from sqlalchemy.orm import Session
from sqlalchemy import select
from src.adapters.db.models import TeamModel
from src.adapters.db.repositories.base_repository import BaseRepository


class TeamRepository(BaseRepository[TeamModel]):
    def __init__(self, db: Session):
        super().__init__(db, TeamModel)

    def get_by_project(self, project_id: int) -> list[TeamModel]:
        stmt = select(TeamModel).where(TeamModel.project_id == project_id)
        return list(self.db.scalars(stmt).all())

    def get_by_name_and_project(self, name: str, project_id: int) -> TeamModel | None:
        stmt = select(TeamModel).where(
            TeamModel.name == name, TeamModel.project_id == project_id
        )
        return self.db.scalar(stmt)

    def get_or_create(
        self, name: str, project_id: int, vcs: str, manager_id: int
    ) -> tuple[TeamModel, bool]:
        team = self.get_by_name_and_project(name, project_id)
        if team:
            return team, False

        team = self.create(
            name=name,
            project_id=project_id,
            vcs=vcs,
            manager_id=manager_id,
            analysis_config="{}",
            workflow_config="{}",
            metrics_config="{}",
            global_config="{}",
        )
        return team, True
