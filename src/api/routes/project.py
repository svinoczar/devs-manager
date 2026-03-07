from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from sqlalchemy.orm import Session

from src.api.dependencies import get_db, get_current_user
from src.adapters.db.models.user import UserModel
from src.adapters.db.repositories.project_repo import ProjectRepository
from src.adapters.db.repositories.organization_repo import OrganizationRepository
from src.data.enums.vcs import VCS


router = APIRouter(prefix="/project", tags=["project"])


class ProjectCreate(BaseModel):
    name: str
    organization_id: int


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: int
    name: str
    organization_id: int
    manager_id: int
    vcs: str
    emoji: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    emoji: str | None = None


@router.post("/create", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    data: ProjectCreate,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org_repo = OrganizationRepository(db)
    org = org_repo.get_by_id(data.organization_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    if org.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the owner of this organization")

    proj_repo = ProjectRepository(db)
    if proj_repo.get_by_name_and_org(data.name, data.organization_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Project with this name already exists in this organization")

    project = proj_repo.create(
        name=data.name,
        organization_id=data.organization_id,
        manager_id=current_user.id,
        vcs=org.main_vcs,
    )
    return project


@router.get("/by-org/{org_id}", response_model=list[ProjectResponse])
def get_projects_by_org(
    org_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org_repo = OrganizationRepository(db)
    org = org_repo.get_by_id(org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    proj_repo = ProjectRepository(db)
    return proj_repo.get_by_org(org_id)


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: int,
    data: ProjectUpdate,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proj_repo = ProjectRepository(db)
    project = proj_repo.get_by_id(project_id)

    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    if project.manager_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only project manager can update the project"
        )

    # Update fields
    if data.name is not None:
        # Check if name is unique within organization
        existing = proj_repo.get_by_name_and_org(data.name, project.organization_id)
        if existing and existing.id != project_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Project with this name already exists in this organization"
            )
        project.name = data.name

    if data.emoji is not None:
        project.emoji = data.emoji

    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Удаляет проект и все связанные команды, репозитории, коммиты.
    Требует права manager проекта.
    """
    proj_repo = ProjectRepository(db)
    project = proj_repo.get_by_id(project_id)

    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    if project.manager_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only project manager can delete the project"
        )

    # Ручное каскадное удаление
    from src.adapters.db.repositories.team_repo import TeamRepository
    from src.adapters.db.repositories.repository_repo import RepositoryRepository
    from src.adapters.db.repositories.commit_repo import CommitRepository
    from src.adapters.db.repositories.sync_session_repo import SyncSessionRepository
    from src.adapters.db.models.commit import CommitModel
    from src.adapters.db.models.commit_file import CommitFileModel
    from src.adapters.db.models.team_member import TeamMemberModel
    from src.adapters.db.models.sync_session import SyncSessionModel
    from src.adapters.db.models.pull_request import PullRequestModel
    from src.adapters.db.models.issue import IssueModel

    team_repo = TeamRepository(db)
    repo_repo = RepositoryRepository(db)

    # Получаем все команды проекта
    teams = team_repo.get_by_project(project_id)

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
    db.commit()
    proj_repo.delete(project_id)
