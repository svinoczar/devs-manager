from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional

from src.adapters.db.base import SessionLocal
from src.core.security import decode_access_token, hash_token
from src.adapters.db.repositories.user_repo import UserRepository
from src.adapters.db.repositories.user_session_repo import UserSessionRepository
from src.adapters.db.models.user import UserModel


# HTTP Bearer token scheme (auto_error=False to allow cookie fallback)
security = HTTPBearer(auto_error=False)


def get_db():
    """Database session dependency"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_access_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    """
    Extract access token from Bearer header or cookie

    Priority: Bearer header > Cookie
    """
    # Try Bearer header first
    if credentials:
        return credentials.credentials

    # Fallback to cookie
    token = request.cookies.get("access_token")
    if token:
        return token

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> UserModel:
    """
    Dependency to get the current authenticated user from JWT token

    Supports both Bearer header and cookie authentication.
    Validates session in database.

    Usage in routes:
        @app.get("/me")
        def get_me(current_user: UserModel = Depends(get_current_user)):
            return current_user
    """
    # Get token from header or cookie
    token = None
    if credentials:
        token = credentials.credentials
    else:
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Decode token
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check token type (must be access, not refresh)
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate session in database
    session_repo = UserSessionRepository(db)
    token_hash = hash_token(token)
    session = session_repo.get_active_session_by_token_hash(token_hash)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalidated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Extract user ID
    user_id: str = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Get user from database
    user_repo = UserRepository(db)
    user = user_repo.get_user_by_id(int(user_id))

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    return user


def get_current_active_user(
    current_user: UserModel = Depends(get_current_user),
) -> UserModel:
    """
    Dependency to get current active user (already checked in get_current_user)
    This is a convenience wrapper for clarity
    """
    return current_user


def get_github_token(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> str:
    """
    Dependency to get the current user's GitHub token

    Usage in routes:
        @app.get("/repos")
        def get_repos(github_token: str = Depends(get_github_token)):
            # Use github_token to call GitHub API
    """
    user_repo = UserRepository(db)
    token = user_repo.get_github_token(current_user)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GitHub token not found. Please connect your GitHub account first.",
        )

    return token


def optional_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[UserModel]:
    """
    Dependency to optionally get current user (doesn't raise error if no token)

    Usage for endpoints that work both with and without authentication:
        @app.get("/public")
        def public_endpoint(user: Optional[UserModel] = Depends(optional_user)):
            if user:
                return {"message": f"Hello {user.username}!"}
            return {"message": "Hello anonymous!"}
    """
    # Check if there's a token (header or cookie)
    has_token = credentials or request.cookies.get("access_token")
    if not has_token:
        return None

    try:
        return get_current_user(request, credentials, db)
    except HTTPException:
        return None