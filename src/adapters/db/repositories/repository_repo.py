from sqlalchemy.orm import Session
from sqlalchemy import select
from src.adapters.db.models.repository import RepositoryModel
from src.adapters.db.repositories.base_repository import BaseRepository


class RepositoryRepository(BaseRepository[RepositoryModel]):
    def __init__(self, db: Session):
        super().__init__(db, RepositoryModel)

    def get_by_external_id(
        self, 
        vcs_provider: str, 
        external_id: str
    ) -> RepositoryModel | None:
        stmt = select(RepositoryModel).where(
            RepositoryModel.vcs_provider == vcs_provider,
            RepositoryModel.external_id == external_id
        )
        return self.db.scalar(stmt)

    def get_by_owner_name(
        self, 
        owner: str, 
        name: str, 
        vcs_provider: str = "github"
    ) -> RepositoryModel | None:
        stmt = select(RepositoryModel).where(
            RepositoryModel.owner == owner,
            RepositoryModel.name == name,
            RepositoryModel.vcs_provider == vcs_provider
        )
        return self.db.scalar(stmt)

    def get_by_url(self, url: str) -> RepositoryModel | None:
        stmt = select(RepositoryModel).where(RepositoryModel.url == url)
        return self.db.scalar(stmt)

    def get_or_create(
        self,
        owner: str,
        name: str,
        vcs_provider: str = "github",
        external_id: str | None = None,
        url: str | None = None,
        default_branch: str | None = None,
        project_id: int | None = None,
    ) -> tuple[RepositoryModel, bool]:
        # Сначала пробуем найти по owner/name
        repo = self.get_by_owner_name(owner, name, vcs_provider)
        if repo:
            return repo, False

        # Если есть external_id, пробуем найти по нему
        if external_id:
            repo = self.get_by_external_id(vcs_provider, external_id)
            if repo:
                return repo, False

        # Создаем новый
        if url is None:
            raise ValueError("url is required for repository creation")

        repo = self.create(
            owner=owner,
            name=name,
            vcs_provider=vcs_provider,
            external_id=external_id,
            url=url,
            default_branch=default_branch,
            project_id=project_id,
        )
        return repo, True

    def get_by_project(self, project_id: int) -> list[RepositoryModel]:
        stmt = select(RepositoryModel).where(
            RepositoryModel.project_id == project_id
        )
        return list(self.db.scalars(stmt).all())

    def get_by_owner(
        self, 
        owner: str, 
        vcs_provider: str | None = None
    ) -> list[RepositoryModel]:
        stmt = select(RepositoryModel).where(RepositoryModel.owner == owner)
        
        if vcs_provider:
            stmt = stmt.where(RepositoryModel.vcs_provider == vcs_provider)
        
        return list(self.db.scalars(stmt).all())

    def update_default_branch(
        self, 
        repo_id: int, 
        branch: str
    ) -> RepositoryModel | None:
        return self.update(repo_id, default_branch=branch)

    def link_to_project(
        self, 
        repo_id: int, 
        project_id: int
    ) -> RepositoryModel | None:
        return self.update(repo_id, project_id=project_id)

    def unlink_from_project(self, repo_id: int) -> RepositoryModel | None:
        return self.update(repo_id, project_id=None)

    def count_by_vcs_provider(self, vcs_provider: str) -> int:
        stmt = select(RepositoryModel).where(
            RepositoryModel.vcs_provider == vcs_provider
        )
        return self.db.query(RepositoryModel).filter(
            RepositoryModel.vcs_provider == vcs_provider
        ).count()