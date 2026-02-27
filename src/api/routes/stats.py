import json
from datetime import datetime, date, timedelta, timezone
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.api.dependencies import get_db, get_current_user
from src.adapters.db.models.user import UserModel
from src.adapters.db.models.commit_file import CommitFileModel
from src.adapters.db.repositories.team_repo import TeamRepository
from src.adapters.db.repositories.commit_repo import CommitRepository
from src.adapters.db.repositories.commit_file_repo import CommitFileRepository
from src.adapters.db.repositories.contributor_repo import ContributorRepository
from src.adapters.db.repositories.pull_request_repo import PullRequestRepository
from src.adapters.db.repositories.issue_repo import IssueRepository

router = APIRouter(prefix="/stats", tags=["stats"])

# Типы коммитов, считающихся "функциональными"
FUNCTIONAL_TYPES = {"feat", "fix", "perf", "refactor"}
FEATURE_TYPES = {"feat", "perf", "refactor"}
BUG_TYPES = {"fix"}

DEFAULT_SPRINT_DAYS = 14
DEFAULT_SIGNIFICANT_MIN_LINES = 5


def _get_workflow_config(team) -> dict:
    try:
        return json.loads(team.workflow_config) if team.workflow_config else {}
    except Exception:
        return {}


def _get_metrics_config(team) -> dict:
    try:
        return json.loads(team.metrics_config) if team.metrics_config else {}
    except Exception:
        return {}


def _calc_dqi(
    commits_by_type: dict[str, int],
    total_commits: int,
    total_additions: int,
    significant_commits: int,
) -> float:
    """
    Developer Quality Index (0–100).

    DQI = functional_ratio * 0.5 + (1 - bug_rate) * 0.3 + significant_ratio * 0.2
    """
    if total_commits == 0:
        return 0.0

    feat_count = sum(commits_by_type.get(t, 0) for t in FEATURE_TYPES)
    fix_count = commits_by_type.get("fix", 0)

    # Functional ratio: share of feature/perf/refactor commits
    functional_ratio = feat_count / total_commits

    # Bug rate: share of fix commits relative to feat+fix
    denominator = feat_count + fix_count
    bug_rate = fix_count / denominator if denominator > 0 else 0.0

    # Significant commits ratio
    significant_ratio = significant_commits / total_commits

    dqi = (functional_ratio * 0.5 + (1 - bug_rate) * 0.3 + significant_ratio * 0.2) * 100
    return round(min(dqi, 100.0), 1)


