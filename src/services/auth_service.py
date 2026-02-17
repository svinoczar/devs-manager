from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from typing import Optional

from src.adapters.db.repositories.user_repo import UserRepository
from src.adapters.db.repositories.user_session_repo import UserSessionRepository
from src.core.security import (
    verify_password,
    create_access_token,
    create_refresh_token,
    hash_token,
    decode_access_token,
    REFRESH_TOKEN_EXPIRE_DAYS,
)
from src.api.schemas.auth import UserCreate, UserLogin, Token, UserResponse


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.user_repo = UserRepository(db)
        self.session_repo = UserSessionRepository(db)
    
    def register_user(self, user_data: UserCreate) -> UserResponse:
        """Register a new user"""
        # Check if email already exists
        existing_user = self.user_repo.get_user_by_email(user_data.email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        
        # Check if username already exists
        existing_user = self.user_repo.get_user_by_username(user_data.username)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken"
            )
        
        # Create user
        user = self.user_repo.create_user(
            email=user_data.email,
            username=user_data.username,
            password=user_data.password,
            full_name=user_data.full_name,
            github_username=user_data.github_username,
            github_token=user_data.github_token,
        )
        
        return UserResponse.from_orm(user)
    
    def login_user(self, login_data: UserLogin) -> Token:
        """Authenticate user and return JWT tokens"""
        # Find user by username
        user = self.user_repo.get_user_by_username(login_data.username)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Verify password
        if not verify_password(login_data.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Check if user is active
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive"
            )

        # Update last login
        self.user_repo.update_last_login(user)

        # Create tokens
        token_data = {"sub": str(user.id), "username": user.username}
        access_token = create_access_token(data=token_data)
        refresh_token = create_refresh_token(data=token_data)

        # Create session in DB
        expires_at = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        self.session_repo.create_session(
            user_id=user.id,
            token_hash=hash_token(access_token),
            refresh_token_hash=hash_token(refresh_token),
            expires_at=expires_at,
        )

        return Token(access_token=access_token, refresh_token=refresh_token)

    def refresh_tokens(self, refresh_token: str) -> Token:
        """Refresh access token using refresh token"""
        # Decode refresh token
        payload = decode_access_token(refresh_token)
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )

        # Check token type
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )

        # Find session by refresh token hash
        refresh_hash = hash_token(refresh_token)
        session = self.session_repo.get_active_session_by_refresh_hash(refresh_hash)

        if not session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session not found or expired",
            )

        # Check if session expired
        if session.expires_at < datetime.utcnow():
            self.session_repo.invalidate_session(session.id)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired",
            )

        # Get user
        user = self.user_repo.get_user_by_id(session.user_id)
        if not user or not user.is_active:
            self.session_repo.invalidate_session(session.id)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive",
            )

        # Create new access token
        token_data = {"sub": str(user.id), "username": user.username}
        new_access_token = create_access_token(data=token_data)

        # Update token hash in session
        self.session_repo.update_token_hash(session.id, hash_token(new_access_token))

        # Return same refresh token with new access token
        return Token(access_token=new_access_token, refresh_token=refresh_token)

    def logout(self, access_token: str) -> None:
        """Invalidate current session"""
        token_hash = hash_token(access_token)
        session = self.session_repo.get_active_session_by_token_hash(token_hash)

        if session:
            self.session_repo.invalidate_session(session.id)

    def logout_all(self, user_id: int) -> None:
        """Invalidate all user sessions"""
        self.session_repo.invalidate_all_user_sessions(user_id)

    def validate_session(self, access_token: str) -> bool:
        """Check if session is valid in DB"""
        token_hash = hash_token(access_token)
        session = self.session_repo.get_active_session_by_token_hash(token_hash)

        if not session:
            return False

        if session.expires_at < datetime.utcnow():
            self.session_repo.invalidate_session(session.id)
            return False

        return True
    
    def get_current_user_id(self, token_data: dict) -> int:
        """Extract user ID from token data"""
        user_id = token_data.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return int(user_id)
    
    def get_user_by_id(self, user_id: int) -> UserResponse:
        """Get user by ID"""
        user = self.user_repo.get_user_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        return UserResponse.from_orm(user)
    
    def update_github_token(
        self,
        user_id: int,
        github_token: str,
        github_username: Optional[str] = None
    ) -> UserResponse:
        """Update user's GitHub token"""
        user = self.user_repo.get_user_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        user = self.user_repo.store_github_token(
            user=user,
            github_token=github_token,
            github_username=github_username
        )
        
        return UserResponse.from_orm(user)
    
    def get_github_token(self, user_id: int) -> str:
        """Get decrypted GitHub token for user"""
        user = self.user_repo.get_user_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        token = self.user_repo.get_github_token(user)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="GitHub token not found. Please connect your GitHub account."
            )
        
        return token