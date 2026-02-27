import datetime

from requests import Session
from src.adapters.db.models.commit_file import CommitFileModel
from src.adapters.db.repositories.commit_file_repo import CommitFileRepository
from src.adapters.db.base import SessionLocal
from src.adapters.db.repositories.repository_repo import RepositoryRepository
from src.adapters.db.repositories.contributor_repo import ContributorRepository
from src.adapters.db.repositories.commit_repo import CommitRepository
from src.adapters.db.repositories.pull_request_repo import PullRequestRepository
from src.adapters.db.repositories.issue_repo import IssueRepository
from src.data.github_api_response.commits_response_entity import SingleCommitEntity
from src.services.external.github_stats_manual import *
from src.services.internal.preprocessing.files_filter import FilesFilter
from src.services.internal.preprocessing.commit_enricher import CommitEnricher
from src.services.internal.preprocessing.file_language_enricher import (
    FileLanguageEnricher,
)
from src.services.internal.preprocessing.commit_type_detector import (
    HeuristicCommitClassifier,
)
from src.adapters.db.models.commit import CommitModel
from src.util.mapper import (
    git_commit_authors_json_to_dto_list,
    single_commit_dto_to_domain_commit_dto,
    single_commit_json_to_dto,
)
from src.util.logger import logger
from src.services.internal.preprocessing.lang_detector import LanguageDetector

import json
import os
import re


lang_detector = LanguageDetector()


