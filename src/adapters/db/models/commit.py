from datetime import datetime
from sqlalchemy import (
    Boolean,
    Integer,
    String,
    Text,
    TIMESTAMP,
    Float,
    ForeignKey,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.db.base import Base


class CommitModel(Base):
    __tablename__ = "commits"

    id: Mapped[int] = mapped_column(primary_key=True)

    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id"), nullable=False
    )

    contributor_id: Mapped[int | None] = mapped_column(
        ForeignKey("contributors.id"), nullable=True
    )

    sha: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    authored_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    committed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    author_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    author_email: Mapped[str | None] = mapped_column(String(128), nullable=True)

    additions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deletions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    changes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    commit_type: Mapped[str | None] = mapped_column(String(64), nullable=True)

    is_conventional: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=False
    )
    conventional_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    conventional_scope: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_breaking_change: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=False
    )

    is_merge_commit: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=False
    )
    is_pr_commit: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=False
    )

    parents_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    files_changed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_revert_commit: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=False
    )

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
