from src.data.enums.vcs import VCS
from sqlalchemy import String, Text, TIMESTAMP, func, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from src.adapters.db.base import Base


class ContributorModel(Base):
    __tablename__ = "contributors"

    id: Mapped[int] = mapped_column(primary_key=True)

    vcs_provider: Mapped[VCS] = mapped_column(
        SAEnum(VCS, name="vcs_enum"),
        nullable=False,
        default=VCS.GITHUB,
    )

    external_id: Mapped[str] = mapped_column(String(128), nullable=False)

    login: Mapped[str | None] = mapped_column(String(128), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    profile_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
