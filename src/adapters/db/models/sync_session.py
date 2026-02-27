from datetime import datetime
from sqlalchemy import Integer, String, Boolean, TIMESTAMP, JSON, ForeignKey, func, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
import enum

from src.adapters.db.base import Base


class SyncStatus(enum.Enum):
    """Статусы синхронизации"""
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class SyncSessionModel(Base):
    """Сессия синхронизации репозитория"""
    __tablename__ = "sync_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"), nullable=False)
    repository_id: Mapped[int] = mapped_column(Integer, ForeignKey("repositories.id"), nullable=False)

    status: Mapped[SyncStatus] = mapped_column(
        SAEnum(SyncStatus, name="sync_status_enum"),
        nullable=False,
        default=SyncStatus.queued
    )

    # Прогресс
    total_commits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_commits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_commits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    current_phase: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sprint_commits_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Результаты
    errors: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"errors": ["msg1", "msg2"]}
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # Финальный результат

    # Timestamps
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
