from datetime import datetime
from sqlalchemy import TIMESTAMP, String, Boolean, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column

from src.data.enums.role import Role
from src.adapters.db.base import Base


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    username: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    github_username: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )

    github_token_encrypted: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    role: Mapped[Role] = mapped_column(
        SAEnum(Role, name="role", create_type=False),
        nullable=False,
        default=Role.NONE,
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

    last_login: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    def __repr__(self):
        return f"<User {self.username}>"