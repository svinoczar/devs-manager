from sqlalchemy.orm import Session
from sqlalchemy import select
from src.adapters.db.models.organization_member import OrganizationMemberModel
from src.adapters.db.repositories.base_repository import BaseRepository


class OrganizationMemberRepository(BaseRepository[OrganizationMemberModel]):
    def __init__(self, db: Session):
        super().__init__(db, OrganizationMemberModel)

    def get_by_name(self, name: str) -> OrganizationMemberModel | None:
        stmt = select(OrganizationMemberModel).where(OrganizationMemberModel.name == name)
        return self.db.scalar(stmt)
    
    def get_or_create(self, **kwargs) -> tuple[OrganizationMemberModel, bool]:
        instance = self.get_by_id(kwargs.get('id'))
        if instance:
            return instance, False
        return self.create(**kwargs), True
