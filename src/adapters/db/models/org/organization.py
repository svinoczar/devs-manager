from datetime import datetime
from sqlalchemy import (
    TIMESTAMP,
    String,
    ForeignKey,
    Enum as SAEnum,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from data.enums.vcs import VCS
from src.adapters.db.base import Base


class OrganizationModel(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True
    )  # GitHub limit: Name cannot be more than 100 characters

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    ) # FK

    main_vcs: Mapped[VCS] = mapped_column(
        SAEnum(VCS, name="vcs_enum"),
        nullable=False,
        default=VCS.GITHUB,
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

    # relationships 
    # owner = relationship("UserModel", back_populates="organizations") 