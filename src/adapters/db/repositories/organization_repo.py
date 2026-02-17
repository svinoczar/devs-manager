from sqlalchemy.orm import Session
from sqlalchemy import select
from src.adapters.db.models import OrganizationModel
from src.adapters.db.repositories.base_repository import BaseRepository


class OrganizationRepository(BaseRepository[OrganizationModel]):
    def __init__(self, db: Session):
        super().__init__(db, OrganizationModel)

    def get_by_name(self, name: str) -> OrganizationModel | None:
        stmt = select(OrganizationModel).where(OrganizationModel.name == name)
        return self.db.scalar(stmt)

    def get_by_owner(self, owner_id: int) -> list[OrganizationModel]:
        stmt = select(OrganizationModel).where(OrganizationModel.owner_id == owner_id)
        return list(self.db.scalars(stmt).all())

    def get_or_create(
        self, name: str, owner_id: int, main_vcs: str
    ) -> tuple[OrganizationModel, bool]:
        org = self.get_by_name(name)
        if org:
            return org, False

        org = self.create(name=name, owner_id=owner_id, main_vcs=main_vcs)
        return org, True

    def transfer_ownership(
        self, org_id: int, new_owner_id: int
    ) -> OrganizationModel | None:
        return self.update(org_id, owner_id=new_owner_id)
