import json
from urllib.parse import urlparse
from copy import deepcopy
import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy import select

from src.api.dependencies import get_db, get_current_user
from src.adapters.db.models.user import UserModel
from src.adapters.db.repositories.team_repo import TeamRepository
from src.adapters.db.repositories.project_repo import ProjectRepository
from src.adapters.db.repositories.organization_repo import OrganizationRepository
from src.adapters.db.repositories.repository_repo import RepositoryRepository
from src.adapters.db.repositories.user_repo import UserRepository
from src.adapters.db.repositories.sync_session_repo import SyncSessionRepository
from src.adapters.db.repositories.commit_repo import CommitRepository
from src.adapters.db.models.sync_session import SyncStatus, SyncSessionModel
from src.adapters.db.models.commit import CommitModel
from src.adapters.db.models.commit_file import CommitFileModel
from src.adapters.db.models.team_member import TeamMemberModel
from src.adapters.db.models.pull_request import PullRequestModel
from src.adapters.db.models.issue import IssueModel
from src.services.internal.rate_limiter import RateLimiter
from src.services.internal.sync_orchestrator import SyncOrchestrator
from src.services.external.github_stats_manual import get_commit_count
from src.data.enums.vcs import VCS
from src.util.logger import logger


router = APIRouter(prefix="/team", tags=["team"])

# Глобальный rate limiter для всех запросов к GitHub API
_global_rate_limiter = RateLimiter(max_requests=4800, time_window_seconds=3600)

VCS_HOSTS: dict[str, VCS] = {
    "github.com": VCS.github,
    "gitlab.com": VCS.gitlab,
    "bitbucket.org": VCS.bitbucket,
}


def parse_repo_url(url: str) -> tuple[VCS, str, str]:
    """Returns (vcs, owner, repo_name) from a repository URL."""
    if not url.startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    host = parsed.netloc.lower().lstrip("www.")
    vcs = VCS_HOSTS.get(host, VCS.svn)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        raise ValueError(f"Cannot parse owner/repo from URL: {url}")
    owner = parts[0]
    name = parts[1].removesuffix(".git")
    return vcs, owner, name


class TeamCreate(BaseModel):
    name: str
    project_id: int


class TeamResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: int
    name: str
    project_id: int
    manager_id: int
    vcs: str


