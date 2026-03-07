from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.orm import Session

from src.api.dependencies import get_db, get_current_user
from src.adapters.db.models.user import UserModel
from src.adapters.db.repositories.organization_repo import OrganizationRepository
from src.data.enums.vcs import VCS
from src.data.enums.company_size import CompanySize


router = APIRouter(prefix="/org", tags=["organization"])


class OrgCreate(BaseModel):
    name: str
    main_vcs: VCS = VCS.github
    company_size: CompanySize = CompanySize.big


class OrgResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: int
    name: str
    owner_id: int
    main_vcs: str
    company_size: str
    emoji: str | None = None


class OrgUpdate(BaseModel):
    name: str | None = None
    emoji: str | None = None


@router.post("/create", response_model=OrgResponse, status_code=status.HTTP_201_CREATED)
def create_organization(
    org_data: OrgCreate,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create a new organization.

    - **name**: Unique organization name
    - **main_vcs**: Primary VCS provider (github, gitlab, bitbucket, svn)
    """
    org_repo = OrganizationRepository(db)

    if org_repo.get_by_name(org_data.name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Organization with this name already exists",
        )

    org = org_repo.create(
        name=org_data.name,
        owner_id=current_user.id,
        main_vcs=org_data.main_vcs,
        company_size=org_data.company_size,
    )
    return org


@router.get("/my", response_model=list[OrgResponse])
def get_my_organizations(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all organizations owned by the current user."""
    org_repo = OrganizationRepository(db)
    return org_repo.get_by_owner(current_user.id)


@router.patch("/{org_id}", response_model=OrgResponse)
def update_organization(
    org_id: int,
    data: OrgUpdate,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org_repo = OrganizationRepository(db)
    org = org_repo.get_by_id(org_id)

    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    if org.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organization owner can update it"
        )

    # Update fields
    if data.name is not None:
        # Check if name is unique
        existing = org_repo.get_by_name(data.name)
        if existing and existing.id != org_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Organization with this name already exists"
            )
        org.name = data.name

    if data.emoji is not None:
        org.emoji = data.emoji

    db.commit()
    db.refresh(org)
    return org


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_organization(
    org_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Удаляет организацию и все связанные проекты, команды, репозитории, коммиты.
    Требует права owner организации.
    """
    org_repo = OrganizationRepository(db)
    org = org_repo.get_by_id(org_id)

    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    if org.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organization owner can delete it"
        )

    # Ручное каскадное удаление
    from src.adapters.db.repositories.project_repo import ProjectRepository
    from src.adapters.db.repositories.team_repo import TeamRepository
    from src.adapters.db.repositories.repository_repo import RepositoryRepository
    from src.adapters.db.models.commit import CommitModel
    from src.adapters.db.models.commit_file import CommitFileModel
    from src.adapters.db.models.team_member import TeamMemberModel
    from src.adapters.db.models.sync_session import SyncSessionModel
    from src.adapters.db.models.pull_request import PullRequestModel
    from src.adapters.db.models.issue import IssueModel

    proj_repo = ProjectRepository(db)
    team_repo = TeamRepository(db)
    repo_repo = RepositoryRepository(db)

    # Получаем все проекты организации
    projects = proj_repo.get_by_org(org_id)

    for project in projects:
        # Получаем все команды проекта
        teams = team_repo.get_by_project(project.id)

        for team in teams:
            # Удаляем все репозитории команды
            repos = repo_repo.get_by_team(team.id)

            for repo in repos:
                # Удаляем commit_files
                commits = db.query(CommitModel).filter(CommitModel.repository_id == repo.id).all()
                for commit in commits:
                    db.query(CommitFileModel).filter(CommitFileModel.commit_id == commit.id).delete()

                # Удаляем коммиты
                db.query(CommitModel).filter(CommitModel.repository_id == repo.id).delete()

                # Удаляем PR и Issues
                try:
                    db.query(PullRequestModel).filter(PullRequestModel.repository_id == repo.id).delete()
                    db.query(IssueModel).filter(IssueModel.repository_id == repo.id).delete()
                except:
                    pass

                # Удаляем sync sessions
                db.query(SyncSessionModel).filter(SyncSessionModel.repository_id == repo.id).delete()

                # Удаляем репозиторий
                repo_repo.delete(repo.id)

            # Удаляем team_members
            db.query(TeamMemberModel).filter(TeamMemberModel.team_id == team.id).delete()

            # Удаляем команду
            team_repo.delete(team.id)

        # Удаляем проект
        proj_repo.delete(project.id)

    # Удаляем организацию
    db.commit()
    org_repo.delete(org_id)