def process_repo(
    owner,
    repo,
    token,
    scope_type,
    scope_id,
    settings,
    since: datetime | None = None,
    max_commits: int | None = None
):
    """
    Обрабатывает репозиторий:
    1) Проверяет, есть ли репо в БД
    2) Если нет, создаёт репо, контрибьюторов и все коммиты
    3) Если есть, добавляет только новые коммиты и новых контрибьюторов
    """

    #TODO: Получить настройки по id

    commits = get_commits_list(
        owner,
        repo,
        token=token,
        since=since,
        max_commits=max_commits,
    )
    contributors = get_contributors(owner, repo, token=token)

    dto_contributors = git_commit_authors_json_to_dto_list(contributors)

    with SessionLocal() as session:
        repo_repo = RepositoryRepository(session)
        contributor_repo = ContributorRepository(session)
        commit_repo = CommitRepository(session)

        # ----------------------
        # Репозиторий
        # ----------------------
        db_repo = repo_repo.get_by_owner_name(owner, repo)
        if not db_repo:
            db_repo = repo_repo.create(
                owner=owner,
                name=repo,
                vcs_provider="github",
                external_id=None,
                url=f"https://github.com/{owner}/{repo}",
            )
            logger.info("Created repo in DB: %s/%s", owner, repo)
        else:
            logger.info("Repo already exists in DB: %s/%s", owner, repo)

        # ----------------------
        # Контрибьюторы
        # ----------------------
        db_contributors = {}
        for c in dto_contributors:
            db_c, created = contributor_repo.get_or_create(
                vcs_provider="github",
                external_id=(
                    str(c.id) if hasattr(c, "id") else None
                ),  # используем GitHub numeric ID
                login=c.login,
                profile_url=c.html_url,
            )
            db_contributors[c.login] = db_c.id  # Сохраняем только ID, не объект

        # ----------------------
        # Коммиты
        # ----------------------
        existing_shas = get_existing_commit_shas(
            session, db_repo.id
        )  # ← функция, вернёт set
        new_commits = []

        # Инициализация пайплайна обогащения
        files_filter = FilesFilter()
        file_enricher = FileLanguageEnricher(lang_detector)
        commit_type_detector = HeuristicCommitClassifier()
        commit_enricher = CommitEnricher(
            file_enricher=file_enricher, commit_type_detector=commit_type_detector
        )
        commit_file_repo = CommitFileRepository(session)

        for commit_json in commits:
            if "author" not in commit_json or not commit_json["author"]:
                continue
            login = commit_json["author"]["login"]
            sha = commit_json["sha"]
            if sha in existing_shas:
                continue  # Уже есть в БД

            try:
                # Получаем полный коммит с файлами и статистикой
                full_commit_json = get_commit(owner, repo, sha, token=token)

                # Преобразуем в domain commit
                commit_dto = single_commit_json_to_dto(full_commit_json)
                commit_obj = single_commit_dto_to_domain_commit_dto(commit_dto)

                # Фильтрация и обогащение
                commit_obj = files_filter.filter(commit_obj)
                commit_obj = commit_enricher.enrich(
                    commit_obj, commit_dto, settings, session
                )

                # Создаем коммит в БД с базовыми полями
                db_commit = commit_repo.create(
                    repository_id=db_repo.id,
                    contributor_id=(
                        db_contributors.get(login)
                        if login in db_contributors
                        else None
                    ),
                    sha=commit_obj.sha,
                    message=commit_obj.message,
                )

                # Обновляем метаданные коммита
                commit_repo.update_details(
                    commit_id=db_commit.id,
                    authored_at=commit_dto.commit.author.date,
                    committed_at=commit_dto.commit.committer.date,
                    author_name=commit_dto.commit.author.name,
                    author_email=commit_dto.commit.author.email,
                    additions=commit_dto.stats.additions if commit_dto.stats else None,
                    deletions=commit_dto.stats.deletions if commit_dto.stats else None,
                    changes=commit_dto.stats.total if commit_dto.stats else None,
                    commit_type=commit_obj.commit_type,
                    is_conventional=commit_obj.is_conventional,
                    conventional_type=commit_obj.conventional_type,
                    conventional_scope=commit_obj.conventional_scope,
                    is_breaking_change=commit_obj.is_breaking_change,
                    is_merge_commit=commit_obj.is_merge_commit,
                    is_revert_commit=commit_obj.is_revert_commit,
                    parents_count=commit_obj.parents_count,
                    files_changed=commit_obj.files_changed,
                )

                # Сохраняем файлы коммита
                files_models = []
                for f in commit_obj.files:
                    files_models.append(
                        CommitFileModel(
                            commit_id=db_commit.id,
                            file_path=f.path,
                            additions=f.additions,
                            deletions=f.deletions,
                            changes=(
                                f.additions + f.deletions
                                if f.additions is not None and f.deletions is not None
                                else None
                            ),
                            language=f.language,
                            patch=f.patch,
                        )
                    )

                if files_models:
                    commit_file_repo.bulk_create(files_models)
                    session.commit()  # Коммитим все изменения

                new_commits.append(db_commit)

            except Exception as e:
                logger.exception(f"Failed to process commit {sha}: {e}")
                continue

        logger.info("Added %d new commits for %s/%s", len(new_commits), owner, repo)

        # ----------------------
        # Pull Requests
        # ----------------------
        pr_repo = PullRequestRepository(session)
        issue_repo = IssueRepository(session)
        new_prs = 0
        new_issues_count = 0

        try:
            prs = get_pull_requests(owner, repo, token=token, since=since)
            for pr_json in prs:
                author = pr_json.get("user") or {}
                pr_created = None
                pr_closed = None
                pr_merged = None
                if pr_json.get("created_at"):
                    pr_created = datetime.datetime.fromisoformat(
                        pr_json["created_at"].replace("Z", "+00:00")
                    )
                if pr_json.get("closed_at"):
                    pr_closed = datetime.datetime.fromisoformat(
                        pr_json["closed_at"].replace("Z", "+00:00")
                    )
                if pr_json.get("merged_at"):
                    pr_merged = datetime.datetime.fromisoformat(
                        pr_json["merged_at"].replace("Z", "+00:00")
                    )

                author_login = author.get("login")
                contributor_id = None
                if author_login and author_login in db_contributors:
                    contributor_id = db_contributors[author_login]

                state = pr_json.get("state", "open")
                if pr_json.get("merged_at"):
                    state = "merged"

                _, created = pr_repo.get_or_create(
                    repository_id=db_repo.id,
                    number=pr_json.get("number", 0),
                    title=pr_json.get("title", ""),
                    state=state,
                    author_login=author_login,
                    author_avatar=author.get("avatar_url"),
                    contributor_id=contributor_id,
                    external_id=pr_json.get("id"),
                    pr_created_at=pr_created,
                    pr_closed_at=pr_closed,
                    pr_merged_at=pr_merged,
                )
                if created:
                    new_prs += 1
        except Exception as e:
            logger.warning("Failed to fetch pull requests for %s/%s: %s", owner, repo, e)

        # ----------------------
        # Issues
        # ----------------------
        try:
            issues = get_issues(owner, repo, token=token, since=since)
            for issue_json in issues:
                author = issue_json.get("user") or {}
                issue_created = None
                issue_closed = None
                if issue_json.get("created_at"):
                    issue_created = datetime.datetime.fromisoformat(
                        issue_json["created_at"].replace("Z", "+00:00")
                    )
                if issue_json.get("closed_at"):
                    issue_closed = datetime.datetime.fromisoformat(
                        issue_json["closed_at"].replace("Z", "+00:00")
                    )

                author_login = author.get("login")
                contributor_id = None
                if author_login and author_login in db_contributors:
                    contributor_id = db_contributors[author_login]

                _, created = issue_repo.get_or_create(
                    repository_id=db_repo.id,
                    number=issue_json.get("number", 0),
                    title=issue_json.get("title", ""),
                    state=issue_json.get("state", "open"),
                    author_login=author_login,
                    author_avatar=author.get("avatar_url"),
                    contributor_id=contributor_id,
                    external_id=issue_json.get("id"),
                    issue_created_at=issue_created,
                    issue_closed_at=issue_closed,
                )
                if created:
                    new_issues_count += 1
        except Exception as e:
            logger.warning("Failed to fetch issues for %s/%s: %s", owner, repo, e)

        logger.info(
            "Added %d PRs and %d issues for %s/%s",
            new_prs, new_issues_count, owner, repo,
        )

    process_repo_response = {
        "new-commits": str(len(new_commits)),
        "new-prs": str(new_prs),
        "new-issues": str(new_issues_count),
        "repository": repo,
        "owner": owner,
    }
    return process_repo_response