@router.post("/create", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
def create_team(
    data: TeamCreate,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proj_repo = ProjectRepository(db)
    project = proj_repo.get_by_id(data.project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.manager_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the manager of this project")

    team_repo = TeamRepository(db)
    if team_repo.get_by_name_and_project(data.name, data.project_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Team with this name already exists in this project")

    team = team_repo.create(
        name=data.name,
        project_id=data.project_id,
        manager_id=current_user.id,
        vcs=project.vcs,
        analysis_config="{}",
        workflow_config="{}",
        metrics_config="{}",
        global_config="{}",
    )
    return team


@router.get("/by-project/{project_id}", response_model=list[TeamResponse])
def get_teams_by_project(
    project_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proj_repo = ProjectRepository(db)
    project = proj_repo.get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    team_repo = TeamRepository(db)
    return team_repo.get_by_project(project_id)


class RepoAdd(BaseModel):
    url: str


class RepoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: int
    url: str
    owner: str
    name: str
    vcs_provider: str
    team_id: int | None


@router.post("/{team_id}/repos", response_model=RepoResponse, status_code=status.HTTP_201_CREATED)
def add_repo_to_team(
    team_id: int,
    data: RepoAdd,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    team_repo = TeamRepository(db)
    team = team_repo.get_by_id(team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    if team.manager_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the manager of this team")

    try:
        vcs, owner, name = parse_repo_url(data.url)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    repo_repo = RepositoryRepository(db)
    existing = repo_repo.get_by_url(data.url)
    if existing and existing.team_id == team_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Repository already added to this team")

    repo = repo_repo.create(
        url=data.url,
        owner=owner,
        name=name,
        vcs_provider=vcs,
        project_id=team.project_id,
        team_id=team_id,
    )
    return repo


@router.get("/{team_id}/repos", response_model=list[RepoResponse])
def get_team_repos(
    team_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    team_repo = TeamRepository(db)
    if not team_repo.get_by_id(team_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    repo_repo = RepositoryRepository(db)
    return repo_repo.get_by_team(team_id)


@router.delete("/{team_id}/repos/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_repo_from_team(
    team_id: int,
    repo_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    team_repo = TeamRepository(db)
    team = team_repo.get_by_id(team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    if team.manager_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the manager of this team")

    repo_repo = RepositoryRepository(db)
    repo = repo_repo.get_by_id(repo_id)
    if not repo or repo.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found in this team")

    repo_repo.delete(repo_id)


# ───────────────────────── Settings ─────────────────────────

DEFAULT_ANALYSIS_CONFIG: dict[str, Any] = {
    "file_filters": {
        "exclude_patterns": [
            "*.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
            "*.min.js", "*.min.css", "dist/", "build/", "node_modules/",
            "__pycache__/", "*.pyc", "*.egg-info/",
        ],
        "exclude_hidden": True,
    },
    "commit_rules": {
        "default_category": "NO CATEGORY",
        "rules": [
            {"name": "Feature", "category": "feat", "keywords": ["feat", "add", "new", "implement", "introduce"], "priority": 95},
            {"name": "Bugfix", "category": "fix", "keywords": ["fix", "bug", "patch", "resolve", "repair"], "priority": 99},
            {"name": "Performance", "category": "perf", "keywords": ["perf", "performance", "optimize", "speed"], "priority": 85},
            {"name": "Refactor", "category": "refactor", "keywords": ["refactor", "restructure", "rework", "reorganize", "simplify"], "priority": 80},
            {"name": "Tests", "category": "test", "keywords": ["test", "spec", "coverage"], "priority": 75},
            {"name": "Docs", "category": "docs", "keywords": ["docs", "doc", "readme", "changelog", "document"], "priority": 70},
            {"name": "Chore", "category": "chore", "keywords": ["chore", "build", "ci", "cd", "deps", "upgrade", "bump"], "priority": 60},
            {"name": "Style", "category": "style", "keywords": ["style", "format", "lint", "prettier", "whitespace"], "priority": 55},
            {"name": "Revert", "category": "revert", "keywords": ["revert", "rollback"], "priority": 90},
            {"name": "Merge", "category": "merge", "keywords": ["merge pull request", "merge branch", "merge mr"], "priority": 120},
        ],
    },
    "special_commits": {
        "include_merge_commits": False,
        "include_revert_commits": True,
        "bot_logins": ["dependabot[bot]", "renovate[bot]", "github-actions[bot]"],
    },
    "breaking_change_markers": ["!", "BREAKING CHANGE", "BREAKING-CHANGE"],
}

DEFAULT_WORKFLOW_CONFIG: dict[str, Any] = {
    "sprint": {
        "enabled": False,
        "duration_days": 14,
    },
    "working_hours": {
        "start": 9,
        "end": 18,
        "timezone": "UTC",
    },
    "working_days": [1, 2, 3, 4, 5],
}

DEFAULT_METRICS_CONFIG: dict[str, Any] = {
    "commit_weights": {
        "feat": 3.0,
        "fix": 2.0,
        "refactor": 2.0,
        "test": 1.5,
        "perf": 2.5,
        "docs": 0.5,
        "style": 0.5,
        "chore": 0.5,
        "ci": 0.5,
        "build": 0.5,
        "revert": 0.0,
    },
    "significant_commit_min_lines": 5,
    "require_conventional_commits": False,
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Рекурсивно мержит override поверх base."""
    result = deepcopy(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


class TeamSettingsResponse(BaseModel):
    analysis_config: dict[str, Any]
    workflow_config: dict[str, Any]
    metrics_config: dict[str, Any]


class TeamSettingsUpdate(BaseModel):
    analysis_config: dict[str, Any] | None = None
    workflow_config: dict[str, Any] | None = None
    metrics_config: dict[str, Any] | None = None


@router.get("/{team_id}/settings", response_model=TeamSettingsResponse)
def get_team_settings(
    team_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    team_repo = TeamRepository(db)
    team = team_repo.get_by_id(team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    if team.manager_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the manager of this team")

    stored_analysis = json.loads(team.analysis_config or "{}")
    stored_workflow = json.loads(team.workflow_config or "{}")
    stored_metrics = json.loads(team.metrics_config or "{}")

    return TeamSettingsResponse(
        analysis_config=_deep_merge(DEFAULT_ANALYSIS_CONFIG, stored_analysis),
        workflow_config=_deep_merge(DEFAULT_WORKFLOW_CONFIG, stored_workflow),
        metrics_config=_deep_merge(DEFAULT_METRICS_CONFIG, stored_metrics),
    )


@router.put("/{team_id}/settings", response_model=TeamSettingsResponse)
def update_team_settings(
    team_id: int,
    data: TeamSettingsUpdate,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    team_repo = TeamRepository(db)
    team = team_repo.get_by_id(team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    if team.manager_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the manager of this team")

    if data.analysis_config is not None:
        team.analysis_config = json.dumps(data.analysis_config)
    if data.workflow_config is not None:
        team.workflow_config = json.dumps(data.workflow_config)
    if data.metrics_config is not None:
        team.metrics_config = json.dumps(data.metrics_config)

    db.commit()
    db.refresh(team)

    stored_analysis = json.loads(team.analysis_config or "{}")
    stored_workflow = json.loads(team.workflow_config or "{}")
    stored_metrics = json.loads(team.metrics_config or "{}")

    return TeamSettingsResponse(
        analysis_config=_deep_merge(DEFAULT_ANALYSIS_CONFIG, stored_analysis),
        workflow_config=_deep_merge(DEFAULT_WORKFLOW_CONFIG, stored_workflow),
        metrics_config=_deep_merge(DEFAULT_METRICS_CONFIG, stored_metrics),
    )


# ───────────────────────── Sync ─────────────────────────

class ActiveSyncSession(BaseModel):
    """Информация об активной сессии синхронизации"""
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    session_id: int
    repository_id: int
    status: str
    progress_percent: float
    current_phase: str
    sprint_commits_done: bool
    total_commits: int
    processed_commits: int


class SyncStatusResponse(BaseModel):
    """Статус синхронизации команды"""
    has_data: bool
    last_sync: datetime | None
    total_commits_in_db: int
    active_sync_sessions: list[ActiveSyncSession]
    needs_initial_sync: bool


@router.get("/{team_id}/sync-status", response_model=SyncStatusResponse)
def get_sync_status(
    team_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Получает статус синхронизации команды:
    - Наличие данных в БД
    - Активные сессии синхронизации
    - Время последней синхронизации
    """
    team_repo = TeamRepository(db)
    if not team_repo.get_by_id(team_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    # Проверяем наличие коммитов
    commit_repo = CommitRepository(db)
    total_commits = commit_repo.count_by_team(team_id)

    # Получаем активные сессии
    sync_repo = SyncSessionRepository(db)
    active_sessions = sync_repo.get_active_by_team(team_id)

    # Находим последнюю завершенную синхронизацию
    from src.adapters.db.models.sync_session import SyncStatus as SyncStatusEnum
    stmt = (
        select(SyncSessionModel)
        .where(
            SyncSessionModel.team_id == team_id,
            SyncSessionModel.status == SyncStatusEnum.completed
        )
        .order_by(SyncSessionModel.completed_at.desc())
        .limit(1)
    )
    last_completed_session = db.scalar(stmt)

    # Формируем список активных сессий с расчетом прогресса
    active_sync_sessions = []
    for session in active_sessions:
        progress_percent = 0.0
        if session.total_commits and session.total_commits > 0:
            progress_percent = (session.processed_commits / session.total_commits) * 100

        active_sync_sessions.append(ActiveSyncSession(
            session_id=session.id,
            repository_id=session.repository_id,
            status=session.status.value if hasattr(session.status, 'value') else session.status,
            progress_percent=round(progress_percent, 2),
            current_phase=session.current_phase or "initializing",
            sprint_commits_done=session.sprint_commits_done or False,
            total_commits=session.total_commits or 0,
            processed_commits=session.processed_commits or 0,
        ))

    return SyncStatusResponse(
        has_data=total_commits > 0,
        last_sync=last_completed_session.completed_at if last_completed_session else None,
        total_commits_in_db=total_commits,
        active_sync_sessions=active_sync_sessions,
        needs_initial_sync=total_commits == 0 and len(active_sessions) == 0,
    )


# Кэш для check-updates (5 минут TTL)
_check_updates_cache: dict[int, tuple[dict, float]] = {}
_CACHE_TTL = 300  # 5 минут


class RepositoryUpdateInfo(BaseModel):
    """Информация об обновлениях репозитория"""
    id: int
    name: str
    owner: str
    commits_in_db: int
    commits_in_github: int | None
    has_new_commits: bool
    new_commits_count: int
    error: str | None = None


class CheckUpdatesResponse(BaseModel):
    """Результат проверки обновлений команды"""
    repositories: list[RepositoryUpdateInfo]
    total_new_commits: int
    checked_at: datetime


@router.get("/{team_id}/check-updates", response_model=CheckUpdatesResponse)
def check_team_updates(
    team_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Проверяет наличие новых коммитов в GitHub для всех репозиториев команды.
    Результат кэшируется на 5 минут.
    """
    # Проверяем кэш
    if team_id in _check_updates_cache:
        cached_data, cached_time = _check_updates_cache[team_id]
        if time.time() - cached_time < _CACHE_TTL:
            logger.debug("Returning cached check-updates for team %d", team_id)
            return cached_data

    team_repo = TeamRepository(db)
    team = team_repo.get_by_id(team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    # Получаем GitHub токен
    user_repo = UserRepository(db)
    github_token = user_repo.get_github_token(current_user)
    if not github_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub token not configured",
        )

    # Получаем репозитории команды
    repo_repo = RepositoryRepository(db)
    repos = repo_repo.get_by_team(team_id)

    if not repos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No repositories linked to this team",
        )

    # Параллельно проверяем каждый репозиторий
    commit_repo = CommitRepository(db)
    repositories_info = []
    total_new = 0

    for repo in repos:
        # Количество коммитов в БД
        db_count = commit_repo.count_by_repository(repo.id)

        # Попытка получить количество из GitHub
        github_count = None
        error_msg = None
        has_new = False
        new_count = 0

        try:
            github_count = get_commit_count(repo.owner, repo.name, github_token)
            if github_count > db_count:
                has_new = True
                new_count = github_count - db_count
                total_new += new_count
        except Exception as e:
            logger.warning("Failed to check updates for %s/%s: %s", repo.owner, repo.name, e)
            error_msg = str(e)

        repositories_info.append(RepositoryUpdateInfo(
            id=repo.id,
            name=repo.name,
            owner=repo.owner,
            commits_in_db=db_count,
            commits_in_github=github_count,
            has_new_commits=has_new,
            new_commits_count=new_count,
            error=error_msg,
        ))

    result = CheckUpdatesResponse(
        repositories=repositories_info,
        total_new_commits=total_new,
        checked_at=datetime.now(timezone.utc),
    )

    # Сохраняем в кэш
    _check_updates_cache[team_id] = (result, time.time())

    return result


class SyncResult(BaseModel):
    repository: str
    owner: str
    new_commits: int
    new_prs: int
    new_issues: int
    status: str
    error: str | None = None


@router.post("/{team_id}/sync")
def sync_team_repos(
    team_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Запускает загрузку данных с GitHub для всех репозиториев команды в фоновом режиме.
    Возвращает session_ids для отслеживания прогресса через SSE.
    Использует сохранённый GitHub-токен текущего пользователя.
    """
    logger.info("[team:sync_team_repos] Sync request for team_id=%d from user_id=%d", team_id, current_user.id)

    team_repo = TeamRepository(db)
    team = team_repo.get_by_id(team_id)
    if not team:
        logger.warning("[team:sync_team_repos] Team %d not found", team_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    user_repo = UserRepository(db)
    github_token = user_repo.get_github_token(current_user)
    if not github_token:
        logger.warning("[team:sync_team_repos] No GitHub token for user %d", current_user.id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub token not configured. Go to Settings → VCS Tokens.",
        )

    repo_repo = RepositoryRepository(db)
    repos = repo_repo.get_by_team(team_id)
    if not repos:
        logger.warning("[team:sync_team_repos] No repositories linked to team %d", team_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No repositories linked to this team.",
        )

    logger.info("[team:sync_team_repos] Found %d repositories for team %d", len(repos), team_id)

    # Проверяем количество активных синхронизаций (ограничение 3 на команду)
    sync_repo = SyncSessionRepository(db)
    active_sessions = sync_repo.get_active_by_team(team_id)
    if len(active_sessions) >= 3:
        logger.warning("[team:sync_team_repos] Too many active sessions for team %d: %d", team_id, len(active_sessions))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many active sync sessions ({len(active_sessions)}). Please wait for current syncs to complete.",
        )

    stored_analysis = json.loads(team.analysis_config or "{}")
    settings = json.dumps({
        "commit_rules": stored_analysis.get(
            "commit_rules",
            DEFAULT_ANALYSIS_CONFIG["commit_rules"]
        )
    })

    session_ids = []

    # Создаем sync session для каждого репо и запускаем в фоновом потоке
    for repo in repos:
        logger.info("[team:sync_team_repos] Creating sync session for repo %s/%s (id=%d)",
                   repo.owner, repo.name, repo.id)
        sync_session = sync_repo.create_session(
            team_id=team_id,
            repository_id=repo.id
        )
        session_ids.append(sync_session.id)
        logger.debug("[team:sync_team_repos] Created sync session id=%d for repo %d", sync_session.id, repo.id)

        # Запускаем синхронизацию в отдельном потоке
        logger.info("[team:sync_team_repos] Starting background thread for session %d", sync_session.id)
        thread = threading.Thread(
            target=_sync_repository_background,
            args=(
                sync_session.id,
                repo.owner,
                repo.name,
                repo.id,
                github_token,
                settings,
            ),
            daemon=True,
            name=f"sync-{sync_session.id}"
        )
        thread.start()
        logger.debug("[team:sync_team_repos] Background thread started: %s", thread.name)

    logger.info(
        "[team:sync_team_repos] ✓ Started sync for team %d: %d repositories, session_ids=%s",
        team_id, len(repos), session_ids
    )

    return {
        "session_ids": session_ids,
        "message": f"Synchronization started for {len(repos)} repositories",
        "repositories": [{"id": r.id, "name": r.name, "owner": r.owner} for r in repos],
    }


def _sync_repository_background(
    session_id: int,
    owner: str,
    repo: str,
    db_repo_id: int,
    token: str,
    settings: str,
):
    """
    Фоновая задача синхронизации репозитория.
    Выполняется в отдельном потоке.

    Args:
        session_id: ID сессии синхронизации
        owner: Владелец репозитория
        repo: Название репозитория
        db_repo_id: ID репозитория в БД
        token: GitHub токен
        settings: JSON строка с настройками анализа
    """
    logger.info("[team:_sync_repository_background] Background sync started for session %d: %s/%s",
               session_id, owner, repo)

    from src.adapters.db.base import SessionLocal

    with SessionLocal() as db:
        sync_repo = SyncSessionRepository(db)

        try:
            # Обновляем статус на running
            logger.debug("[team:_sync_repository_background] Fetching sync session %d", session_id)
            sync_session = sync_repo.get_by_id(session_id)
            if not sync_session:
                logger.error("[team:_sync_repository_background] ✗ Sync session %d not found", session_id)
                return

            logger.info("[team:_sync_repository_background] Updating session %d status to running", session_id)
            sync_session.status = SyncStatus.running
            sync_session.started_at = datetime.now(timezone.utc)
            db.commit()

            logger.info("[team:_sync_repository_background] Starting orchestrator for session %d: %s/%s",
                       session_id, owner, repo)

            # Callback для обновления прогресса
            def progress_callback(progress):
                try:
                    logger.debug("[team:_sync_repository_background:progress_callback] Updating progress for session %d: %d/%d commits, phase=%s, sprint_done=%s",
                               session_id, progress.processed_commits, progress.total_commits,
                               progress.current_phase, progress.sprint_commits_done)
                    sync_repo.update_progress(
                        session_id=session_id,
                        total_commits=progress.total_commits,
                        processed_commits=progress.processed_commits,
                        current_phase=progress.current_phase,
                        sprint_commits_done=progress.sprint_commits_done,
                    )
                except Exception as e:
                    logger.warning("[team:_sync_repository_background:progress_callback] ⚠ Failed to update progress for session %d: %s",
                                 session_id, e)

            # Запускаем оркестратор
            logger.info("[team:_sync_repository_background] Initializing orchestrator (max_workers=5, sprint_days=14)")
            orchestrator = SyncOrchestrator(
                rate_limiter=_global_rate_limiter,
                max_workers=5,
                progress_callback=progress_callback
            )

            logger.info("[team:_sync_repository_background] Starting orchestrator.sync_repository()")
            result = orchestrator.sync_repository(
                owner=owner,
                repo=repo,
                token=token,
                settings=settings,
                db_repo_id=db_repo_id,
                sprint_days=14,
                session_id=session_id
            )

            # Финализация
            logger.info("[team:_sync_repository_background] Orchestrator completed, finalizing session %d", session_id)
            sync_session = sync_repo.get_by_id(session_id)

            # Если синхронизация была отменена, не меняем статус
            if not result.get("cancelled"):
                logger.info("[team:_sync_repository_background] Marking session %d as completed", session_id)
                sync_session.status = SyncStatus.completed
                sync_session.completed_at = datetime.now(timezone.utc)

            sync_session.result = result
            sync_session.new_commits = result.get("new_commits", 0)
            if result.get("errors"):
                logger.warning("[team:_sync_repository_background] Session %d completed with %d errors",
                             session_id, len(result["errors"]))
                sync_session.errors = {"errors": result["errors"]}
            db.commit()

            if result.get("cancelled"):
                logger.info("[team:_sync_repository_background] ⚠ Sync for session %d was cancelled", session_id)
            else:
                logger.info(
                    "[team:_sync_repository_background] ✓ Completed sync for session %d: %d new commits (total: %d commits, %d sprint, %d archive)",
                    session_id, result.get("new_commits", 0), result.get("total_commits", 0),
                    result.get("sprint_commits", 0), result.get("archive_commits", 0)
                )

        except Exception as e:
            logger.error("[team:_sync_repository_background] ✗ Sync failed for session %d: %s",
                       session_id, e, exc_info=True)

            # Обработка ошибки
            try:
                logger.info("[team:_sync_repository_background] Updating session %d status to failed", session_id)
                sync_session = sync_repo.get_by_id(session_id)
                if sync_session:
                    sync_session.status = SyncStatus.failed
                    sync_session.completed_at = datetime.now(timezone.utc)
                    sync_session.errors = {"errors": [str(e)]}
                    db.commit()
                    logger.info("[team:_sync_repository_background] Session %d marked as failed", session_id)
            except Exception as db_error:
                logger.error("[team:_sync_repository_background] ✗ Failed to update failed status for session %d: %s",
                           session_id, db_error)


# ───────────────────────── Delete ─────────────────────────

@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(
    team_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Удаляет команду и все связанные данные (репозитории, коммиты, сессии синхронизации).
    Требует права manager команды.
    """
    team_repo = TeamRepository(db)
    team = team_repo.get_by_id(team_id)

    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    if team.manager_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only team manager can delete the team"
        )

    # Ручное каскадное удаление всех связанных данных
    # Удаляем в правильном порядке из-за foreign key constraints

    # 0. СНАЧАЛА отменяем все активные синхронизации
    sync_session_repo = SyncSessionRepository(db)
    active_sessions = sync_session_repo.get_active_by_team(team_id)

    if active_sessions:
        logger.info("Cancelling %d active sync sessions for team %d", len(active_sessions), team_id)
        for session in active_sessions:
            session.status = SyncStatus.cancelled
            session.completed_at = datetime.now(timezone.utc)
        db.commit()

        # Даем потокам время завершиться (до 5 секунд)
        import time
        for i in range(10):
            time.sleep(0.5)
            db.refresh(session)  # Обновляем статус из БД
            # Проверяем, все ли потоки завершились
            remaining = sync_session_repo.get_active_by_team(team_id)
            if not remaining:
                logger.info("All sync threads terminated for team %d", team_id)
                break

    # 1. Получаем все репозитории команды
    logger.info("Step 1: Getting repositories for team %d", team_id)
    repo_repo = RepositoryRepository(db)
    repos = repo_repo.get_by_team(team_id)
    logger.info("Found %d repositories", len(repos))

    # 2. Для каждого репозитория удаляем все связанные данные
    from src.adapters.db.repositories.commit_file_repo import CommitFileRepository
    from src.adapters.db.repositories.pull_request_repo import PullRequestRepository
    from src.adapters.db.repositories.issue_repo import IssueRepository

    commit_repo = CommitRepository(db)
    commit_file_repo = CommitFileRepository(db)

    for idx, repo in enumerate(repos):
        logger.info("Step 2.%d: Processing repository %d (%s)", idx+1, repo.id, repo.name)

        # Получаем ID всех коммитов репозитория
        logger.info("  Getting commit IDs for repo %d", repo.id)
        commit_ids = db.query(CommitModel.id).filter(CommitModel.repository_id == repo.id).all()
        commit_ids = [c_id for (c_id,) in commit_ids]
        logger.info("  Found %d commits", len(commit_ids))

        # Bulk delete commit_files для всех коммитов (батчами по 1000)
        if commit_ids:
            logger.info("  Deleting commit files for %d commits", len(commit_ids))
            batch_size = 1000
            for i in range(0, len(commit_ids), batch_size):
                batch = commit_ids[i:i + batch_size]
                db.query(CommitFileModel).filter(CommitFileModel.commit_id.in_(batch)).delete(synchronize_session=False)
                db.commit()  # Коммитим после каждого батча
                logger.info("  Deleted commit files batch %d-%d", i, min(i + batch_size, len(commit_ids)))
            logger.info("  All commit files deleted")

        # Удаляем коммиты (батчами если их много)
        logger.info("  Deleting %d commits for repo %d", len(commit_ids), repo.id)
        if len(commit_ids) > 1000:
            # Если коммитов много - удаляем батчами
            for i in range(0, len(commit_ids), batch_size):
                batch = commit_ids[i:i + batch_size]
                db.query(CommitModel).filter(CommitModel.id.in_(batch)).delete(synchronize_session=False)
                db.commit()  # Коммитим после каждого батча
                logger.info("  Deleted commits batch %d-%d", i, min(i + batch_size, len(commit_ids)))
        else:
            # Если мало - можно одним запросом
            db.query(CommitModel).filter(CommitModel.repository_id == repo.id).delete(synchronize_session=False)
            db.commit()
        logger.info("  All commits deleted")

        # Удаляем PR и Issues (если есть)
        try:
            logger.info("  Deleting PRs for repo %d", repo.id)
            db.query(PullRequestModel).filter(PullRequestModel.repository_id == repo.id).delete(synchronize_session=False)
        except Exception as e:
            logger.warning("  Failed to delete PRs: %s", e)

        try:
            logger.info("  Deleting issues for repo %d", repo.id)
            db.query(IssueModel).filter(IssueModel.repository_id == repo.id).delete(synchronize_session=False)
        except Exception as e:
            logger.warning("  Failed to delete issues: %s", e)

        # Удаляем sync sessions
        logger.info("  Deleting sync sessions for repo %d", repo.id)
        db.query(SyncSessionModel).filter(SyncSessionModel.repository_id == repo.id).delete(synchronize_session=False)
        logger.info("  Sync sessions deleted")

        # Удаляем репозиторий
        logger.info("  Deleting repository %d", repo.id)
        repo_repo.delete(repo.id)
        logger.info("  Repository deleted")

        # Коммитим изменения после каждого репозитория
        db.commit()
        logger.info("  Changes committed for repo %d", repo.id)

    # 3. Удаляем team_members
    logger.info("Step 3: Deleting team members for team %d", team_id)
    db.query(TeamMemberModel).filter(TeamMemberModel.team_id == team_id).delete(synchronize_session=False)
    logger.info("Team members deleted")

    # 4. Удаляем саму команду
    logger.info("Step 4: Deleting team %d", team_id)
    team_repo.delete(team_id)
    logger.info("Team deleted, committing changes")
    db.commit()

    logger.info("✅ Team %d successfully deleted by user %d", team_id, current_user.id)
