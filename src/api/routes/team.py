import json
from urllib.parse import urlparse
from copy import deepcopy

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from typing import Any

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


# ───────────────────────── Settings ─────────────────────────

DEFAULT_ANALYSIS_CONFIG: dict[str, Any] = {
    "file_filters": {
        "exclude_patterns": [
            "*.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
            "*.min.js", "*.min.css", "dist/", "build/", "node_modules/",
            "__pycache__/", "*.pyc", "*.egg-info/",
        ],
        "exclude_hidden": True,
    },
    "commit_classification": {
        "default_category": "other",
        "rules": [
            {"name": "Feature", "category": "feat", "keywords": ["feat", "add", "new", "implement", "introduce"], "priority": 95},
            {"name": "Bugfix", "category": "fix", "keywords": ["fix", "bug", "patch", "resolve", "repair"], "priority": 99},
            {"name": "Performance", "category": "perf", "keywords": ["perf", "performance", "optimize", "speed"], "priority": 85},
            {"name": "Refactor", "category": "refactor", "keywords": ["refactor", "restructure", "rework", "reorganize", "simplify"], "priority": 80},
            {"name": "Tests", "category": "test", "keywords": ["test", "spec", "coverage"], "priority": 75},
            {"name": "Docs", "category": "docs", "keywords": ["docs", "doc", "readme", "changelog", "document"], "priority": 70},
            {"name": "Chore", "category": "chore", "keywords": ["chore", "build", "ci", "cd", "deps", "upgrade", "bump"], "priority": 60},
            {"name": "Style", "category": "style", "keywords": ["style", "format", "lint", "prettier", "whitespace"], "priority": 55},
            {"name": "Revert", "category": "revert", "keywords": ["revert", "rollback"], "priority": 90},
        ],
    },
    "special_commits": {
        "include_merge_commits": False,
        "include_revert_commits": True,
        "bot_logins": ["dependabot[bot]", "renovate[bot]", "github-actions[bot]"],
    },
    "breaking_change_markers": ["!", "BREAKING CHANGE", "BREAKING-CHANGE"],
}

DEFAULT_WORKFLOW_CONFIG: dict[str, Any] = {
    "sprint": {
        "enabled": False,
        "duration_days": 14,
    },
    "working_hours": {
        "start": 9,
        "end": 18,
        "timezone": "UTC",
    },
    "working_days": [1, 2, 3, 4, 5],
}

DEFAULT_METRICS_CONFIG: dict[str, Any] = {
    "commit_weights": {
        "feat": 3.0,
        "fix": 2.0,
        "refactor": 2.0,
        "test": 1.5,
        "perf": 2.5,
        "docs": 0.5,
        "style": 0.5,
        "chore": 0.5,
        "ci": 0.5,
        "build": 0.5,
        "revert": 0.0,
    },
    "significant_commit_min_lines": 5,
    "require_conventional_commits": False,
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Рекурсивно мержит override поверх base."""
    result = deepcopy(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


class TeamSettingsResponse(BaseModel):
    analysis_config: dict[str, Any]
    workflow_config: dict[str, Any]
    metrics_config: dict[str, Any]


class TeamSettingsUpdate(BaseModel):
    analysis_config: dict[str, Any] | None = None
    workflow_config: dict[str, Any] | None = None
    metrics_config: dict[str, Any] | None = None


@router.get("/{team_id}/settings", response_model=TeamSettingsResponse)
def get_team_settings(
    team_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    team_repo = TeamRepository(db)
    team = team_repo.get_by_id(team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    if team.manager_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the manager of this team")

    stored_analysis = json.loads(team.analysis_config or "{}")
    stored_workflow = json.loads(team.workflow_config or "{}")
    stored_metrics = json.loads(team.metrics_config or "{}")

    return TeamSettingsResponse(
        analysis_config=_deep_merge(DEFAULT_ANALYSIS_CONFIG, stored_analysis),
        workflow_config=_deep_merge(DEFAULT_WORKFLOW_CONFIG, stored_workflow),
        metrics_config=_deep_merge(DEFAULT_METRICS_CONFIG, stored_metrics),
    )


@router.put("/{team_id}/settings", response_model=TeamSettingsResponse)
def update_team_settings(
    team_id: int,
    data: TeamSettingsUpdate,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    team_repo = TeamRepository(db)
    team = team_repo.get_by_id(team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    if team.manager_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the manager of this team")

    if data.analysis_config is not None:
        team.analysis_config = json.dumps(data.analysis_config)
    if data.workflow_config is not None:
        team.workflow_config = json.dumps(data.workflow_config)
    if data.metrics_config is not None:
        team.metrics_config = json.dumps(data.metrics_config)

    db.commit()
    db.refresh(team)

    stored_analysis = json.loads(team.analysis_config or "{}")
    stored_workflow = json.loads(team.workflow_config or "{}")
    stored_metrics = json.loads(team.metrics_config or "{}")

    return TeamSettingsResponse(
        analysis_config=_deep_merge(DEFAULT_ANALYSIS_CONFIG, stored_analysis),
        workflow_config=_deep_merge(DEFAULT_WORKFLOW_CONFIG, stored_workflow),
        metrics_config=_deep_merge(DEFAULT_METRICS_CONFIG, stored_metrics),
    )
