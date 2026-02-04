from datetime import datetime
from sqlalchemy import (
    TIMESTAMP,
    String,
    Text,
    Integer,
    ForeignKey,
    func
)
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.db.base import Base


class CommitFileModel(Base):
    __tablename__ = "commit_files"

    id: Mapped[int] = mapped_column(primary_key=True)

    commit_id: Mapped[int] = mapped_column(
        ForeignKey("commits.id"), nullable=False
    )  # FK

    file_path: Mapped[str] = mapped_column(Text, nullable=False)

    additions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deletions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    changes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    language: Mapped[str | None] = mapped_column(String(128), nullable=True)

    patch: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
