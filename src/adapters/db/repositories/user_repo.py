from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, or_

from src.adapters.db.models.user import UserModel
from src.adapters.db.repositories.base_repository import BaseRepository
from src.core.security import get_password_hash, encrypt_github_token, decrypt_github_token



class UserRepository(BaseRepository[UserModel]):
    def __init__(self, db: Session):
        super().__init__(db, UserModel)

    def get_by_username(self, username: str) -> UserModel | None:
        stmt = select(UserModel).where(UserModel.username == username)
        return self.db.scalar(stmt)

    def get_or_create(self, **kwargs) -> tuple[UserModel, bool]:
        instance = self.get_by_id(kwargs.get("id"))
        if instance:
            return instance, False
        return self.create(**kwargs), True

    def create_user(
        self,
        email: str,
        username: str,
        password: str,
        full_name: Optional[str] = None,
        github_username: Optional[str] = None,
        github_token: Optional[str] = None,
    ) -> UserModel:
        """Create a new user"""
        hashed_password = get_password_hash(password)

        user = UserModel(
            email=email,
            username=username,
            hashed_password=hashed_password,
            full_name=full_name,
            github_username=github_username,
            github_token_encrypted=encrypt_github_token(github_token) if github_token else None,
        )
        
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user
    
    def get_user_by_id(self, user_id: int) -> Optional[UserModel]:
        """Get user by ID"""
        return self.db.query(UserModel).filter(UserModel.id == user_id).first()
    
    def get_user_by_username(self, username: str) -> Optional[UserModel]:
        """Get user by username"""
        return self.db.query(UserModel).filter(UserModel.username == username).first()
    
    def get_user_by_email(self, email: str) -> Optional[UserModel]:
        """Get user by email"""
        return self.db.query(UserModel).filter(UserModel.email == email).first()
    
    def get_user_by_email_or_username(self, identifier: str) -> Optional[UserModel]:
        """Get user by email or username"""
        return self.db.query(UserModel).filter(
            or_(UserModel.email == identifier, UserModel.username == identifier)
        ).first()
    
    def update_user(self, user: UserModel, **kwargs) -> UserModel:
        """Update user fields"""
        for key, value in kwargs.items():
            if hasattr(user, key) and value is not None:
                setattr(user, key, value)
        
        user.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(user)
        return user
    
    def update_password(self, user: UserModel, new_password: str) -> UserModel:
        """Update user password"""
        user.hashed_password = get_password_hash(new_password)
        user.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(user)
        return user
    
    def store_github_token(
        self,
        user: UserModel,
        github_token: str,
        github_username: Optional[str] = None
    ) -> UserModel:
        """Store encrypted GitHub token"""
        user.github_token_encrypted = encrypt_github_token(github_token)
        if github_username:
            user.github_username = github_username
        
        user.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(user)
        return user
    
    def get_github_token(self, user: UserModel) -> Optional[str]:
        """Get decrypted GitHub token"""
        if not user.github_token_encrypted:
            return None
        return decrypt_github_token(user.github_token_encrypted)
    
    def update_last_login(self, user: UserModel) -> UserModel:
        """Update last login timestamp"""
        user.last_login = datetime.utcnow()
        self.db.commit()
        self.db.refresh(user)
        return user
    
    def delete_user(self, user: UserModel) -> None:
        """Delete a user"""
        self.db.delete(user)
        self.db.commit()
    
    def deactivate_user(self, user: UserModel) -> UserModel:
        """Deactivate a user account"""
        user.is_active = False
        user.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(user)
        return user