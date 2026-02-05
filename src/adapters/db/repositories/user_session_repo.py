from sqlalchemy.orm import Session
from sqlalchemy import select
from src.adapters.db.models.user_session import UserSessionModel
from src.adapters.db.repositories.base_repository import BaseRepository


class UserSessionRepository(BaseRepository[UserSessionModel]):
    def __init__(self, db: Session):
        super().__init__(db, UserSessionModel)

    def get_by_name(self, name: str) -> UserSessionModel | None:
        stmt = select(UserSessionModel).where(UserSessionModel.name == name)
        return self.db.scalar(stmt)
    
    def get_or_create(self, **kwargs) -> tuple[UserSessionModel, bool]:
        instance = self.get_by_id(kwargs.get('id'))
        if instance:
            return instance, False
        return self.create(**kwargs), True
