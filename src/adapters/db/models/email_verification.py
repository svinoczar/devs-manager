from datetime import datetime, timedelta
from sqlalchemy import TIMESTAMP, String, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.db.base import Base


class EmailVerificationModel(Base):
    __tablename__ = "email_verification_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(6), nullable=False, index=True)
    
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    
    verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    def __repr__(self):
        return f"<EmailVerification {self.email} - {self.code}>"