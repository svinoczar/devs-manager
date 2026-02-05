from sqlalchemy.orm import Session
from sqlalchemy import select
from src.adapters.db.models.team import TeamModel
from src.adapters.db.repositories.base_repository import BaseRepository


class TeamRepository(BaseRepository[TeamModel]):
    def __init__(self, db: Session):
        super().__init__(db, TeamModel)

    def get_by_project(self, proj_id: int) -> list[TeamModel]:
        stmt = select(TeamModel).where(TeamModel.proj_id == proj_id)
        return list(self.db.scalars(stmt).all())

    def get_by_name_and_project(self, name: str, proj_id: int) -> TeamModel | None:
        stmt = select(TeamModel).where(
            TeamModel.name == name, TeamModel.proj_id == proj_id
        )
        return self.db.scalar(stmt)

    def get_or_create(
        self, name: str, proj_id: int, vcs: str
    ) -> tuple[TeamModel, bool]:
        team = self.get_by_name_and_project(name, proj_id)
        if team:
            return team, False

        team = self.create(name=name, proj_id=proj_id, vcs=vcs)
        return team, True