def process_single_commit(
    commit_json: dict,
    owner: str,
    repo: str,
    token: str,
    settings: str,
    db_repo_id: int,
    db_contributors: dict,
    session: SessionLocal,
) -> dict:
    """
    Обрабатывает один коммит: получает детали, обогащает, сохраняет в БД.
    Thread-safe функция для использования в многопоточном режиме.

    Args:
        commit_json: Сокращенная информация о коммите из списка
        owner: Владелец репозитория
        repo: Название репозитория
        token: GitHub токен
        settings: JSON строка с настройками анализа
        db_repo_id: ID репозитория в БД
        db_contributors: Словарь {login: contributor_id}
        session: SQLAlchemy сессия

    Returns:
        dict с полями:
            - created: bool - был ли создан новый коммит
            - sha: str - SHA коммита

    Raises:
        Exception: При ошибках обработки
    """
    if "author" not in commit_json or not commit_json["author"]:
        return {"created": False, "sha": commit_json["sha"]}

    login = commit_json["author"]["login"]
    sha = commit_json["sha"]

    # Получаем полный коммит с файлами и статистикой
    full_commit_json = get_commit(owner, repo, sha, token=token)

    # Преобразуем в domain commit
    commit_dto = single_commit_json_to_dto(full_commit_json)
    commit_obj = single_commit_dto_to_domain_commit_dto(commit_dto)

    # Инициализация пайплайна обогащения
    files_filter = FilesFilter()
    file_enricher = FileLanguageEnricher(lang_detector)
    commit_type_detector = HeuristicCommitClassifier()
    commit_enricher = CommitEnricher(
        file_enricher=file_enricher, commit_type_detector=commit_type_detector
    )

    # Фильтрация и обогащение
    commit_obj = files_filter.filter(commit_obj)
    commit_obj = commit_enricher.enrich(
        commit_obj, commit_dto, settings, session
    )

    # Получаем репозитории
    commit_repo = CommitRepository(session)
    commit_file_repo = CommitFileRepository(session)

    # Создаем коммит в БД с базовыми полями
    db_commit = commit_repo.create(
        repository_id=db_repo_id,
        contributor_id=(
            db_contributors.get(login)
            if login in db_contributors
            else None
        ),
        sha=commit_obj.sha,
        message=commit_obj.message,
    )

    # Обновляем метаданные коммита
    commit_repo.update_details(
        commit_id=db_commit.id,
        authored_at=commit_dto.commit.author.date,
        committed_at=commit_dto.commit.committer.date,
        author_name=commit_dto.commit.author.name,
        author_email=commit_dto.commit.author.email,
        additions=commit_dto.stats.additions if commit_dto.stats else None,
        deletions=commit_dto.stats.deletions if commit_dto.stats else None,
        changes=commit_dto.stats.total if commit_dto.stats else None,
        commit_type=commit_obj.commit_type,
        is_conventional=commit_obj.is_conventional,
        conventional_type=commit_obj.conventional_type,
        conventional_scope=commit_obj.conventional_scope,
        is_breaking_change=commit_obj.is_breaking_change,
        is_merge_commit=commit_obj.is_merge_commit,
        is_revert_commit=commit_obj.is_revert_commit,
        parents_count=commit_obj.parents_count,
        files_changed=commit_obj.files_changed,
    )

    # Сохраняем файлы коммита
    files_models = []
    for f in commit_obj.files:
        files_models.append(
            CommitFileModel(
                commit_id=db_commit.id,
                file_path=f.path,
                additions=f.additions,
                deletions=f.deletions,
                changes=(
                    f.additions + f.deletions
                    if f.additions is not None and f.deletions is not None
                    else None
                ),
                language=f.language,
                patch=f.patch,
            )
        )

    if files_models:
        commit_file_repo.bulk_create(files_models)
        session.commit()  # Коммитим все изменения

    logger.debug("Processed commit %s for %s/%s", sha[:7], owner, repo)

    return {"created": True, "sha": sha}


# ----------------------
# Получаем все sha коммитов для репо
# ----------------------
def get_existing_commit_shas(session, repo_id):
    shas = (
        session.query(CommitModel.sha)
        .filter(CommitModel.repository_id == repo_id)
        .all()
    )
    return set(s[0] for s in shas)
