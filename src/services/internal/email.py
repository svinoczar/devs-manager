import random
import string
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from src.adapters.db.models.email_verification import EmailVerificationModel


class EmailService:
    def __init__(self, db: Session):
        self.db = db

    def generate_code(self) -> str:
        """Generate a 6-digit verification code"""
        return "".join(random.choices(string.digits, k=6))

    def send_verification_email(self, email: str) -> str:
        """
        Generate and 'send' verification code
        In real app, this would use SendGrid/AWS SES/etc
        For now, just return the code for testing
        """
        # Delete old codes for this email
        self.db.query(EmailVerificationModel).filter(
            EmailVerificationModel.email == email,
            EmailVerificationModel.verified == False,
        ).delete()

        # Generate new code
        code = self.generate_code()

        # Save to database
        verification = EmailVerificationModel(
            email=email, code=code, expires_at=datetime.utcnow() + timedelta(minutes=15)
        )

        self.db.add(verification)
        self.db.commit()

        # TODO: Send actual email here
        print(f"📧 Verification code for {email}: {code}")

        return code

    def verify_code(self, email: str, code: str) -> bool:
        """Verify the code is correct and not expired"""
        verification = (
            self.db.query(EmailVerificationModel)
            .filter(
                EmailVerificationModel.email == email,
                EmailVerificationModel.code == code,
                EmailVerificationModel.verified == False,
                EmailVerificationModel.expires_at > datetime.utcnow(),
            )
            .first()
        )

        if not verification:
            return False

        # Mark as verified
        verification.verified = True
        self.db.commit()

        return True
