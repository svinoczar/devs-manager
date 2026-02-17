from datetime import datetime
from sqlalchemy import TIMESTAMP, Text, func
from src.adapters.db.base import Base

from sqlalchemy.orm import Mapped, mapped_column


class FileExtensionModel(Base):
    __tablename__ = "file_extensions"

    id: Mapped[int] = mapped_column(primary_key=True)
    extension: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )