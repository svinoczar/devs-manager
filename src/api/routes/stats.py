import json
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.api.dependencies import get_db, get_current_user
from src.adapters.db.models.user import UserModel
from src.adapters.db.repositories.team_repo import TeamRepository
from src.adapters.db.repositories.commit_repo import CommitRepository
from src.adapters.db.repositories.commit_file_repo import CommitFileRepository
from src.adapters.db.repositories.contributor_repo import ContributorRepository
from src.adapters.db.repositories.pull_request_repo import PullRequestRepository
from src.adapters.db.repositories.issue_repo import IssueRepository

router = APIRouter(prefix="/stats", tags=["stats"])

FUNCTIONAL_TYPES = {"feat", "fix", "perf", "refactor"}
FEATURE_TYPES = {"feat", "perf", "refactor"}
BUG_TYPES = {"fix"}

DEFAULT_SPRINT_DAYS = 14
DEFAULT_SIGNIFICANT_MIN_LINES = 5

DOC_FILE_PATTERNS = ['.md', 'README', 'CHANGELOG', 'CONTRIBUTING', 'LICENSE', '.rst', '.adoc']
TEST_FILE_PATTERNS = ['.test.', '.spec.', 'test_', '_test.', '__tests__/', '/tests/', '/test/', 'spec/']

# Comment line prefixes per language for documentation ratio calculation
COMMENT_PREFIXES_BY_LANG: dict[str, list[str]] = {
    "Python":     ["#", '"""', "'''", "##"],
    "JavaScript": ["//", "/*", "*/", " *", "/**"],
    "TypeScript": ["//", "/*", "*/", " *", "/**"],
    "Java":       ["//", "/*", "*/", " *", "/**"],
    "Go":         ["//", "/*", "*/", " *"],
    "Rust":       ["//", "///", "/*", "*/", " *"],
    "C":          ["//", "/*", "*/", " *"],
    "C++":        ["//", "/*", "*/", " *"],
    "Ruby":       ["#"],
    "Shell":      ["#"],
    "SQL":        ["--", "/*", "*/"],
    "HTML":       ["<!--", "-->", "!--"],
    "CSS":        ["/*", "*/", " *"],
    "SCSS":       ["//", "/*", "*/", " *"],
    "PHP":        ["//", "#", "/*", "*/", " *"],
    "Swift":      ["//", "/*", "*/", " *", "///"],
    "Kotlin":     ["//", "/*", "*/", " *"],
    "Scala":      ["//", "/*", "*/", " *"],
    "R":          ["#"],
    "Markdown":   [],  # Markdown files are themselves documentation — count all lines
}

# Default prefixes for unknown languages
DEFAULT_COMMENT_PREFIXES = ["//", "#", "/*", "*/", " *", '"""', "'''", "--", "<!--"]


def _is_doc_file(file_path: str) -> bool:
    file_path_lower = file_path.lower()
    return any(pattern.lower() in file_path_lower for pattern in DOC_FILE_PATTERNS)


def _is_test_file(file_path: str) -> bool:
    file_path_lower = file_path.lower()
    return any(pattern.lower() in file_path_lower for pattern in TEST_FILE_PATTERNS)


def _is_comment_line(line: str, language: str | None) -> bool:
    """
    Check if a source code line (stripped of leading '+') is a comment or docstring.
    Multi-line comment markers (/* */) and docstring openers count as comment lines.
    """
    stripped = line.strip()
    if not stripped:
        return False

    # Markdown/doc files — every line counts as documentation
    if language == "Markdown":
        return True

    prefixes = COMMENT_PREFIXES_BY_LANG.get(language or "", DEFAULT_COMMENT_PREFIXES)
    return any(stripped.startswith(p) for p in prefixes)


def _extract_added_lines(patch: str) -> set[str]:
    """Extract content of added lines from a git diff patch."""
    lines = set()
    for raw in (patch or "").split("\n"):
        if raw.startswith("+") and not raw.startswith("+++"):
            content = raw[1:].strip()
            if content:
                lines.add(content)
    return lines


def _extract_deleted_lines(patch: str) -> set[str]:
    """Extract content of deleted/replaced lines from a git diff patch."""
    lines = set()
    for raw in (patch or "").split("\n"):
        if raw.startswith("-") and not raw.startswith("---"):
            content = raw[1:].strip()
            if content:
                lines.add(content)
    return lines


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


def _get_analysis_config(team) -> dict:
    try:
        return json.loads(team.analysis_config) if team.analysis_config else {}
    except Exception:
        return {}


def _calc_dqi(
    commits_by_type: dict[str, int],
    total_commits: int,
    total_additions: int,
    significant_commits: int,
    reversion_ratio: float = 0.0,
    breaking_ratio: float = 0.0,
    doc_ratio: float = 0.0,
    test_ratio: float = 0.0,
    sprint_stability: float = 100.0,
) -> float:
    """
    Developer Quality Index (0–100).

    Weights:
    - 25% — functional commits (feat/perf/refactor)
    - 10% — bug fixes
    - 15% — significant changes
    - 15% — reversion stability
    - 15% — code stability (sprint)
    - 5%  — no breaking changes
    - 7%  — test coverage
    - 5%  — documentation
    - 3%  — base bonus
    """
    if total_commits == 0:
        return 0.0

    feat_count = sum(commits_by_type.get(t, 0) for t in FEATURE_TYPES)
    fix_count = commits_by_type.get("fix", 0)

    functional_ratio = feat_count / total_commits

    denominator = feat_count + fix_count
    bug_rate = fix_count / denominator if denominator > 0 else 0.0

    significant_ratio = significant_commits / total_commits

    reversion_stability = max(0.0, 1.0 - reversion_ratio / 100)
    breaking_stability = max(0.0, 1.0 - breaking_ratio / 100)

    # Code stability: sprint_stability is already 0-100
    code_stability = sprint_stability / 100.0

    # Documentation (normalise: 15% doc_ratio = 100%)
    doc_score = min(doc_ratio / 15, 1.0)

    # Test coverage (normalise: 25% test_ratio = 100%)
    test_score = min(test_ratio / 25, 1.0)

    dqi = (
        functional_ratio  * 25
        + bug_rate         * 10
        + significant_ratio * 15
        + reversion_stability * 15
        + code_stability   * 15
        + breaking_stability * 5
        + test_score       * 7
        + doc_score        * 5
        + 3  # base bonus
    )

    return round(min(dqi, 100.0), 1)


def _compute_stability_metrics(
    contributor_commits: list,
    all_commits_sorted: list,
    files_by_commit: dict[int, list],
    sprint_days: int,
) -> dict:
    """
    Compute per-contributor code stability.

    Approach:
    - For each line added by a contributor's commit at time T, check whether
      that same line content appears in the deleted-lines of any later commit
      (by any author) within the same sprint.
    - weekly_stability:  % of added lines NOT churned within 7 days of addition
    - sprint_stability:  % of added lines NOT churned before sprint end

    Returns dict with keys: weekly_stability, sprint_stability (both 0-100).
    """
    if not contributor_commits or not all_commits_sorted:
        return {"weekly_stability": 100.0, "sprint_stability": 100.0}

    # Build per-file timeline of deletions: file_path → list of (date, deleted_set)
    file_deletions: dict[str, list[tuple]] = defaultdict(list)
    for commit in all_commits_sorted:
        for f in files_by_commit.get(commit.id, []):
            if f.patch:
                deleted = _extract_deleted_lines(f.patch)
                if deleted:
                    file_deletions[f.file_path].append((commit.authored_at, deleted))

    total_added = 0
    churned_week = 0
    churned_sprint = 0

    for commit in contributor_commits:
        commit_date = commit.authored_at
        if not commit_date:
            continue

        for f in files_by_commit.get(commit.id, []):
            if not f.patch:
                continue
            added = _extract_added_lines(f.patch)
            if not added:
                continue

            week_deleted: set[str] = set()
            sprint_deleted: set[str] = set()

            for del_date, deleted_set in file_deletions.get(f.file_path, []):
                if del_date is None or del_date <= commit_date:
                    continue  # Only look at future changes
                days_later = (del_date - commit_date).total_seconds() / 86400.0
                intersect = added & deleted_set
                if not intersect:
                    continue
                if days_later <= 7:
                    week_deleted |= intersect
                sprint_deleted |= intersect

            n = len(added)
            total_added += n
            churned_week += len(week_deleted)
            churned_sprint += len(sprint_deleted)

    if total_added == 0:
        return {"weekly_stability": 100.0, "sprint_stability": 100.0}

    weekly_stability = round((total_added - churned_week) / total_added * 100, 1)
    sprint_stability = round((total_added - churned_sprint) / total_added * 100, 1)
    return {"weekly_stability": weekly_stability, "sprint_stability": sprint_stability}


