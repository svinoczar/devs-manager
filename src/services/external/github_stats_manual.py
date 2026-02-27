from datetime import datetime
import os
import time
import requests
import json

from dotenv import load_dotenv
from src.util.mapper import single_commit_json_to_dto


load_dotenv()


def get_commits_list(
    owner,
    repo,
    token=None,
    since: datetime | None = None,
    max_commits: int | None = None,
):
    if token is None:
        token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN not found")

    url = f"https://api.github.com/repos/{owner}/{repo}/commits"
    headers = {
        "Authorization": f"token {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "Accept": "application/vnd.github.v3+json",
    }

    all_commits = []
    page = 1
    per_page = 100

    while True:
        params = {
            "page": page,
            "per_page": per_page,
        }

        if since:
            params["since"] = since.isoformat()

        for attempt in range(3):
            try:
                response = requests.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=60,
                )
                response.raise_for_status()
                break
            except requests.RequestException as e:
                if attempt == 2:
                    raise
                time.sleep(5)

        commits = response.json()
        if not commits:
            break

        for commit in commits:
            all_commits.append(commit)
            if max_commits and len(all_commits) >= max_commits:
                return all_commits

        print(f"Retrieved page {page}: {len(commits)} commits")

        if "next" in response.links:
            page += 1
        else:
            break

    print(f"Total commits retrieved: {len(all_commits)}")
    return all_commits



def get_commit_count(owner: str, repo: str, token: str | None = None) -> int:
    """
    Быстро получает количество коммитов в репозитории без полной пагинации.

    Args:
        owner: Владелец репозитория
        repo: Название репозитория
        token: GitHub токен (опционально, по умолчанию из env)

    Returns:
        Количество коммитов
    """
    if token is None:
        token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN not found")

    url = f"https://api.github.com/repos/{owner}/{repo}/commits"
    headers = {
        "Authorization": f"token {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "Accept": "application/vnd.github.v3+json",
    }

    # Запрашиваем только 1 коммит чтобы получить Link header
    params = {"per_page": 1, "page": 1}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()

        # Пытаемся извлечь total count из Link header
        link_header = response.headers.get("Link", "")
        if "page=" in link_header:
            # Парсим последнюю страницу из Link header
            # Формат: <...page=N&per_page=1>; rel="last"
            import re
            match = re.search(r'page=(\d+)>; rel="last"', link_header)
            if match:
                # Количество коммитов = последняя страница * per_page
                # Но так как per_page=1, это и есть количество коммитов
                return int(match.group(1))

        # Fallback: если Link header не помог, считаем напрямую
        # (это медленнее, но надёжнее)
        page = 1
        per_page = 100
        total = 0

        while page < 100:  # Лимит в 10000 коммитов (100 страниц * 100)
            params = {"per_page": per_page, "page": page}
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()

            commits = response.json()
            if not commits:
                break

            total += len(commits)

            if len(commits) < per_page:
                # Последняя страница
                break

            page += 1

        return total

    except requests.RequestException as e:
        raise RuntimeError(f"Failed to get commit count: {e}")


def get_commit(owner, repo, ref, token=None):
    if token is None:
        token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN not found in .env file")

    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{ref}"
    headers = {
        "Authorization": f"token {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "Accept": "application/vnd.github.v3+json",
    }

    response = requests.get(url, headers=headers, timeout=60)
    response.raise_for_status()
    return response.json()


def compare_commit(owner, repo, basehead, token=None):
    if token is None:
        token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN not found in .env file")

    url = f"https://api.github.com/repos/{owner}/{repo}/compare/{basehead}"
    headers = {
        "Authorization": f"token {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "Accept": "application/vnd.github.v3+json",
    }

    response = requests.get(url, headers=headers, timeout=60)
    response.raise_for_status()
    return json.loads(response.json())


def get_contributors(owner, repo, token=None):

    if token is None:
        token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN not found in .env file")

    url = f"https://api.github.com/repos/{owner}/{repo}/contributors"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "Accept": "application/vnd.github+json"
    }

    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


def get_pull_requests(owner, repo, token=None, since: datetime | None = None, until: datetime | None = None):
    if token is None:
        token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN not found in .env file")

    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    headers = {
        "Authorization": f"token {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "Accept": "application/vnd.github.v3+json",
    }

    all_prs = []
    page = 1

    while True:
        params = {"state": "all", "per_page": 100, "page": page}

        for attempt in range(3):
            try:
                response = requests.get(url, headers=headers, params=params, timeout=60)
                response.raise_for_status()
                break
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(5)

        prs = response.json()
        if not prs:
            break

        for pr in prs:
            created_at_str = pr.get("created_at")
            if created_at_str:
                pr_date = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                if since and pr_date < since:
                    return all_prs
                if until and pr_date > until:
                    continue
            all_prs.append(pr)

        if "next" in response.links:
            page += 1
        else:
            break

    return all_prs


def get_issues(owner, repo, token=None, since: datetime | None = None):
    if token is None:
        token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN not found in .env file")

    url = f"https://api.github.com/repos/{owner}/{repo}/issues"
    headers = {
        "Authorization": f"token {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "Accept": "application/vnd.github.v3+json",
    }

    all_issues = []
    page = 1

    while True:
        params = {"state": "all", "per_page": 100, "page": page}
        if since:
            params["since"] = since.isoformat()

        for attempt in range(3):
            try:
                response = requests.get(url, headers=headers, params=params, timeout=60)
                response.raise_for_status()
                break
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(5)

        issues = response.json()
        if not issues:
            break

        for issue in issues:
            # GitHub issues API returns PRs too — filter them out
            if "pull_request" not in issue:
                all_issues.append(issue)

        if "next" in response.links:
            page += 1
        else:
            break

    return all_issues



# Использование
# commits = get_commits_list("Nerds-International", "nerd-code-frontend")
# commit = get_commit("Nerds-International", "nerd-code-frontend", commits[0]["sha"])
# print(commit)
# dto = JSONToSingleCommitEntity(commit)
# print(dto)
# print(get_collaborators("Nerds-International", "nerd-code-frontend"))
# print('\n\n\n\n')
# print(json.dumps(commits))

# commits = get_commit('svinoczar', 'itmo', '2bf0de21d28e4ed24bb271c1d9e12ee7720c2cfe')
# print(str(commits).replace('\'', '"'))

# commits = get_commit('svinoczar', 'contribution-analyzer', 'main...dev')
# print(str(commits).replace('\'', '"'))
