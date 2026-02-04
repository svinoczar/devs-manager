from datetime import datetime
from sqlalchemy import (
    TIMESTAMP,
    String,
    ForeignKey,
    Enum as SAEnum,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from data.enums.vcs import VCS
from src.adapters.db.base import Base


class ProjectModel(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True
    )  # GitHub limit: Name cannot be more than 100 characters

    manager_id: Mapped[int] = mapped_column(ForeignKey("users.id"))  # FK

    vcs: Mapped[VCS] = mapped_column(
        SAEnum(VCS, name="vcs_enum"), nullable=False, default=VCS.GITHUB
    )

    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))  # FK

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