@router.get("/team/{team_id}/sprint-stats")
def get_sprint_stats(
    team_id: int,
    days: int | str | None = None,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> dict[str, Any]:
    team_repo = TeamRepository(db)
    team = team_repo.get_by_id(team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    # --- Sprint duration ---
    workflow = _get_workflow_config(team)
    metrics = _get_metrics_config(team)

    sprint_cfg = workflow.get("sprint", {})
    default_sprint_days = sprint_cfg.get("duration_days", DEFAULT_SPRINT_DAYS)

    # Поддержка days=all (последние 5000 коммитов)
    is_all_time = False
    commit_limit = None

    if days == "all":
        is_all_time = True
        commit_limit = 5000
        sprint_days = 9999  # Большое число для извлечения всех коммитов
    else:
        sprint_days = int(days) if days else default_sprint_days

    significant_min_lines = (
        metrics.get("significant_commit_min_lines", DEFAULT_SIGNIFICANT_MIN_LINES)
    )
    commit_weights: dict[str, float] = metrics.get("commit_weights", {
        "feat": 3.0, "fix": 2.0, "perf": 2.5, "refactor": 2.0,
        "test": 1.5, "docs": 0.5, "style": 0.5, "chore": 0.5, "revert": 0.0,
    })

    until_dt = datetime.now(timezone.utc)

    if is_all_time:
        # Для "all" берем очень старую дату
        since_dt = datetime(2000, 1, 1, tzinfo=timezone.utc)
    else:
        since_dt = until_dt - timedelta(days=sprint_days)

    # --- Fetch data ---
    commit_repo = CommitRepository(db)
    pr_repo = PullRequestRepository(db)
    issue_repo = IssueRepository(db)
    contributor_repo = ContributorRepository(db)

    commits = commit_repo.get_by_team_date_range(team_id, since_dt, until_dt)

    # Применяем лимит для all-time режима
    limited = False
    if commit_limit and len(commits) > commit_limit:
        commits = sorted(commits, key=lambda c: c.authored_at or datetime.min, reverse=True)[:commit_limit]
        limited = True

    # Пересчитываем реальный период после применения лимита
    if commits:
        actual_since = min(c.authored_at for c in commits if c.authored_at)
        actual_until = max(c.authored_at for c in commits if c.authored_at)
    else:
        actual_since = since_dt
        actual_until = until_dt

    prs = pr_repo.get_by_team_date_range(team_id, actual_since, actual_until)
    issues = issue_repo.get_by_team_date_range(team_id, actual_since, actual_until)

    # --- Contributor lookup ---
    contributor_cache: dict[int, dict] = {}
    for c in contributor_repo.get_all(limit=10000):
        contributor_cache[c.id] = {
            "login": c.login or c.external_id,
            "avatar_url": c.profile_url,
        }

    # --- Build daily buckets ---
    daily: dict[str, dict] = {}

    if is_all_time:
        # Для all-time строим buckets на основе реальных дат коммитов
        if commits:
            actual_days = (actual_until.date() - actual_since.date()).days + 1
            for i in range(min(actual_days, 365)):  # Макс 365 дней для графиков
                day = (actual_since + timedelta(days=i)).date()
                daily[str(day)] = {
                    "date": str(day),
                    "commit_count": 0,
                    "additions": 0,
                    "deletions": 0,
                    "pr_count": 0,
                    "issue_count": 0,
                    "commits": [],
                    "pull_requests": [],
                    "issues": [],
                }
    else:
        for i in range(sprint_days):
            day = (since_dt + timedelta(days=i)).date()
            daily[str(day)] = {
                "date": str(day),
                "commit_count": 0,
                "additions": 0,
                "deletions": 0,
                "pr_count": 0,
                "issue_count": 0,
                "commits": [],
                "pull_requests": [],
                "issues": [],
            }

    # --- Fill commits ---
    contributor_stats: dict[str, dict] = defaultdict(lambda: {
        "login": "",
        "avatar_url": None,
        "total_commits": 0,
        "commits_by_type": defaultdict(int),
        "total_additions": 0,
        "total_deletions": 0,
        "significant_commits": 0,
        "weighted_score": 0.0,
        "prs_opened": 0,
        "prs_merged": 0,
        "issues_opened": 0,
    })

    for commit in commits:
        if not commit.authored_at:
            continue

        day_str = commit.authored_at.date().__str__()
        if day_str not in daily:
            continue

        contrib_info = contributor_cache.get(commit.contributor_id, {}) if commit.contributor_id else {}
        login = contrib_info.get("login") or commit.author_name or "unknown"
        avatar = contrib_info.get("avatar_url")

        commit_type = commit.commit_type or "chore"
        additions = commit.additions or 0
        deletions = commit.deletions or 0

        daily[day_str]["commit_count"] += 1
        daily[day_str]["additions"] += additions
        daily[day_str]["deletions"] += deletions
        daily[day_str]["commits"].append({
            "sha": commit.sha,
            "short_sha": commit.sha[:7],
            "message": commit.message.split("\n")[0][:120],
            "commit_type": commit_type,
            "author_login": login,
            "author_avatar": avatar,
            "additions": additions,
            "deletions": deletions,
            "files_changed": commit.files_changed or 0,
        })

        # Contributor stats
        cs = contributor_stats[login]
        cs["login"] = login
        cs["avatar_url"] = avatar
        cs["total_commits"] += 1
        cs["commits_by_type"][commit_type] += 1
        cs["total_additions"] += additions
        cs["total_deletions"] += deletions

        if additions >= significant_min_lines:
            cs["significant_commits"] += 1

        weight = commit_weights.get(commit_type, 0.5)
        cs["weighted_score"] += additions * weight

    # --- Fill PRs ---
    for pr in prs:
        pr_date = pr.pr_created_at
        if not pr_date:
            continue
        day_str = pr_date.date().__str__()
        if day_str not in daily:
            continue

        daily[day_str]["pr_count"] += 1
        daily[day_str]["pull_requests"].append({
            "number": pr.number,
            "title": pr.title[:120],
            "state": pr.state,
            "author_login": pr.author_login or "unknown",
            "author_avatar": pr.author_avatar,
            "created_at": pr.pr_created_at.isoformat() if pr.pr_created_at else None,
            "merged_at": pr.pr_merged_at.isoformat() if pr.pr_merged_at else None,
        })

        login = pr.author_login or "unknown"
        if login in contributor_stats:
            contributor_stats[login]["prs_opened"] += 1
            if pr.state == "merged":
                contributor_stats[login]["prs_merged"] += 1

    # --- Fill Issues ---
    for issue in issues:
        issue_date = issue.issue_created_at
        if not issue_date:
            continue
        day_str = issue_date.date().__str__()
        if day_str not in daily:
            continue

        daily[day_str]["issue_count"] += 1
        daily[day_str]["issues"].append({
            "number": issue.number,
            "title": issue.title[:120],
            "state": issue.state,
            "author_login": issue.author_login or "unknown",
            "author_avatar": issue.author_avatar,
            "created_at": issue.issue_created_at.isoformat() if issue.issue_created_at else None,
            "closed_at": issue.issue_closed_at.isoformat() if issue.issue_closed_at else None,
        })

        login = issue.author_login or "unknown"
        if login in contributor_stats:
            contributor_stats[login]["issues_opened"] += 1

    # --- Build contributor ranking ---
    contributors_list = []
    for login, cs in contributor_stats.items():
        commits_by_type = dict(cs["commits_by_type"])
        dqi = _calc_dqi(
            commits_by_type=commits_by_type,
            total_commits=cs["total_commits"],
            total_additions=cs["total_additions"],
            significant_commits=cs["significant_commits"],
        )
        contributors_list.append({
            "login": login,
            "avatar_url": cs["avatar_url"],
            "total_commits": cs["total_commits"],
            "commits_by_type": commits_by_type,
            "total_additions": cs["total_additions"],
            "total_deletions": cs["total_deletions"],
            "significant_commits": cs["significant_commits"],
            "weighted_score": round(cs["weighted_score"], 1),
            "quality_index": dqi,
            "prs_opened": cs["prs_opened"],
            "prs_merged": cs["prs_merged"],
            "issues_opened": cs["issues_opened"],
        })

    # Sort by DQI desc, take top 5 for ranking but return all
    contributors_list.sort(key=lambda x: x["quality_index"], reverse=True)

    # --- Summary ---
    total_commits = sum(d["commit_count"] for d in daily.values())
    total_additions = sum(d["additions"] for d in daily.values())
    active_days = sum(1 for d in daily.values() if d["commit_count"] > 0)

    return {
        "period_info": {
            "preset": "all" if is_all_time else str(sprint_days if days else default_sprint_days),
            "start_date": str(actual_since.date() if commits else since_dt.date()),
            "end_date": str(actual_until.date() if commits else until_dt.date()),
            "total_commits": len(commits),
            "limited": limited,
            "limit": commit_limit if limited else None,
        },
        "sprint": {
            "duration_days": sprint_days if not is_all_time else None,
            "start_date": str(actual_since.date() if commits else since_dt.date()),
            "end_date": str(actual_until.date() if commits else until_dt.date()),
        },
        "daily_stats": list(daily.values()),
        "contributors": contributors_list,
        "summary": {
            "total_commits": total_commits,
            "total_additions": total_additions,
            "active_days": active_days,
            "unique_contributors": len(contributors_list),
            "total_prs": len(prs),
            "total_issues": len(issues),
        },
    }


@router.get("/commit/{sha}/details")
def get_commit_details(
    sha: str,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> dict[str, Any]:
    commit_repo = CommitRepository(db)
    commit = commit_repo.get_by_sha(sha)
    if not commit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Commit not found")

    commit_file_repo = CommitFileRepository(db)
    files = commit_file_repo.get_by_commit(commit.id)

    contributor_repo = ContributorRepository(db)
    contrib = None
    if commit.contributor_id:
        contrib = contributor_repo.get_by_id(commit.contributor_id)

    return {
        "sha": commit.sha,
        "short_sha": commit.sha[:7],
        "message": commit.message,
        "commit_type": commit.commit_type,
        "is_conventional": commit.is_conventional,
        "is_merge_commit": commit.is_merge_commit,
        "is_pr_commit": commit.is_pr_commit,
        "is_revert_commit": commit.is_revert_commit,
        "is_breaking_change": commit.is_breaking_change,
        "authored_at": commit.authored_at.isoformat() if commit.authored_at else None,
        "author_name": commit.author_name,
        "author_email": commit.author_email,
        "author_login": contrib.login if contrib else None,
        "author_avatar": contrib.profile_url if contrib else None,
        "additions": commit.additions or 0,
        "deletions": commit.deletions or 0,
        "changes": commit.changes or 0,
        "files_changed": commit.files_changed or 0,
        "files": [
            {
                "file_path": f.file_path,
                "additions": f.additions or 0,
                "deletions": f.deletions or 0,
                "language": f.language,
                "patch": f.patch,
            }
            for f in files
        ],
    }


@router.get("/team/{team_id}/contributor/{contributor_login}/commits")
def get_contributor_commits(
    team_id: int,
    contributor_login: str,
    days: int | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Получить список коммитов конкретного разработчика с оценкой каждого.

    Args:
        team_id: ID команды
        contributor_login: GitHub login разработчика
        days: Количество дней для анализа (опционально, по умолчанию из конфига спринта)
        limit: Максимальное количество коммитов
        offset: Смещение для пагинации
        db: Database session
        current_user: Текущий пользователь

    Returns:
        dict с полями:
            - contributor: информация о разработчике
            - commits: список коммитов с quality_score
            - total: общее количество коммитов
            - pagination: параметры пагинации
    """
    # Проверяем команду
    team_repo = TeamRepository(db)
    team = team_repo.get_by_id(team_id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )

    # Ищем контрибьютора по login
    contributor_repo = ContributorRepository(db)
    contributors = contributor_repo.get_by_login(contributor_login, vcs_provider="github")

    if not contributors:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contributor {contributor_login} not found"
        )

    contributor = contributors[0]  # Берем первого (обычно один)

    # Получаем конфигурацию
    workflow = _get_workflow_config(team)
    metrics = _get_metrics_config(team)

    # Определяем период
    sprint_days = days or workflow.get("sprint", {}).get("duration_days", DEFAULT_SPRINT_DAYS)
    until_dt = datetime.now(timezone.utc)
    since_dt = until_dt - timedelta(days=sprint_days)

    # Получаем коммиты
    commit_repo = CommitRepository(db)
    commits = commit_repo.get_by_contributor_and_team(
        contributor_id=contributor.id,
        team_id=team_id,
        since=since_dt,
        until=until_dt,
        limit=limit,
        offset=offset
    )

    # Получаем параметры для вычисления качества
    commit_weights = metrics.get("commit_weights", {
        "feat": 3.0,
        "fix": 2.0,
        "refactor": 2.0,
        "perf": 2.5,
        "test": 1.5,
        "docs": 1.0,
        "style": 0.5,
        "chore": 0.5,
        "other": 0.5,
    })
    significant_min_lines = metrics.get("significant_commit_min_lines", DEFAULT_SIGNIFICANT_MIN_LINES)

    # Формируем список коммитов с оценкой качества
    commits_list = []
    for commit in commits:
        additions = commit.additions or 0
        deletions = commit.deletions or 0
        commit_type = commit.commit_type or "other"
        weight = commit_weights.get(commit_type, 0.5)

        # Вычисляем quality_score
        # Формула: (additions * weight) / 10, нормализованный к 0-100
        raw_score = additions * weight
        quality_score = min(int(raw_score / 10), 100)

        # Альтернативная формула для более детальной оценки:
        # Учитываем типы коммитов
        if commit_type in FEATURE_TYPES:
            quality_multiplier = 1.2
        elif commit_type in BUG_TYPES:
            quality_multiplier = 1.0
        else:
            quality_multiplier = 0.8

        # Финальный score с учетом множителя
        quality_score = min(int(raw_score / 10 * quality_multiplier), 100)

        commits_list.append({
            "sha": commit.sha,
            "short_sha": commit.sha[:7],
            "message": commit.message.split("\n")[0][:120] if commit.message else "",
            "commit_type": commit_type,
            "quality_score": quality_score,
            "additions": additions,
            "deletions": deletions,
            "changes": commit.changes or (additions + deletions),
            "files_changed": commit.files_changed or 0,
            "authored_at": commit.authored_at.isoformat() if commit.authored_at else None,
            "is_significant": additions >= significant_min_lines,
            "is_conventional": commit.is_conventional or False,
            "is_breaking_change": commit.is_breaking_change or False,
            "is_merge_commit": commit.is_merge_commit or False,
            "is_revert_commit": commit.is_revert_commit or False,
        })

    return {
        "contributor": {
            "login": contributor.login,
            "display_name": contributor.display_name,
            "avatar_url": contributor.profile_url,
            "email": contributor.email,
        },
        "commits": commits_list,
        "total": len(commits_list),
        "period": {
            "days": sprint_days,
            "since": since_dt.isoformat(),
            "until": until_dt.isoformat(),
        },
        "pagination": {
            "limit": limit,
            "offset": offset,
        },
    }
