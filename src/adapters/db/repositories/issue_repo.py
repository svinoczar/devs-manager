from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import select

from src.adapters.db.models.issue import IssueModel
from src.adapters.db.repositories.base_repository import BaseRepository


class IssueRepository(BaseRepository[IssueModel]):
    def __init__(self, db: Session):
        super().__init__(db, IssueModel)

    def get_by_repo_and_number(
        self, repository_id: int, number: int
    ) -> IssueModel | None:
        stmt = select(IssueModel).where(
            IssueModel.repository_id == repository_id,
            IssueModel.number == number,
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
        issue_created_at: datetime | None = None,
        issue_closed_at: datetime | None = None,
    ) -> tuple[IssueModel, bool]:
        existing = self.get_by_repo_and_number(repository_id, number)
        if existing:
            return existing, False

        issue = self.create(
            repository_id=repository_id,
            number=number,
            title=title,
            state=state,
            author_login=author_login,
            author_avatar=author_avatar,
            contributor_id=contributor_id,
            external_id=external_id,
            issue_created_at=issue_created_at,
            issue_closed_at=issue_closed_at,
        )
        return issue, True

    def get_by_team_date_range(
        self,
        team_id: int,
        since: datetime,
        until: datetime,
    ) -> list[IssueModel]:
        from src.adapters.db.models.repository import RepositoryModel

        stmt = (
            select(IssueModel)
            .join(RepositoryModel, IssueModel.repository_id == RepositoryModel.id)
            .where(
                RepositoryModel.team_id == team_id,
                IssueModel.issue_created_at >= since,
                IssueModel.issue_created_at < until,
            )
            .order_by(IssueModel.issue_created_at)
        )
        return list(self.db.scalars(stmt).all())
