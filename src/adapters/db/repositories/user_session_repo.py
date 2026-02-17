from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import select, update
from src.adapters.db.models.user_session import UserSessionModel
from src.adapters.db.repositories.base_repository import BaseRepository


class UserSessionRepository(BaseRepository[UserSessionModel]):
    def __init__(self, db: Session):
        super().__init__(db, UserSessionModel)

    def create_session(
        self,
        user_id: int,
        token_hash: str,
        refresh_token_hash: str,
        expires_at: datetime,
    ) -> UserSessionModel:
        return self.create(
            user_id=user_id,
            token_hash=token_hash,
            refresh_token_hash=refresh_token_hash,
            expires_at=expires_at,
            is_active=True,
        )

    def get_active_session_by_token_hash(self, token_hash: str) -> UserSessionModel | None:
        stmt = (
            select(UserSessionModel)
            .where(UserSessionModel.token_hash == token_hash)
            .where(UserSessionModel.is_active == True)
        )
        return self.db.scalar(stmt)

    def get_active_session_by_refresh_hash(self, refresh_hash: str) -> UserSessionModel | None:
        stmt = (
            select(UserSessionModel)
            .where(UserSessionModel.refresh_token_hash == refresh_hash)
            .where(UserSessionModel.is_active == True)
        )
        return self.db.scalar(stmt)

    def invalidate_session(self, session_id: int) -> None:
        stmt = (
            update(UserSessionModel)
            .where(UserSessionModel.id == session_id)
            .values(is_active=False)
        )
        self.db.execute(stmt)
        self.db.commit()

    def invalidate_all_user_sessions(self, user_id: int) -> None:
        stmt = (
            update(UserSessionModel)
            .where(UserSessionModel.user_id == user_id)
            .where(UserSessionModel.is_active == True)
            .values(is_active=False)
        )
        self.db.execute(stmt)
        self.db.commit()

    def update_token_hash(self, session_id: int, new_token_hash: str) -> None:
        stmt = (
            update(UserSessionModel)
            .where(UserSessionModel.id == session_id)
            .values(token_hash=new_token_hash)
        )
        self.db.execute(stmt)
        self.db.commit()
