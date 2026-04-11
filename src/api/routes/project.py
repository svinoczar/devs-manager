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

    # Оптимизированное удаление - используем batch delete для больших таблиц
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[delete_project] Starting deletion of project {project_id}: {project.name}")

    # Вспомогательная функция для batch deletion используя raw SQL с CTID
    def batch_delete_raw(table_name, where_clause, batch_size=5000, label="records"):
        """Удаляет записи порциями используя CTID (быстрее чем IN с ID)"""
        from sqlalchemy import text
        total_deleted = 0

        while True:
            # Используем CTID для быстрого batch deletion
            sql = text(f"""
                DELETE FROM {table_name}
                WHERE ctid IN (
                    SELECT ctid FROM {table_name}
                    WHERE {where_clause}
                    LIMIT :batch_size
                )
            """)

            result = db.execute(sql, {"batch_size": batch_size})
            deleted = result.rowcount

            db.commit()  # Commit после каждого батча!
            total_deleted += deleted

            if deleted > 0:
                logger.info(f"[delete_project] Deleted {total_deleted} {label}...")

            if deleted < batch_size:
                break

        logger.info(f"[delete_project] ✓ Total deleted {total_deleted} {label}")
        return total_deleted

    team_ids = [team.id for team in teams]
    logger.info(f"[delete_project] Found {len(team_ids)} teams")

    if team_ids:
        # Получаем все репозитории для всех команд
        repo_ids = [repo.id for team_id in team_ids for repo in repo_repo.get_by_team(team_id)]
        logger.info(f"[delete_project] Found {len(repo_ids)} repositories")

        if repo_ids:
            # Удаляем все commit_files для всех репозиториев batch'ами
            logger.info(f"[delete_project] Deleting commit files...")
            repo_ids_str = ','.join(map(str, repo_ids))
            batch_delete_raw(
                "commit_files",
                f"commit_id IN (SELECT id FROM commits WHERE repository_id IN ({repo_ids_str}))",
                batch_size=10000,
                label="commit files"
            )

            # Удаляем все коммиты batch'ами
            logger.info(f"[delete_project] Deleting commits...")
            batch_delete_raw(
                "commits",
                f"repository_id IN ({repo_ids_str})",
                batch_size=5000,
                label="commits"
            )

            # Удаляем PR и Issues
            try:
                logger.info(f"[delete_project] Deleting PRs and issues...")
                deleted_prs = db.query(PullRequestModel).filter(
                    PullRequestModel.repository_id.in_(repo_ids)
                ).delete(synchronize_session=False)
                # FIX: исправлен баг - было PullRequestModel.repository_id
                deleted_issues = db.query(IssueModel).filter(
                    IssueModel.repository_id.in_(repo_ids)
                ).delete(synchronize_session=False)
                db.commit()
                logger.info(f"[delete_project] ✓ Deleted {deleted_prs} PRs, {deleted_issues} issues")
            except Exception as e:
                logger.warning(f"[delete_project] Failed to delete PRs/issues: {e}")
                db.rollback()

            # Удаляем sync sessions
            logger.info(f"[delete_project] Deleting sync sessions...")
            deleted_sessions = db.query(SyncSessionModel).filter(
                SyncSessionModel.repository_id.in_(repo_ids)
            ).delete(synchronize_session=False)
            db.commit()
            logger.info(f"[delete_project] ✓ Deleted {deleted_sessions} sync sessions")

            # Удаляем все репозитории
            logger.info(f"[delete_project] Deleting repositories...")
            for repo_id in repo_ids:
                repo_repo.delete(repo_id)
            db.commit()
            logger.info(f"[delete_project] ✓ Deleted {len(repo_ids)} repositories")

        # Удаляем всех team_members
        logger.info(f"[delete_project] Deleting team members...")
        deleted_members = db.query(TeamMemberModel).filter(
            TeamMemberModel.team_id.in_(team_ids)
        ).delete(synchronize_session=False)
        db.commit()
        logger.info(f"[delete_project] ✓ Deleted {deleted_members} team members")

        # Удаляем все команды
        logger.info(f"[delete_project] Deleting teams...")
        for team_id in team_ids:
            team_repo.delete(team_id)
        db.commit()
        logger.info(f"[delete_project] ✓ Deleted {len(team_ids)} teams")

    # Удаляем проект
    logger.info(f"[delete_project] Deleting project...")
    proj_repo.delete(project_id)
    db.commit()
    logger.info(f"[delete_project] ✓ Project {project_id} deleted successfully")
