from datetime import datetime
from sqlalchemy import (
    TIMESTAMP,
    ForeignKey,
    String,
    func,
    Text
)
from sqlalchemy.orm import Mapped, mapped_column

from data.enums.vcs import VCS
from src.adapters.db.base import Base


class UserSessionModel(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )  # FK

    token_hash: Mapped[str | None] = mapped_column(Text, nullable=False)
    
    refresh_token_hash: Mapped[str | None] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )