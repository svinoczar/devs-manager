from sqlalchemy.orm import Session
from sqlalchemy import select
from src.adapters.db.models.user import UserModel
from src.adapters.db.repositories.base_repository import BaseRepository


class UserRepository(BaseRepository[UserModel]):
    def __init__(self, db: Session):
        super().__init__(db, UserModel)

    def get_by_name(self, name: str) -> UserModel | None:
        stmt = select(UserModel).where(UserModel.name == name)
        return self.db.scalar(stmt)

    def get_or_create(self, **kwargs) -> tuple[UserModel, bool]:
        instance = self.get_by_id(kwargs.get("id"))
        if instance:
            return instance, False
        return self.create(**kwargs), True
