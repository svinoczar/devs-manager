from sqlalchemy.orm import Session
from sqlalchemy import select
from src.adapters.db.models import ProjectModel
from src.adapters.db.repositories.base_repository import BaseRepository


class ProjectRepository(BaseRepository[ProjectModel]):
    def __init__(self, db: Session):
        super().__init__(db, ProjectModel)

    def get_by_org(self, org_id: int) -> list[ProjectModel]:
        stmt = select(ProjectModel).where(ProjectModel.organization_id == org_id)
        return list(self.db.scalars(stmt).all())

    def get_by_name_and_org(self, name: str, org_id: int) -> ProjectModel | None:
        stmt = select(ProjectModel).where(
            ProjectModel.name == name, ProjectModel.organization_id == org_id
        )
        return self.db.scalar(stmt)

    def get_or_create(
        self, name: str, org_id: int, vcs: str, manager_id: int
    ) -> tuple[ProjectModel, bool]:
        project = self.get_by_name_and_org(name, org_id)
        if project:
            return project, False

        project = self.create(name=name, organization_id=org_id, vcs=vcs, manager_id=manager_id)
        return project, True
