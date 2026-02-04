from datetime import datetime
from sqlalchemy import (
    TIMESTAMP,
    ForeignKey,
    String,
    func
)
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.db.base import Base


class TeamMemberModel(Base):
    __tablename__ = "team_members"

    id: Mapped[int] = mapped_column(primary_key=True)

    team_id: Mapped[int] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
    )  # FK

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )  # FK

    dev_role: Mapped[str | None] = mapped_column(String(128), nullable=False)
    
    joined_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

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