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
