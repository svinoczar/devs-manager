from datetime import datetime
from sqlalchemy import (
    TIMESTAMP,
    Text,
    ForeignKey,
    Enum as SAEnum,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from data.enums.vcs import VCS
from src.adapters.db.base import Base


class TeamModel(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(Text, nullable=False)

    manager_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )  # FK

    vcs: Mapped[VCS] = mapped_column(
        SAEnum(VCS, name="vcs_enum"),
        nullable=False,
        default=VCS.GITHUB,
    )

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))  # FK

    analysis_config: Mapped[str | None] = mapped_column(Text, nullable=False)

    workflow_config: Mapped[str | None] = mapped_column(Text, nullable=False)

    metrics_config: Mapped[str | None] = mapped_column(Text, nullable=False)

    global_config: Mapped[str | None] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # relationships (опционально, но полезно)
    manager = relationship("UserModel", lazy="joined")
    projects = relationship("ProjectModel")
