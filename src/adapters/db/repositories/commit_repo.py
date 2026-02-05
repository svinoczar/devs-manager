from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import select
from src.adapters.db.models.commit import CommitModel
from src.adapters.db.repositories.base_repository import BaseRepository


class CommitRepository(BaseRepository[CommitModel]):
    def __init__(self, db: Session):
        super().__init__(db, CommitModel)

    def get_by_repo_and_sha(
        self,
        repository_id: int,
        sha: str
    ) -> CommitModel | None:
        stmt = select(CommitModel).where(
            CommitModel.repository_id == repository_id,
            CommitModel.sha == sha
        )
        return self.db.scalar(stmt)

    def get_or_create(
        self,
        repository_id: int,
        sha: str,
        message: str,
        contributor_id: int | None = None,
    ) -> tuple[CommitModel, bool]:
        commit = self.get_by_repo_and_sha(repository_id, sha)
        if commit:
            return commit, False

        commit = self.create(
            repository_id=repository_id,
            contributor_id=contributor_id,
            sha=sha,
            message=message,
        )
        return commit, True

    def get_commits_for_update(
        self,
        repository_id: int,
        limit: int,
        since: datetime | None = None,
    ) -> list[CommitModel]:
        stmt = select(CommitModel).where(
            CommitModel.repository_id == repository_id
        )
        
        if since:
            stmt = stmt.where(CommitModel.authored_at >= since)
        
        stmt = stmt.limit(limit)
        return list(self.db.scalars(stmt).all())

    def update_details(
        self,
        commit_id: int,
        *,
        authored_at: datetime | None = None,
        committed_at: datetime | None = None,
        author_name: str | None = None,
        author_email: str | None = None,
        additions: int | None = None,
        deletions: int | None = None,
        changes: int | None = None,
        commit_type: str | None = None,
        is_conventional: bool | None = None,
        conventional_type: str | None = None,
        conventional_scope: str | None = None,
        is_breaking_change: bool | None = None,
        is_merge_commit: bool | None = None,
        is_pr_commit: bool | None = None,
        is_revert_commit: bool | None = None,
        parents_count: int | None = None,
        files_changed: int | None = None,
    ) -> CommitModel | None:
        
        commit = self.get_by_id(commit_id)
        if not commit:
            return None

        if authored_at is not None:
            commit.authored_at = authored_at
        if committed_at is not None:
            commit.committed_at = committed_at
        
        if author_name is not None:
            commit.author_name = author_name
        if author_email is not None:
            commit.author_email = author_email

        if additions is not None:
            commit.additions = additions
        if deletions is not None:
            commit.deletions = deletions
        if changes is not None:
            commit.changes = changes

        if commit_type is not None:
            commit.commit_type = commit_type

        if is_conventional is not None:
            commit.is_conventional = is_conventional
        if conventional_type is not None:
            commit.conventional_type = conventional_type
        if conventional_scope is not None:
            commit.conventional_scope = conventional_scope
        if is_breaking_change is not None:
            commit.is_breaking_change = is_breaking_change

        if is_merge_commit is not None:
            commit.is_merge_commit = is_merge_commit
        if is_pr_commit is not None:
            commit.is_pr_commit = is_pr_commit
        if is_revert_commit is not None:
            commit.is_revert_commit = is_revert_commit

        if parents_count is not None:
            commit.parents_count = parents_count
        if files_changed is not None:
            commit.files_changed = files_changed

        self.db.commit()
        self.db.refresh(commit)
        return commit

    def get_by_repository(
        self, 
        repository_id: int,
        limit: int = 100,
        offset: int = 0
    ) -> list[CommitModel]:
        stmt = (
            select(CommitModel)
            .where(CommitModel.repository_id == repository_id)
            .order_by(CommitModel.authored_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.scalars(stmt).all())

    def count_by_repository(self, repository_id: int) -> int:
        stmt = select(CommitModel).where(
            CommitModel.repository_id == repository_id
        )
        return self.db.query(CommitModel).filter(
            CommitModel.repository_id == repository_id
        ).count()

    def get_by_contributor(
        self, 
        contributor_id: int,
        limit: int = 100
    ) -> list[CommitModel]:
        stmt = (
            select(CommitModel)
            .where(CommitModel.contributor_id == contributor_id)
            .order_by(CommitModel.authored_at.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())