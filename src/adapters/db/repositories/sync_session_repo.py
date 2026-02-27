from sqlalchemy.orm import Session
from sqlalchemy import select
from src.adapters.db.models.sync_session import SyncSessionModel, SyncStatus
from src.adapters.db.repositories.base_repository import BaseRepository


class SyncSessionRepository(BaseRepository[SyncSessionModel]):
    """Репозиторий для работы с сессиями синхронизации"""

    def __init__(self, db: Session):
        super().__init__(db, SyncSessionModel)

    def create_session(
        self,
        team_id: int,
        repository_id: int
    ) -> SyncSessionModel:
        """
        Создает новую сессию синхронизации.

        Args:
            team_id: ID команды
            repository_id: ID репозитория

        Returns:
            Созданная сессия синхронизации
        """
        return self.create(
            team_id=team_id,
            repository_id=repository_id,
            status=SyncStatus.queued
        )

    def update_progress(
        self,
        session_id: int,
        total_commits: int | None = None,
        processed_commits: int | None = None,
        new_commits: int | None = None,
        current_phase: str | None = None,
        sprint_commits_done: bool | None = None
    ) -> SyncSessionModel | None:
        """
        Обновляет прогресс синхронизации.

        Args:
            session_id: ID сессии
            total_commits: Общее количество коммитов
            processed_commits: Количество обработанных коммитов
            new_commits: Количество новых коммитов
            current_phase: Текущая фаза синхронизации
            sprint_commits_done: Завершена ли обработка спринта

        Returns:
            Обновленная сессия или None если не найдена
        """
        session = self.get_by_id(session_id)
        if not session:
            return None

        if total_commits is not None:
            session.total_commits = total_commits
        if processed_commits is not None:
            session.processed_commits = processed_commits
        if new_commits is not None:
            session.new_commits = new_commits
        if current_phase is not None:
            session.current_phase = current_phase
        if sprint_commits_done is not None:
            session.sprint_commits_done = sprint_commits_done

        self.db.commit()
        self.db.refresh(session)
        return session

    def get_active_by_team(self, team_id: int) -> list[SyncSessionModel]:
        """
        Получает все активные сессии синхронизации для команды.

        Args:
            team_id: ID команды

        Returns:
            Список активных сессий (queued или running)
        """
        stmt = select(SyncSessionModel).where(
            SyncSessionModel.team_id == team_id,
            SyncSessionModel.status.in_([SyncStatus.queued, SyncStatus.running])
        )
        return list(self.db.scalars(stmt).all())
