from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable
import threading

from src.adapters.db.base import SessionLocal
from src.services.internal.process import process_single_commit, get_existing_commit_shas
from src.services.external.github_stats_manual import get_commits_list, get_contributors
from src.adapters.db.repositories.contributor_repo import ContributorRepository
from src.util.logger import logger


@dataclass
class SyncProgress:
    """Модель прогресса синхронизации"""
    total_commits: int = 0
    processed_commits: int = 0
    total_pages: int = 0
    processed_pages: int = 0
    current_phase: str = "initializing"  # initializing, fetching_list, processing_sprint, processing_archive, complete
    sprint_commits_done: bool = False
    errors: list[str] = field(default_factory=list)
    start_time: datetime | None = None

    @property
    def progress_percent(self) -> int:
        """Вычисляет процент выполнения"""
        if self.total_commits == 0:
            return 0
        return int((self.processed_commits / self.total_commits) * 100)


class SyncOrchestrator:
    """
    Оркестрирует многопоточную синхронизацию с приоритетной загрузкой.

    Процесс:
    1. Получение списка всех коммитов (пагинация)
    2. Разделение на sprint (последние N дней) и archive
    3. Параллельная обработка sprint коммитов (приоритет)
    4. Параллельная обработка archive коммитов
    """

    def __init__(
        self,
        rate_limiter: "RateLimiter",
        max_workers: int = 5,
        progress_callback: Callable[[SyncProgress], None] | None = None
    ):
        """
        Инициализирует оркестратор.

        Args:
            rate_limiter: Rate limiter для соблюдения лимитов GitHub API
            max_workers: Максимальное количество worker threads
            progress_callback: Функция для уведомления о прогрессе
        """
        self.rate_limiter = rate_limiter
        self.max_workers = max_workers
        self.progress_callback = progress_callback
        self.progress = SyncProgress()
        self.lock = threading.Lock()

    def sync_repository(
        self,
        owner: str,
        repo: str,
        token: str,
        settings: str,
        db_repo_id: int,
        sprint_days: int = 14
    ) -> dict:
        """
        Синхронизирует репозиторий с приоритетной загрузкой спринта.

        Args:
            owner: Владелец репозитория
            repo: Название репозитория
            token: GitHub токен
            settings: JSON строка с настройками анализа
            db_repo_id: ID репозитория в БД
            sprint_days: Количество дней для спринта (приоритетная загрузка)

        Returns:
            dict с результатами синхронизации:
                - total_commits: общее количество коммитов
                - processed_commits: количество обработанных
                - sprint_commits: количество коммитов в спринте
                - archive_commits: количество архивных коммитов
                - new_commits: количество новых коммитов
                - errors: список ошибок
        """
        self.progress.start_time = datetime.now(timezone.utc)
        logger.info("Starting sync for %s/%s", owner, repo)

        # Фаза 1: Получение списка SHA
        self.progress.current_phase = "fetching_list"
        self._notify_progress()

        sprint_cutoff = datetime.now(timezone.utc) - timedelta(days=sprint_days)

        try:
            all_commits_list = self._fetch_commits_list_paginated(
                owner, repo, token
            )
        except Exception as e:
            logger.error("Failed to fetch commits list: %s", e)
            self.progress.errors.append(f"Failed to fetch commits: {str(e)}")
            self._notify_progress()
            raise

        # Разделение на sprint и archive
        sprint_commits = []
        archive_commits = []

        for commit_json in all_commits_list:
            try:
                commit_date_str = commit_json.get("commit", {}).get("author", {}).get("date")
                if commit_date_str:
                    commit_date = datetime.fromisoformat(commit_date_str.replace("Z", "+00:00"))
                    if commit_date >= sprint_cutoff:
                        sprint_commits.append(commit_json)
                    else:
                        archive_commits.append(commit_json)
                else:
                    # Если нет даты, считаем архивным
                    archive_commits.append(commit_json)
            except Exception as e:
                logger.warning("Failed to parse commit date for %s: %s", commit_json.get("sha", "?"), e)
                archive_commits.append(commit_json)

        self.progress.total_commits = len(all_commits_list)
        logger.info(
            "Split commits: %d sprint, %d archive (total %d)",
            len(sprint_commits), len(archive_commits), len(all_commits_list)
        )
        self._notify_progress()

        # Подготовка: контрибьюторы
        db_contributors = self._prepare_contributors(owner, repo, token, db_repo_id)

        # Фаза 2: Обработка sprint коммитов (приоритет)
        self.progress.current_phase = "processing_sprint"
        self._notify_progress()

        sprint_results = self._process_commits_parallel(
            sprint_commits, owner, repo, token, settings, db_repo_id, db_contributors
        )

        self.progress.sprint_commits_done = True
        logger.info("Sprint commits processed: %d new", sprint_results["new"])
        self._notify_progress()

        # Фаза 3: Обработка archive коммитов
        self.progress.current_phase = "processing_archive"
        self._notify_progress()

        archive_results = self._process_commits_parallel(
            archive_commits, owner, repo, token, settings, db_repo_id, db_contributors
        )

        logger.info("Archive commits processed: %d new", archive_results["new"])

        # Фаза 4: Завершение
        self.progress.current_phase = "complete"
        self._notify_progress()

        total_new = sprint_results["new"] + archive_results["new"]
        logger.info("Sync completed for %s/%s: %d new commits", owner, repo, total_new)

        return {
            "total_commits": self.progress.total_commits,
            "processed_commits": self.progress.processed_commits,
            "sprint_commits": len(sprint_commits),
            "archive_commits": len(archive_commits),
            "new_commits": total_new,
            "errors": self.progress.errors,
        }

    def _fetch_commits_list_paginated(
        self, owner: str, repo: str, token: str
    ) -> list[dict]:
        """
        Получает список всех коммитов с пагинацией.

        Args:
            owner: Владелец репозитория
            repo: Название репозитория
            token: GitHub токен

        Returns:
            Список коммитов (сокращенная форма из списка)
        """
        logger.info("Fetching commits list for %s/%s", owner, repo)
        commits = get_commits_list(owner, repo, token=token)
        logger.info("Fetched %d commits", len(commits))
        return commits

    def _prepare_contributors(
        self, owner: str, repo: str, token: str, db_repo_id: int
    ) -> dict:
        """
        Получает и создает контрибьюторов в БД.

        Args:
            owner: Владелец репозитория
            repo: Название репозитория
            token: GitHub токен
            db_repo_id: ID репозитория в БД

        Returns:
            Словарь {login: contributor_id}
        """
        from src.services.external.github_stats_manual import get_contributors
        from src.util.mapper import git_commit_authors_json_to_dto_list

        logger.info("Fetching contributors for %s/%s", owner, repo)

        contributors_json = get_contributors(owner, repo, token=token)
        dto_contributors = git_commit_authors_json_to_dto_list(contributors_json)

        db_contributors = {}
        with SessionLocal() as session:
            contributor_repo = ContributorRepository(session)

            for c in dto_contributors:
                db_c, created = contributor_repo.get_or_create(
                    vcs_provider="github",
                    external_id=(
                        str(c.id) if hasattr(c, "id") else None
                    ),
                    login=c.login,
                    profile_url=c.html_url,
                )
                db_contributors[c.login] = db_c.id  # Сохраняем только ID, не объект

        logger.info("Prepared %d contributors", len(db_contributors))
        return db_contributors

    def _process_commits_parallel(
        self,
        commits_list: list[dict],
        owner: str,
        repo: str,
        token: str,
        settings: str,
        db_repo_id: int,
        db_contributors: dict
    ) -> dict:
        """
        Параллельно обрабатывает список коммитов.

        Args:
            commits_list: Список коммитов для обработки
            owner: Владелец репозитория
            repo: Название репозитория
            token: GitHub токен
            settings: JSON строка с настройками
            db_repo_id: ID репозитория в БД
            db_contributors: Словарь {login: contributor_id}

        Returns:
            dict с полями:
                - new: количество новых коммитов
                - skipped: количество пропущенных
        """
        new_count = 0
        skipped_count = 0

        # Получаем существующие SHA из БД
        with SessionLocal() as session:
            existing_shas = get_existing_commit_shas(session, db_repo_id)

        # Фильтруем уже существующие
        commits_to_process = [
            c for c in commits_list if c["sha"] not in existing_shas
        ]
        skipped_count = len(commits_list) - len(commits_to_process)

        if skipped_count > 0:
            logger.info("Skipping %d existing commits", skipped_count)

        if not commits_to_process:
            logger.info("No new commits to process")
            return {"new": 0, "skipped": skipped_count}

        # Обрабатываем в пуле потоков
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(
                    self._process_single_commit_wrapper,
                    commit_json, owner, repo, token, settings, db_repo_id, db_contributors
                ): commit_json["sha"]
                for commit_json in commits_to_process
            }

            for future in as_completed(futures):
                sha = futures[future]
                try:
                    result = future.result()
                    if result["created"]:
                        new_count += 1

                    with self.lock:
                        self.progress.processed_commits += 1
                        self._notify_progress()

                except Exception as e:
                    logger.error("Failed to process commit %s: %s", sha[:7], e)
                    with self.lock:
                        self.progress.errors.append(f"Commit {sha[:7]}: {str(e)}")
                        self.progress.processed_commits += 1
                        self._notify_progress()

        return {"new": new_count, "skipped": skipped_count}

    def _process_single_commit_wrapper(
        self,
        commit_json: dict,
        owner: str,
        repo: str,
        token: str,
        settings: str,
        db_repo_id: int,
        db_contributors: dict
    ) -> dict:
        """
        Обёртка для обработки одного коммита с rate limiting и session management.

        Args:
            commit_json: Сокращенная информация о коммите
            owner: Владелец репозитория
            repo: Название репозитория
            token: GitHub токен
            settings: JSON строка с настройками
            db_repo_id: ID репозитория в БД
            db_contributors: Словарь {login: contributor_id}

        Returns:
            dict с полями created и sha
        """
        # Rate limiting
        self.rate_limiter.acquire()

        # Создаем отдельную сессию для этого потока
        with SessionLocal() as session:
            try:
                result = process_single_commit(
                    commit_json=commit_json,
                    owner=owner,
                    repo=repo,
                    token=token,
                    settings=settings,
                    db_repo_id=db_repo_id,
                    db_contributors=db_contributors,
                    session=session
                )
                return result
            except Exception as e:
                logger.error("Error processing commit %s: %s", commit_json.get("sha", "?"), e)
                raise

    def _notify_progress(self):
        """Уведомляет callback о прогрессе"""
        if self.progress_callback:
            try:
                self.progress_callback(self.progress)
            except Exception as e:
                logger.warning("Progress callback failed: %s", e)
