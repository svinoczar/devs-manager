from sqlalchemy.orm import Session
from sqlalchemy import select, or_
from src.adapters.db.models.contributor import ContributorModel
from src.adapters.db.repositories.base_repository import BaseRepository


class ContributorRepository(BaseRepository[ContributorModel]):
    def __init__(self, db: Session):
        super().__init__(db, ContributorModel)

    def get_by_external_id(
        self, 
        vcs_provider: str, 
        external_id: str
    ) -> ContributorModel | None:
        stmt = select(ContributorModel).where(
            ContributorModel.vcs_provider == vcs_provider,
            ContributorModel.external_id == external_id
        )
        return self.db.scalar(stmt)

    def get_by_email(self, email: str) -> list[ContributorModel]:
        stmt = select(ContributorModel).where(ContributorModel.email == email)
        return list(self.db.scalars(stmt).all())

    def get_by_login(
        self, 
        login: str, 
        vcs_provider: str | None = None
    ) -> list[ContributorModel]:
        stmt = select(ContributorModel).where(ContributorModel.login == login)
        
        if vcs_provider:
            stmt = stmt.where(ContributorModel.vcs_provider == vcs_provider)
        
        return list(self.db.scalars(stmt).all())

    def get_or_create(
        self,
        vcs_provider: str,
        external_id: str,
        login: str | None = None,
        display_name: str | None = None,
        email: str | None = None,
        profile_url: str | None = None,
    ) -> tuple[ContributorModel, bool]:
        contributor = self.get_by_external_id(vcs_provider, external_id)
        if contributor:
            return contributor, False

        contributor = self.create(
            vcs_provider=vcs_provider,
            external_id=external_id,
            login=login,
            display_name=display_name,
            email=email,
            profile_url=profile_url,
        )
        return contributor, True

    def search_by_email_or_login(
        self, 
        search_term: str
    ) -> list[ContributorModel]:
        stmt = select(ContributorModel).where(
            or_(
                ContributorModel.email.ilike(f"%{search_term}%"),
                ContributorModel.login.ilike(f"%{search_term}%"),
                ContributorModel.display_name.ilike(f"%{search_term}%")
            )
        )
        return list(self.db.scalars(stmt).all())

    def get_by_vcs_provider(self, vcs_provider: str) -> list[ContributorModel]:
        stmt = select(ContributorModel).where(
            ContributorModel.vcs_provider == vcs_provider
        )
        return list(self.db.scalars(stmt).all())
