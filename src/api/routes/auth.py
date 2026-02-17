from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from src.api.schemas.auth import (
    UserCreate,
    UserLogin,
    UserResponse,
    Token,
    GitHubTokenUpdate,
    UserUpdate,
    PasswordChange,
    EmailVerificationRequest,
    EmailVerificationCode,
    VCSSetup,
    RefreshTokenRequest,
)
from src.api.dependencies import get_db, get_current_user, get_access_token
from src.services.auth_service import AuthService
from src.adapters.db.models.user import UserModel
from src.adapters.db.repositories.user_repo import UserRepository
from src.core.security import verify_password, ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS
from src.services.internal.email import EmailService


# Cookie settings
COOKIE_SECURE = False  # Set True in production (HTTPS)
COOKIE_HTTPONLY = True
COOKIE_SAMESITE = "lax"


router = APIRouter(prefix="/auth", tags=["authentication"])


# region models


class AvailabilityCheck(BaseModel):
    email: EmailStr | None = None
    username: str | None = None


# endregion


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """
    Register a new user

    - **email**: Valid email address
    - **username**: Unique username (3-50 characters)
    - **password**: Password (minimum 8 characters)
    - **full_name**: Optional full name
    - **github_username**: Optional GitHub username
    """
    auth_service = AuthService(db)
    return auth_service.register_user(user_data)


@router.post("/login", response_model=Token)
def login(login_data: UserLogin, response: Response, db: Session = Depends(get_db)):
    """
    Login and receive JWT tokens

    - **username**: Your username
    - **password**: Your password

    Returns JWT tokens and sets HttpOnly cookies
    """
    auth_service = AuthService(db)
    tokens = auth_service.login_user(login_data)

    # Set cookies
    response.set_cookie(
        key="access_token",
        value=tokens.access_token,
        httponly=COOKIE_HTTPONLY,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    response.set_cookie(
        key="refresh_token",
        value=tokens.refresh_token,
        httponly=COOKIE_HTTPONLY,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )

    return tokens


@router.post("/refresh", response_model=Token)
def refresh_token(
    request: Request,
    response: Response,
    body: RefreshTokenRequest | None = None,
    db: Session = Depends(get_db),
):
    """
    Refresh access token using refresh token

    Accepts refresh token from:
    - Request body (refresh_token field)
    - Cookie (refresh_token)
    """
    # Get refresh token from body or cookie
    refresh_tok = None
    if body and body.refresh_token:
        refresh_tok = body.refresh_token
    else:
        refresh_tok = request.cookies.get("refresh_token")

    if not refresh_tok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token required",
        )

    auth_service = AuthService(db)
    tokens = auth_service.refresh_tokens(refresh_tok)

    # Update access token cookie
    response.set_cookie(
        key="access_token",
        value=tokens.access_token,
        httponly=COOKIE_HTTPONLY,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )

    return tokens


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    access_token: str = Depends(get_access_token),
):
    """
    Logout current session

    Invalidates the session and clears cookies
    """
    auth_service = AuthService(db)
    auth_service.logout(access_token)

    # Clear cookies
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")

    return {"message": "Logged out successfully"}


@router.post("/logout-all")
def logout_all(
    response: Response,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Logout from all sessions

    Invalidates all user sessions and clears cookies
    """
    auth_service = AuthService(db)
    auth_service.logout_all(current_user.id)

    # Clear cookies
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")

    return {"message": "Logged out from all sessions"}


@router.post("/check-availability")
def check_availability(data: AvailabilityCheck, db: Session = Depends(get_db)):
    user_repo = UserRepository(db)

    result = {
        "email_available": True,
        "username_available": True,
    }

    if data.email and user_repo.get_user_by_email(data.email):
        result["email_available"] = False

    if data.username and user_repo.get_user_by_username(data.username):
        result["username_available"] = False

    return result


@router.post("/send-verification")
def send_verification_code(
    request: EmailVerificationRequest, db: Session = Depends(get_db)
):
    """
    Send verification code to email
    Returns the code in response (for testing only - remove in production!)
    """
    email_service = EmailService(db)
    code = email_service.send_verification_email(request.email)

    # In production, don't return the code!
    return {
        "message": "Verification code sent",
        "code": code,  # Remove this in production
    }


@router.post("/verify-email")
def verify_email_code(request: EmailVerificationCode, db: Session = Depends(get_db)):
    """
    Verify the email code
    """
    email_service = EmailService(db)

    if not email_service.verify_code(request.email, request.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification code",
        )

    return {"message": "Email verified successfully"}


@router.post("/setup-vcs")
def setup_vcs(vcs_data: VCSSetup, db: Session = Depends(get_db)):
    """
    Save VCS configuration (temporary storage before full registration)
    In real app, this would be stored in session or cache
    """
    # TODO: Validate token with VCS provider API

    return {"message": "VCS configured successfully", "provider": vcs_data.vcs_provider}


@router.get("/me", response_model=UserResponse)
def get_current_user_info(current_user: UserModel = Depends(get_current_user)):
    """
    Get current authenticated user information

    Requires: Authorization header with Bearer token
    """
    return UserResponse.from_orm(current_user)


@router.put("/me", response_model=UserResponse)
def update_current_user(
    user_update: UserUpdate,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update current user information

    - **email**: New email (optional)
    - **full_name**: New full name (optional)
    - **github_username**: New GitHub username (optional)
    """
    user_repo = UserRepository(db)

    update_data = user_update.dict(exclude_unset=True)

    # Check if email is being changed and is already taken
    if "email" in update_data:
        existing = user_repo.get_user_by_email(update_data["email"])
        if existing and existing.id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

    updated_user = user_repo.update_user(current_user, **update_data)
    return UserResponse.from_orm(updated_user)


@router.post("/change-password")
def change_password(
    password_change: PasswordChange,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Change user password

    - **old_password**: Current password
    - **new_password**: New password (minimum 8 characters)
    """
    # Verify old password
    if not verify_password(password_change.old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect current password"
        )

    # Update password
    user_repo = UserRepository(db)
    user_repo.update_password(current_user, password_change.new_password)

    return {"message": "Password updated successfully"}


@router.post("/github-token")
def connect_github(
    token_data: GitHubTokenUpdate,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Store encrypted GitHub personal access token

    - **github_token**: Your GitHub personal access token
    - **github_username**: Optional GitHub username

    The token is encrypted before storage for security
    """
    auth_service = AuthService(db)
    auth_service.update_github_token(
        user_id=current_user.id,
        github_token=token_data.github_token,
        github_username=token_data.github_username,
    )
    return {"message": "GitHub token stored successfully"}


@router.delete("/github-token")
def disconnect_github(
    current_user: UserModel = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Remove stored GitHub token
    """
    user_repo = UserRepository(db)
    user_repo.update_user(current_user, github_token_encrypted=None)
    return {"message": "GitHub token removed successfully"}


@router.delete("/me")
def delete_account(
    current_user: UserModel = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Delete current user account (soft delete - deactivate)
    """
    user_repo = UserRepository(db)
    user_repo.deactivate_user(current_user)
    return {"message": "Account deactivated successfully"}
