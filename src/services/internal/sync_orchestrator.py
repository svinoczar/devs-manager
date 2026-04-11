from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable
import threading

from src.adapters.db.base import SessionLocal
from src.services.internal.process import process_single_commit, get_existing_commit_shas
from src.services.external.github_stats_manual import get_commits_paginated, get_contributors, get_commits_count
from src.adapters.db.repositories.contributor_repo import ContributorRepository
from src.adapters.db.repositories.sync_session_repo import SyncSessionRepository
from src.util.logger import logger


class SyncCancelledException(Exception):
    """Исключение выбрасывается когда синхронизация отменена пользователем"""
    pass


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
        sprint_days: int = 14,
        session_id: int | None = None,
        sprint_only: bool = True
    ) -> dict:
        """
        Синхронизирует репозиторий с приоритетной потоковой загрузкой.

        Процесс:
        1. Загружаем коммиты постранично
        2. Каждую страницу сразу разделяем на sprint/archive
        3. Sprint коммиты обрабатываем немедленно
        4. Когда вышли за пределы sprint_cutoff - отмечаем sprint_commits_done
        5. Если sprint_only=True - останавливаемся, иначе продолжаем обработку archive

        Args:
            owner: Владелец репозитория
            repo: Название репозитория
            token: GitHub токен
            settings: JSON строка с настройками анализа
            db_repo_id: ID репозитория в БД
            sprint_days: Количество дней для спринта (приоритетная загрузка)
            sprint_only: Если True, загружаем только sprint коммиты (по умолчанию)

        Returns:
            dict с результатами синхронизации
        """
        self.progress.start_time = datetime.now(timezone.utc)
        logger.info("[sync_orchestrator:sync_repository] Starting streaming sync for %s/%s (session_id=%s, sprint_days=%d)",
                   owner, repo, session_id, sprint_days)

        sprint_cutoff = datetime.now(timezone.utc) - timedelta(days=sprint_days)
        logger.info("[sync_orchestrator:sync_repository] Sprint cutoff date: %s", sprint_cutoff.isoformat())

        # Подготовка: контрибьюторы
        logger.info("[sync_orchestrator:sync_repository] Phase: preparing contributors")
        self.progress.current_phase = "preparing"
        self._notify_progress()
        db_contributors = self._prepare_contributors(owner, repo, token, db_repo_id)

        # Получаем существующие SHA один раз
        logger.info("[sync_orchestrator:sync_repository] Getting existing commit SHAs from database")
        with SessionLocal() as session:
            existing_shas = get_existing_commit_shas(session, db_repo_id)
        logger.info("[sync_orchestrator:sync_repository] Found %d existing commits in DB", len(existing_shas))

        # Предварительный подсчёт общего количества коммитов за период спринта
        # Это позволит сразу показать правильный прогресс (X/Y коммитов)
        logger.info("[sync_orchestrator:sync_repository] Getting total commits count for sprint period...")
        try:
            total_commits_in_period = get_commits_count(
                owner, repo, token,
                since=sprint_cutoff  # Только за период спринта
            )
            logger.info("[sync_orchestrator:sync_repository] Total commits in sprint period: %d", total_commits_in_period)
        except Exception as e:
            logger.warning("[sync_orchestrator:sync_repository] Failed to get commits count: %s, will calculate during processing", e)
            total_commits_in_period = 0

        # Устанавливаем начальное значение total_commits для прогресса
        self.progress.total_commits = total_commits_in_period
        self._notify_progress()

        # Счетчики для отслеживания прогресса синхронизации
        # sprint_count - количество коммитов в sprint зоне (последние N дней)
        # archive_count - количество коммитов в archive зоне (старше N дней)
        # sprint_new/archive_new - количество НОВЫХ коммитов в каждой зоне
        # total_commits_seen - общее количество просмотренных коммитов (включая существующие)
        # total_new_commits - только новые коммиты для показа прогресса
        # in_sprint_zone - флаг того, что мы еще в зоне свежих коммитов
        sprint_count = 0
        archive_count = 0
        sprint_new = 0
        archive_new = 0
        total_commits_seen = 0
        total_new_commits = 0
        in_sprint_zone = True

        # Фаза 1: Потоковая обработка с приоритетом спринта
        logger.info("[sync_orchestrator:sync_repository] Phase: processing_sprint (streaming mode)")
        self.progress.current_phase = "processing_sprint"
        self._notify_progress()

        try:
            for page_data in get_commits_paginated(owner, repo, token):
                # Проверяем, не отменена ли синхронизация
                self._check_cancellation(session_id)

                commits_on_page = page_data["commits"]
                page_num = page_data["page"]

                logger.info(
                    "[sync_orchestrator:sync_repository] Processing page %d: %d commits (total seen: %d, new: %d)",
                    page_num, len(commits_on_page), total_commits_seen, total_new_commits
                )

                # Разделяем страницу на sprint (приоритет) и archive (фон)
                # Sprint - последние N дней, нужны для быстрого показа дашборда
                # Archive - все остальные, обрабатываются в фоне
                sprint_batch = []
                archive_batch = []

                for commit_json in commits_on_page:
                    total_commits_seen += 1

                    # Пропускаем уже существующие коммиты (дедупликация по SHA)
                    if commit_json["sha"] in existing_shas:
                        continue

                    # Это новый коммит - увеличиваем счётчик для показа правильного прогресса
                    total_new_commits += 1

                    # Определяем категорию по дате
                    try:
                        commit_date_str = commit_json.get("commit", {}).get("author", {}).get("date")
                        if commit_date_str:
                            commit_date = datetime.fromisoformat(commit_date_str.replace("Z", "+00:00"))
                            is_sprint = commit_date >= sprint_cutoff
                        else:
                            is_sprint = False
                    except Exception as e:
                        logger.warning("Failed to parse date for %s: %s", commit_json.get("sha", "?")[:7], e)
                        is_sprint = False

                    if is_sprint:
                        sprint_batch.append(commit_json)
                        sprint_count += 1
                    else:
                        archive_batch.append(commit_json)
                        archive_count += 1

                        # Если дошли до архивных коммитов - отмечаем sprint как завершенный
                        if in_sprint_zone:
                            in_sprint_zone = False
                            self.progress.sprint_commits_done = True
                            self.progress.current_phase = "processing_archive"
                            logger.info("[sync_orchestrator:sync_repository] ✓ Sprint zone ended at page %d, switching to archive processing (sprint: %d commits, %d new)",
                                      page_num, sprint_count, sprint_new)
                            self._notify_progress()

                # Обрабатываем sprint батч сразу
                if sprint_batch:
                    logger.info("[sync_orchestrator:sync_repository] Processing %d sprint commits from page %d (workers=%d)",
                              len(sprint_batch), page_num, self.max_workers)
                    result = self._process_commits_parallel(
                        sprint_batch, owner, repo, token, settings, db_repo_id, db_contributors
                    )
                    sprint_new += result["new"]
                    logger.debug("[sync_orchestrator:sync_repository] Sprint batch processed: %d new, %d skipped",
                               result["new"], result["skipped"])

                # Обрабатываем archive батч (только если не sprint_only)
                if archive_batch and not in_sprint_zone:
                    if sprint_only:
                        # Останавливаем пагинацию - sprint завершен, archive не нужен
                        logger.info("[sync_orchestrator:sync_repository] Sprint completed, stopping pagination (sprint_only=True). Archive commits available: %d on current page",
                                  len(archive_batch))
                        break
                    else:
                        logger.info("[sync_orchestrator:sync_repository] Processing %d archive commits from page %d (workers=%d)",
                                  len(archive_batch), page_num, self.max_workers)
                        result = self._process_commits_parallel(
                            archive_batch, owner, repo, token, settings, db_repo_id, db_contributors
                        )
                        archive_new += result["new"]
                        logger.debug("[sync_orchestrator:sync_repository] Archive batch processed: %d new, %d skipped",
                                   result["new"], result["skipped"])

        except SyncCancelledException as e:
            logger.info("[sync_orchestrator:sync_repository] ✗ Sync was cancelled: %s", e)
            self.progress.current_phase = "cancelled"
            self.progress.errors.append("Синхронизация отменена пользователем")
            self._notify_progress()
            # Не поднимаем исключение дальше - это нормальное завершение
            return {
                "total_commits": total_commits_seen,
                "processed_commits": self.progress.processed_commits,
                "sprint_commits": sprint_count,
                "archive_commits": archive_count,
                "new_commits": sprint_new + archive_new,
                "errors": self.progress.errors,
                "cancelled": True,
            }
        except Exception as e:
            logger.error("[sync_orchestrator:sync_repository] ✗ Streaming sync failed: %s", e, exc_info=True)
            self.progress.errors.append(f"Sync error: {str(e)}")
            self._notify_progress()
            raise

        # Финализация
        if in_sprint_zone:
            # Если все коммиты были в sprint зоне
            logger.info("[sync_orchestrator:sync_repository] All commits were in sprint zone, marking sprint as done")
            self.progress.sprint_commits_done = True

        self.progress.current_phase = "complete"
        self._notify_progress()

        total_new = sprint_new + archive_new
        duration = (datetime.now(timezone.utc) - self.progress.start_time).total_seconds()
        logger.info(
            "[sync_orchestrator:sync_repository] ✓ Sync completed for %s/%s in %.2fs: %d total seen, %d sprint (%d new), %d archive (%d new)",
            owner, repo, duration, total_commits_seen, sprint_count, sprint_new, archive_count, archive_new
        )

        return {
            "total_commits": total_commits_seen,
            "processed_commits": self.progress.processed_commits,
            "sprint_commits": sprint_count,
            "archive_commits": archive_count,
            "new_commits": total_new,
            "errors": self.progress.errors,
        }


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

        logger.info("[sync_orchestrator:_prepare_contributors] Fetching contributors for %s/%s", owner, repo)

        contributors_json = get_contributors(owner, repo, token=token)
        dto_contributors = git_commit_authors_json_to_dto_list(contributors_json)
        logger.debug("[sync_orchestrator:_prepare_contributors] Received %d contributors from GitHub", len(dto_contributors))

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
                if created:
                    logger.debug("[sync_orchestrator:_prepare_contributors] Created new contributor: %s", c.login)

        logger.info("[sync_orchestrator:_prepare_contributors] ✓ Prepared %d contributors", len(db_contributors))
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
            logger.debug("[sync_orchestrator:_process_commits_parallel] Skipping %d existing commits", skipped_count)

        if not commits_to_process:
            logger.debug("[sync_orchestrator:_process_commits_parallel] No new commits to process")
            return {"new": 0, "skipped": skipped_count}

        logger.info("[sync_orchestrator:_process_commits_parallel] Starting parallel processing of %d commits with %d workers",
                   len(commits_to_process), self.max_workers)

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
                    logger.error("[sync_orchestrator:_process_commits_parallel] ✗ Failed to process commit %s: %s", sha[:7], e)
                    with self.lock:
                        self.progress.errors.append(f"Commit {sha[:7]}: {str(e)}")
                        self.progress.processed_commits += 1
                        self._notify_progress()

        logger.info("[sync_orchestrator:_process_commits_parallel] ✓ Parallel processing complete: %d new commits created",
                   new_count)
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

        sha = commit_json.get("sha", "unknown")
        logger.debug("[sync_orchestrator:_process_single_commit_wrapper] Processing commit %s", sha[:7])

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
                if result["created"]:
                    logger.debug("[sync_orchestrator:_process_single_commit_wrapper] ✓ Created commit %s", sha[:7])
                return result
            except Exception as e:
                logger.error("[sync_orchestrator:_process_single_commit_wrapper] ✗ Error processing commit %s: %s",
                           sha[:7], e)
                raise

    def _notify_progress(self):
        """Уведомляет callback о прогрессе"""
        if self.progress_callback:
            try:
                self.progress_callback(self.progress)
            except Exception as e:
                logger.warning("Progress callback failed: %s", e)

    def _check_cancellation(self, session_id: int | None) -> None:
        """
        Проверяет, не была ли отменена синхронизация.
        Выбрасывает SyncCancelledException если синхронизация отменена.
        """
        if not session_id:
            return

        try:
            with SessionLocal() as session:
                sync_repo = SyncSessionRepository(session)
                sync_session = sync_repo.get_by_id(session_id)

                if sync_session and sync_session.status.value == "cancelled":
                    logger.warning("[sync_orchestrator:_check_cancellation] ⚠ Sync session %d was cancelled, aborting", session_id)
                    raise SyncCancelledException(f"Sync session {session_id} was cancelled")
        except SyncCancelledException:
            raise
        except Exception as e:
            logger.error("[sync_orchestrator:_check_cancellation] Failed to check cancellation status: %s", e)
            # Не прерываем синхронизацию если не можем проверить статус
