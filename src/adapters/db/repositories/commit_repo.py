# src/adapters/db/repositories/commit_repo.py
from datetime import datetime
from sqlalchemy.orm import Session
from src.adapters.db.models.commit import CommitModel

class CommitRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        repository_id: int,
        contributor_id: int | None,
        sha: str,
        message: str
    ) -> CommitModel:
        commit = CommitModel(
            repository_id=repository_id,
            contributor_id=contributor_id,
            sha=sha,
            message=message
        )
        self.db.add(commit)
        self.db.commit()
        self.db.refresh(commit)
        return commit

    def get_by_repo_and_sha(
        self,
        repository_id: int,
        sha: str
    ) -> CommitModel | None:
        return (
            self.db.query(CommitModel)
            .filter_by(repository_id=repository_id, sha=sha)
            .first()
        )

    def get_or_create(
        self,
        repository_id: int,
        sha: str,
        message: str,
        contributor_id: int | None = None,
    ):
        commit = self.get_by_repo_and_sha(repository_id, sha)
        if commit:
            return commit

        return self.create(
            repository_id=repository_id,
            contributor_id=contributor_id,
            sha=sha,
            message=message,
        )

    def get_commits_for_update(
        self,
        repository_id: int,
        limit: int,
        since: datetime | None = None,
    ) -> list[CommitModel]:
        query = self.db.query(CommitModel).filter(
            CommitModel.repository_id == repository_id,
        )
        if since:
            query = query.filter(CommitModel.authored_at >= since)
        return query.limit(limit).all()


    def update_details(
        self,
        commit_id: int,
        *,

        authored_at=None,
        committed_at=None,

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
    ):
        commit = self.db.get(CommitModel, commit_id)
        if not commit:
            return

        commit.authored_at = authored_at
        commit.committed_at = committed_at

        commit.author_name = author_name
        commit.author_email = author_email

        commit.additions = additions
        commit.deletions = deletions
        commit.changes = changes

        commit.commit_type = commit_type

        commit.is_conventional = is_conventional
        commit.conventional_type = conventional_type
        commit.conventional_scope = conventional_scope
        commit.is_breaking_change = is_breaking_change

        commit.is_merge_commit = is_merge_commit
        commit.is_pr_commit = is_pr_commit
        commit.is_revert_commit = is_revert_commit

        commit.parents_count = parents_count
        commit.files_changed = files_changed

        self.db.commit()