def _compute_comment_ratio(
    contributor_commits: list,
    files_by_commit: dict[int, list],
) -> float:
    """
    Compute percentage of added code lines that are comments or documentation.

    Counts:
    - Single-line comments (// # -- etc.)
    - Multi-line comment markers (/* */ etc.)
    - Docstring openers/closers (\"\"\" ''' etc.)
    - Entire markdown/rst files

    Returns comment_ratio as percentage (0-100).
    """
    total_added = 0
    comment_added = 0

    for commit in contributor_commits:
        for f in files_by_commit.get(commit.id, []):
            if not f.patch:
                continue
            lang = f.language
            for raw in f.patch.split("\n"):
                if not raw.startswith("+") or raw.startswith("+++"):
                    continue
                total_added += 1
                content = raw[1:]  # strip leading +
                if _is_comment_line(content, lang):
                    comment_added += 1

    if total_added == 0:
        return 0.0
    return round(comment_added / total_added * 100, 1)


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

    workflow = _get_workflow_config(team)
    metrics = _get_metrics_config(team)
    analysis = _get_analysis_config(team)

    special_commits = analysis.get("special_commits", {})
    bot_logins = set(special_commits.get("bot_logins", []))

    sprint_cfg = workflow.get("sprint", {})
    default_sprint_days = sprint_cfg.get("duration_days", DEFAULT_SPRINT_DAYS)

    is_all_time = False
    commit_limit = None

    if days == "all":
        is_all_time = True
        commit_limit = 5000
        sprint_days = 9999
    else:
        sprint_days = int(days) if days else default_sprint_days

    significant_min_lines = metrics.get("significant_commit_min_lines", DEFAULT_SIGNIFICANT_MIN_LINES)
    commit_weights: dict[str, float] = metrics.get("commit_weights", {
        "feat": 3.0, "fix": 2.0, "perf": 2.5, "refactor": 2.0,
        "test": 1.5, "docs": 0.5, "style": 0.5, "chore": 0.5, "revert": 0.0,
    })

    until_dt = datetime.now(timezone.utc)

    if is_all_time:
        since_dt = datetime(2000, 1, 1, tzinfo=timezone.utc)
    else:
        since_dt = until_dt - timedelta(days=sprint_days)

    commit_repo = CommitRepository(db)
    pr_repo = PullRequestRepository(db)
    issue_repo = IssueRepository(db)
    contributor_repo = ContributorRepository(db)

    commits = commit_repo.get_by_team_date_range(team_id, since_dt, until_dt)

    limited = False
    if commit_limit and len(commits) > commit_limit:
        commits = sorted(commits, key=lambda c: c.authored_at or datetime.min, reverse=True)[:commit_limit]
        limited = True

    if commits:
        actual_since = min(c.authored_at for c in commits if c.authored_at)
        actual_until = max(c.authored_at for c in commits if c.authored_at)
    else:
        actual_since = since_dt
        actual_until = until_dt

    prs = pr_repo.get_by_team_date_range(team_id, actual_since, actual_until)
    issues = issue_repo.get_by_team_date_range(team_id, actual_since, actual_until)

    contributor_cache: dict[int, dict] = {}
    for c in contributor_repo.get_all(limit=10000):
        contributor_cache[c.id] = {
            "login": c.login or c.external_id,
            "avatar_url": c.profile_url,
        }

    # --- Load all commit files upfront (for stability + comment metrics) ---
    commit_file_repo = CommitFileRepository(db)
    commit_ids = [c.id for c in commits]
    files_by_commit: dict[int, list] = defaultdict(list)

    if commit_ids:
        for i in range(0, len(commit_ids), 1000):
            batch_ids = commit_ids[i:i + 1000]
            files = commit_file_repo.get_by_commit_ids(batch_ids)
            for f in files:
                files_by_commit[f.commit_id].append(f)

    # Sorted commits for stability computation
    all_commits_sorted = sorted(
        [c for c in commits if c.authored_at],
        key=lambda c: c.authored_at,
    )

    # --- Build daily buckets ---
    daily: dict[str, dict] = {}

    if is_all_time:
        if commits:
            actual_days = (actual_until.date() - actual_since.date()).days + 1
            for i in range(min(actual_days, 365)):
                day = (actual_since + timedelta(days=i)).date()
                daily[str(day)] = {
                    "date": str(day), "commit_count": 0, "additions": 0,
                    "deletions": 0, "pr_count": 0, "issue_count": 0,
                    "commits": [], "pull_requests": [], "issues": [],
                }
    else:
        for i in range(sprint_days):
            day = (since_dt + timedelta(days=i)).date()
            daily[str(day)] = {
                "date": str(day), "commit_count": 0, "additions": 0,
                "deletions": 0, "pr_count": 0, "issue_count": 0,
                "commits": [], "pull_requests": [], "issues": [],
            }

    # --- Contributor stats accumulators ---
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
        "revert_commits": 0,
        "breaking_commits": 0,
        "doc_commits": 0,
        "test_commits": 0,
        "commits_with_docs": 0,
        "commits_with_tests": 0,
        # Per-contributor commit list (for stability + comment ratio)
        "_commits": [],
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

        if login in bot_logins:
            continue

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

        cs = contributor_stats[login]
        cs["login"] = login
        cs["avatar_url"] = avatar
        cs["total_commits"] += 1
        cs["commits_by_type"][commit_type] += 1
        cs["total_additions"] += additions
        cs["total_deletions"] += deletions
        cs["_commits"].append(commit)

        if additions >= significant_min_lines:
            cs["significant_commits"] += 1

        weight = commit_weights.get(commit_type, 0.5)
        cs["weighted_score"] += additions * weight

        if commit.is_revert_commit:
            cs["revert_commits"] += 1
        if commit.is_breaking_change:
            cs["breaking_commits"] += 1
        if commit_type == "docs":
            cs["doc_commits"] += 1
        if commit_type == "test":
            cs["test_commits"] += 1

    # --- Analyze commit files for doc/test file patterns ---
    for commit_id, commit_files in files_by_commit.items():
        commit = next((c for c in commits if c.id == commit_id), None)
        if not commit or not commit.contributor_id:
            continue

        contrib_info = contributor_cache.get(commit.contributor_id, {})
        login = contrib_info.get("login") or commit.author_name or "unknown"

        if login in bot_logins or login not in contributor_stats:
            continue

        has_doc_files = any(_is_doc_file(f.file_path) for f in commit_files)
        has_test_files = any(_is_test_file(f.file_path) for f in commit_files)

        if has_doc_files:
            contributor_stats[login]["commits_with_docs"] += 1
        if has_test_files:
            contributor_stats[login]["commits_with_tests"] += 1

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
        total = cs["total_commits"]

        reversion_ratio = (cs["revert_commits"] / total * 100) if total > 0 else 0
        breaking_ratio = (cs["breaking_commits"] / total * 100) if total > 0 else 0

        doc_ratio = ((cs["doc_commits"] + cs["commits_with_docs"]) / total * 100) if total > 0 else 0

        functional_commits = (
            sum(cs["commits_by_type"].get(t, 0) for t in FEATURE_TYPES)
            + cs["commits_by_type"].get("fix", 0)
        )
        test_ratio = (
            (cs["test_commits"] + cs["commits_with_tests"]) / functional_commits * 100
            if functional_commits > 0 else 0
        )

        # Code stability metrics
        contributor_commits_sorted = sorted(
            [c for c in cs["_commits"] if c.authored_at],
            key=lambda c: c.authored_at,
        )
        stability = _compute_stability_metrics(
            contributor_commits=contributor_commits_sorted,
            all_commits_sorted=all_commits_sorted,
            files_by_commit=files_by_commit,
            sprint_days=sprint_days,
        )

        # Comment/documentation ratio (% of added code lines that are comments)
        comment_ratio = _compute_comment_ratio(contributor_commits_sorted, files_by_commit)

        dqi = _calc_dqi(
            commits_by_type=commits_by_type,
            total_commits=total,
            total_additions=cs["total_additions"],
            significant_commits=cs["significant_commits"],
            reversion_ratio=reversion_ratio,
            breaking_ratio=breaking_ratio,
            doc_ratio=doc_ratio,
            test_ratio=test_ratio,
            sprint_stability=stability["sprint_stability"],
        )

        contributors_list.append({
            "login": login,
            "avatar_url": cs["avatar_url"],
            "total_commits": total,
            "commits_by_type": commits_by_type,
            "total_additions": cs["total_additions"],
            "total_deletions": cs["total_deletions"],
            "significant_commits": cs["significant_commits"],
            "weighted_score": round(cs["weighted_score"], 1),
            "quality_index": dqi,
            "prs_opened": cs["prs_opened"],
            "prs_merged": cs["prs_merged"],
            "issues_opened": cs["issues_opened"],
            "revert_commits": cs["revert_commits"],
            "breaking_commits": cs["breaking_commits"],
            "doc_commits": cs["doc_commits"],
            "test_commits": cs["test_commits"],
            "reversion_ratio": round(reversion_ratio, 1),
            "breaking_ratio": round(breaking_ratio, 1),
            "doc_ratio": round(doc_ratio, 1),
            "test_ratio": round(test_ratio, 1),
            # New metrics
            "weekly_stability": stability["weekly_stability"],
            "sprint_stability": stability["sprint_stability"],
            "comment_ratio": comment_ratio,
        })

    contributors_list.sort(key=lambda x: x["quality_index"], reverse=True)

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
    days: int | str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Получить список коммитов конкретного разработчика с оценкой каждого.
    Поддерживает days=all для получения всех коммитов.
    """
    team_repo = TeamRepository(db)
    team = team_repo.get_by_id(team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    contributor_repo = ContributorRepository(db)
    contributors = contributor_repo.get_by_login(contributor_login, vcs_provider="github")

    if not contributors:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contributor {contributor_login} not found",
        )

    contributor = contributors[0]

    workflow = _get_workflow_config(team)
    metrics = _get_metrics_config(team)

    # Handle days=all — fetch from the beginning of time
    is_all_time = days == "all"
    until_dt = datetime.now(timezone.utc)

    if is_all_time:
        since_dt = datetime(2000, 1, 1, tzinfo=timezone.utc)
        sprint_days = 9999
    else:
        sprint_days = int(days) if days else workflow.get("sprint", {}).get("duration_days", DEFAULT_SPRINT_DAYS)
        since_dt = until_dt - timedelta(days=sprint_days)

    commit_repo = CommitRepository(db)
    commits = commit_repo.get_by_contributor_and_team(
        contributor_id=contributor.id,
        team_id=team_id,
        since=since_dt,
        until=until_dt,
        limit=limit,
        offset=offset,
    )

    commit_weights = metrics.get("commit_weights", {
        "feat": 3.0, "fix": 2.0, "refactor": 2.0, "perf": 2.5,
        "test": 1.5, "docs": 1.0, "style": 0.5, "chore": 0.5, "other": 0.5,
    })
    significant_min_lines = metrics.get("significant_commit_min_lines", DEFAULT_SIGNIFICANT_MIN_LINES)

    commits_list = []
    for commit in commits:
        additions = commit.additions or 0
        deletions = commit.deletions or 0
        commit_type = commit.commit_type or "other"
        weight = commit_weights.get(commit_type, 0.5)

        raw_score = additions * weight

        if commit_type in FEATURE_TYPES:
            quality_multiplier = 1.2
        elif commit_type in BUG_TYPES:
            quality_multiplier = 1.0
        else:
            quality_multiplier = 0.8

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
            "days": "all" if is_all_time else sprint_days,
            "since": since_dt.isoformat(),
            "until": until_dt.isoformat(),
        },
        "pagination": {
            "limit": limit,
            "offset": offset,
        },
    }


@router.get("/team/{team_id}/file-stats")
def get_file_stats(
    team_id: int,
    days: int | str | None = None,
    top_n: int = 20,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> dict[str, Any]:
    """
    File-level analytics for the team:
    - top_files: most frequently changed files with per-contributor breakdown and daily history
    - contributor_file_matrix: contributor → {file_path: change_count}

    Used to render "File Hotspots" and "Collaboration Matrix" charts.
    """
    team_repo = TeamRepository(db)
    team = team_repo.get_by_id(team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    workflow = _get_workflow_config(team)
    analysis = _get_analysis_config(team)
    special_commits = analysis.get("special_commits", {})
    bot_logins = set(special_commits.get("bot_logins", []))

    sprint_cfg = workflow.get("sprint", {})
    default_sprint_days = sprint_cfg.get("duration_days", DEFAULT_SPRINT_DAYS)

    is_all_time = days == "all"
    until_dt = datetime.now(timezone.utc)

    if is_all_time:
        since_dt = datetime(2000, 1, 1, tzinfo=timezone.utc)
        sprint_days = 9999
    else:
        sprint_days = int(days) if days else default_sprint_days
        since_dt = until_dt - timedelta(days=sprint_days)

    commit_repo = CommitRepository(db)
    commits = commit_repo.get_by_team_date_range(team_id, since_dt, until_dt)

    if not commits:
        return {
            "top_files": [],
            "contributor_file_matrix": {},
            "period": {"days": "all" if is_all_time else sprint_days},
        }

    contributor_repo = ContributorRepository(db)
    contributor_cache: dict[int, str] = {}
    for c in contributor_repo.get_all(limit=10000):
        contributor_cache[c.id] = c.login or c.external_id or "unknown"

    # Build commit → login map
    commit_login: dict[int, str] = {}
    for commit in commits:
        if commit.contributor_id:
            login = contributor_cache.get(commit.contributor_id, commit.author_name or "unknown")
        else:
            login = commit.author_name or "unknown"
        if login not in bot_logins:
            commit_login[commit.id] = login

    commit_file_repo = CommitFileRepository(db)
    commit_ids = [c.id for c in commits if c.id in commit_login]

    # file_path → {changes, additions, deletions, contributors: {login: count}, daily: {date: {add, del}}}
    file_agg: dict[str, dict] = defaultdict(lambda: {
        "language": None,
        "change_count": 0,
        "total_additions": 0,
        "total_deletions": 0,
        "contributors": defaultdict(int),
        "daily": defaultdict(lambda: {"additions": 0, "deletions": 0}),
    })

    contributor_file_matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for i in range(0, len(commit_ids), 1000):
        batch_ids = commit_ids[i:i + 1000]
        files = commit_file_repo.get_by_commit_ids(batch_ids)
        for f in files:
            login = commit_login.get(f.commit_id)
            if not login:
                continue
            fp = f.file_path
            agg = file_agg[fp]
            if agg["language"] is None and f.language:
                agg["language"] = f.language
            agg["change_count"] += 1
            agg["total_additions"] += f.additions or 0
            agg["total_deletions"] += f.deletions or 0
            agg["contributors"][login] += 1
            contributor_file_matrix[login][fp] += 1

            # Find commit date for daily breakdown
            commit = next((c for c in commits if c.id == f.commit_id), None)
            if commit and commit.authored_at:
                day_str = str(commit.authored_at.date())
                agg["daily"][day_str]["additions"] += f.additions or 0
                agg["daily"][day_str]["deletions"] += f.deletions or 0

    # Sort by change_count and take top_n
    top_files_sorted = sorted(
        file_agg.items(), key=lambda x: x[1]["change_count"], reverse=True
    )[:top_n]

    top_files = []
    for fp, agg in top_files_sorted:
        contributors_list = [
            {"login": login, "change_count": cnt}
            for login, cnt in sorted(agg["contributors"].items(), key=lambda x: -x[1])
        ]
        daily_list = [
            {"date": d, "additions": v["additions"], "deletions": v["deletions"]}
            for d, v in sorted(agg["daily"].items())
        ]
        top_files.append({
            "file_path": fp,
            "language": agg["language"],
            "change_count": agg["change_count"],
            "total_additions": agg["total_additions"],
            "total_deletions": agg["total_deletions"],
            "contributors": contributors_list,
            "daily_changes": daily_list,
        })

    # Slim down contributor_file_matrix to only top_n files
    top_file_paths = {fp for fp, _ in top_files_sorted}
    matrix_slim: dict[str, dict[str, int]] = {
        login: {fp: cnt for fp, cnt in files.items() if fp in top_file_paths}
        for login, files in contributor_file_matrix.items()
    }

    return {
        "top_files": top_files,
        "contributor_file_matrix": matrix_slim,
        "period": {"days": "all" if is_all_time else sprint_days},
    }
