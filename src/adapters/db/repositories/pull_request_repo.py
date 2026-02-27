from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import select

from src.adapters.db.models.pull_request import PullRequestModel
from src.adapters.db.repositories.base_repository import BaseRepository


class PullRequestRepository(BaseRepository[PullRequestModel]):
    def __init__(self, db: Session):
        super().__init__(db, PullRequestModel)

    def get_by_repo_and_number(
        self, repository_id: int, number: int
    ) -> PullRequestModel | None:
        stmt = select(PullRequestModel).where(
            PullRequestModel.repository_id == repository_id,
            PullRequestModel.number == number,
        )
        return self.db.scalar(stmt)

    def get_or_create(
        self,
        repository_id: int,
        number: int,
        title: str,
        state: str,
        author_login: str | None = None,
        author_avatar: str | None = None,
        contributor_id: int | None = None,
        external_id: int | None = None,
        pr_created_at: datetime | None = None,
        pr_closed_at: datetime | None = None,
        pr_merged_at: datetime | None = None,
    ) -> tuple[PullRequestModel, bool]:
        existing = self.get_by_repo_and_number(repository_id, number)
        if existing:
            return existing, False

        pr = self.create(
            repository_id=repository_id,
            number=number,
            title=title,
            state=state,
            author_login=author_login,
            author_avatar=author_avatar,
            contributor_id=contributor_id,
            external_id=external_id,
            pr_created_at=pr_created_at,
            pr_closed_at=pr_closed_at,
            pr_merged_at=pr_merged_at,
        )
        return pr, True

    def get_by_repository_date_range(
        self,
        repository_id: int,
        since: datetime,
        until: datetime,
    ) -> list[PullRequestModel]:
        stmt = (
            select(PullRequestModel)
            .where(
                PullRequestModel.repository_id == repository_id,
                PullRequestModel.pr_created_at >= since,
                PullRequestModel.pr_created_at < until,
            )
            .order_by(PullRequestModel.pr_created_at)
        )
        return list(self.db.scalars(stmt).all())

    def get_by_team_date_range(
        self,
        team_id: int,
        since: datetime,
        until: datetime,
    ) -> list[PullRequestModel]:
        from src.adapters.db.models.repository import RepositoryModel

        stmt = (
            select(PullRequestModel)
            .join(RepositoryModel, PullRequestModel.repository_id == RepositoryModel.id)
            .where(
                RepositoryModel.team_id == team_id,
                PullRequestModel.pr_created_at >= since,
                PullRequestModel.pr_created_at < until,
            )
            .order_by(PullRequestModel.pr_created_at)
        )
        return list(self.db.scalars(stmt).all())
