from datetime import datetime
from data.enums.vcs import VCS
from sqlalchemy import String, Text, TIMESTAMP, func, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.db.base import Base


class RepositoryModel(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(primary_key=True)

    vcs_provider: Mapped[VCS] = mapped_column(
        SAEnum(VCS, name="vcs_enum"),
        nullable=False,
        default=VCS.GITHUB,
    )

    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    owner: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(
        String(128), nullable=False
    )  # GitHub limit: Name cannot be more than 100 characters

    url: Mapped[str] = mapped_column(Text, nullable=False)

    default_branch: Mapped[str | None] = mapped_column(String(128), nullable=True)

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
