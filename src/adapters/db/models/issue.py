from datetime import datetime
from sqlalchemy import Integer, String, Text, TIMESTAMP, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.db.base import Base


class IssueModel(Base):
    __tablename__ = "issues"

    id: Mapped[int] = mapped_column(primary_key=True)

    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id"), nullable=False
    )

    contributor_id: Mapped[int | None] = mapped_column(
        ForeignKey("contributors.id"), nullable=True
    )

    external_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)  # open/closed
    author_login: Mapped[str | None] = mapped_column(String(128), nullable=True)
    author_avatar: Mapped[str | None] = mapped_column(Text, nullable=True)

    issue_created_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    issue_closed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
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
