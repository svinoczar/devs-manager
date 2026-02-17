from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from sqlalchemy.orm import Session

from src.api.dependencies import get_db, get_current_user
from src.adapters.db.models.user import UserModel
from src.adapters.db.repositories.team_repo import TeamRepository
from src.adapters.db.repositories.project_repo import ProjectRepository
from src.adapters.db.repositories.organization_repo import OrganizationRepository
from src.adapters.db.repositories.repository_repo import RepositoryRepository
from src.data.enums.vcs import VCS


router = APIRouter(prefix="/team", tags=["team"])

VCS_HOSTS: dict[str, VCS] = {
    "github.com": VCS.github,
    "gitlab.com": VCS.gitlab,
    "bitbucket.org": VCS.bitbucket,
}


def parse_repo_url(url: str) -> tuple[VCS, str, str]:
    """Returns (vcs, owner, repo_name) from a repository URL."""
    if not url.startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    host = parsed.netloc.lower().lstrip("www.")
    vcs = VCS_HOSTS.get(host, VCS.svn)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        raise ValueError(f"Cannot parse owner/repo from URL: {url}")
    owner = parts[0]
    name = parts[1].removesuffix(".git")
    return vcs, owner, name


class TeamCreate(BaseModel):
    name: str
    project_id: int


class TeamResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: int
    name: str
    project_id: int
    manager_id: int
    vcs: str


@router.post("/create", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
def create_team(
    data: TeamCreate,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proj_repo = ProjectRepository(db)
    project = proj_repo.get_by_id(data.project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.manager_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the manager of this project")

    team_repo = TeamRepository(db)
    if team_repo.get_by_name_and_project(data.name, data.project_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Team with this name already exists in this project")

    team = team_repo.create(
        name=data.name,
        project_id=data.project_id,
        manager_id=current_user.id,
        vcs=project.vcs,
        analysis_config="{}",
        workflow_config="{}",
        metrics_config="{}",
        global_config="{}",
    )
    return team


@router.get("/by-project/{project_id}", response_model=list[TeamResponse])
def get_teams_by_project(
    project_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proj_repo = ProjectRepository(db)
    project = proj_repo.get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    team_repo = TeamRepository(db)
    return team_repo.get_by_project(project_id)


class RepoAdd(BaseModel):
    url: str


class RepoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: int
    url: str
    owner: str
    name: str
    vcs_provider: str
    team_id: int | None


@router.post("/{team_id}/repos", response_model=RepoResponse, status_code=status.HTTP_201_CREATED)
def add_repo_to_team(
    team_id: int,
    data: RepoAdd,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    team_repo = TeamRepository(db)
    team = team_repo.get_by_id(team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    if team.manager_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the manager of this team")

    try:
        vcs, owner, name = parse_repo_url(data.url)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    repo_repo = RepositoryRepository(db)
    existing = repo_repo.get_by_url(data.url)
    if existing and existing.team_id == team_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Repository already added to this team")

    repo = repo_repo.create(
        url=data.url,
        owner=owner,
        name=name,
        vcs_provider=vcs,
        project_id=team.project_id,
        team_id=team_id,
    )
    return repo


@router.get("/{team_id}/repos", response_model=list[RepoResponse])
def get_team_repos(
    team_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    team_repo = TeamRepository(db)
    if not team_repo.get_by_id(team_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    repo_repo = RepositoryRepository(db)
    return repo_repo.get_by_team(team_id)


@router.delete("/{team_id}/repos/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_repo_from_team(
    team_id: int,
    repo_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    team_repo = TeamRepository(db)
    team = team_repo.get_by_id(team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    if team.manager_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the manager of this team")

    repo_repo = RepositoryRepository(db)
    repo = repo_repo.get_by_id(repo_id)
    if not repo or repo.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found in this team")

    repo_repo.delete(repo_id)
