from datetime import datetime
from pydantic import BaseModel
from typing import List, Optional


from src.data.domain.file_change import FileChange

class Commit(BaseModel):
    sha: str
    author_login: str | None
    message: Optional[str] = None

    files: List[FileChange] | None = None

    commit_type: str | None = None

    authored_at: Optional[datetime] = None
    committed_at: Optional[datetime] = None

    author_name: Optional[str] = None
    author_email: Optional[str] = None

    additions: Optional[int] = None
    deletions: Optional[int] = None
    changes: Optional[int] = None

    is_conventional: Optional[bool] = None 
    conventional_type: Optional[str] = None 
    conventional_scope: Optional[str] = None 
    is_breaking_change: Optional[bool] = None

    is_merge_commit: Optional[bool] = None
    is_pr_commit: Optional[bool] = None

    parents_count: Optional[int] = None
    parent_sha: Optional[str] = None
    files_changed: Optional[int] = None
    is_revert_commit: Optional[bool] = None 