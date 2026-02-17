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
