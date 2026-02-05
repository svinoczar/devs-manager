from datetime import datetime
from sqlalchemy import (
    TIMESTAMP,
    String,
    Enum as SAEnum,
    func
)
from sqlalchemy.orm import Mapped, mapped_column

from src.data.enums.role import Role
from src.adapters.db.base import Base


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    email: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    role: Mapped[Role] = mapped_column(
        SAEnum(Role, name="role"),
        nullable=False,
        default=Role.MEMBER,
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

    