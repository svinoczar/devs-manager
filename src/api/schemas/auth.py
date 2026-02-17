from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional


# User Registration
class UserCreate(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)
    full_name: Optional[str] = None
    github_username: Optional[str] = None
    github_token: Optional[str] = None


# User Login
class UserLogin(BaseModel):
    username: str
    password: str


# Token Response
class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: Optional[int] = None
    username: Optional[str] = None


class RefreshTokenRequest(BaseModel):
    refresh_token: str


# User Response
class UserResponse(BaseModel):
    id: int
    email: str
    username: str
    full_name: Optional[str]
    github_username: Optional[str]
    is_active: bool
    is_verified: bool
    created_at: datetime
    last_login: Optional[datetime]

    class Config:
        from_attributes = True


# GitHub Token
class GitHubTokenUpdate(BaseModel):
    github_token: str
    github_username: Optional[str] = None


# User Update
class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    github_username: Optional[str] = None


# Password Change
class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=8)


class EmailVerificationRequest(BaseModel):
    email: EmailStr


class EmailVerificationCode(BaseModel):
    email: EmailStr
    code: str


class VCSSetup(BaseModel):
    vcs_provider: str  # 'github', 'gitlab', 'bitbucket', 'svn'
    access_token: str
    username: str | None = None
