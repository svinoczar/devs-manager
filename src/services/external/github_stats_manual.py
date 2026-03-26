from datetime import datetime
import os
import time
import requests
import json
import logging

from dotenv import load_dotenv
from src.util.mapper import single_commit_json_to_dto


load_dotenv()
logger = logging.getLogger(__name__)


def github_request_with_retry(url, headers, params=None, max_retries=5):
    """
    Выполняет GitHub API запрос с автоматическим retry при rate limit.

    Args:
        url: URL для запроса
        headers: HTTP заголовки
        params: Query параметры (опционально)
        max_retries: Максимальное количество попыток

    Returns:
        Response object

    Raises:
        requests.HTTPError: Если все попытки исчерпаны
    """
    logger.debug("[github_stats_manual:github_request_with_retry] Requesting %s (params=%s)", url, params)
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=60)

            # Проверяем rate limit
            if response.status_code == 403:
                # Проверяем заголовки rate limit
                remaining = response.headers.get('X-RateLimit-Remaining', '0')
                reset_time = response.headers.get('X-RateLimit-Reset', '0')

                if remaining == '0':
                    # Rate limit достигнут
                    reset_timestamp = int(reset_time)
                    current_time = int(time.time())
                    wait_seconds = max(reset_timestamp - current_time, 60)

                    logger.warning(
                        "[github_stats_manual:github_request_with_retry] ⚠ Rate limit exceeded. Waiting %ds until reset. Attempt %d/%d",
                        wait_seconds, attempt + 1, max_retries
                    )

                    if attempt < max_retries - 1:
                        time.sleep(wait_seconds)
                        continue
                    else:
                        response.raise_for_status()
                else:
                    # 403 по другой причине
                    response.raise_for_status()

            response.raise_for_status()
            logger.debug("[github_stats_manual:github_request_with_retry] ✓ Request successful (status=%d)", response.status_code)
            return response

        except requests.RequestException as e:
            if attempt == max_retries - 1:
                logger.error("[github_stats_manual:github_request_with_retry] ✗ Max retries exceeded: %s", e)
                raise

            # Exponential backoff для других ошибок
            wait_time = min(2 ** attempt * 5, 60)  # Max 60 секунд
            logger.warning("[github_stats_manual:github_request_with_retry] ⚠ Request failed: %s. Retrying in %ds (attempt %d/%d)...",
                         e, wait_time, attempt + 1, max_retries)
            time.sleep(wait_time)

    raise requests.HTTPError(f"Max retries ({max_retries}) exceeded")


def get_commits_list(
    owner,
    repo,
    token=None,
    since: datetime | None = None,
    max_commits: int | None = None,
):
    """
    Загружает все коммиты репозитория в память.

    DEPRECATED: Используйте get_commits_paginated() для более эффективной обработки.
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

        try:
            response = github_request_with_retry(url, headers, params)
        except requests.RequestException as e:
            logger.error(f"Failed to fetch commits page {page}: {e}")
            raise

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


def get_commits_count(
    owner: str,
    repo: str,
    token: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> int:
    """
    Быстро получает общее количество коммитов за период через GitHub API.
    Использует Link header для определения total count.

    Args:
        owner: Владелец репозитория
        repo: Название репозитория
        token: GitHub токен
        since: Загружать коммиты начиная с этой даты
        until: Загружать коммиты до этой даты

    Returns:
        int: Общее количество коммитов за период
    """
    logger.info("[github_stats_manual:get_commits_count] Getting commits count for %s/%s (since=%s, until=%s)",
               owner, repo, since.isoformat() if since else None, until.isoformat() if until else None)

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

    params = {
        "per_page": 1,  # Минимальный размер для быстрого запроса
    }

    if since:
        params["since"] = since.isoformat()
    if until:
        params["until"] = until.isoformat()

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()

        # Проверяем Link header для определения количества страниц
        link_header = response.headers.get("Link", "")
        if "last" in link_header:
            # Парсим Link header: <url?page=N>; rel="last"
            import re
            match = re.search(r'page=(\d+)>; rel="last"', link_header)
            if match:
                last_page = int(match.group(1))
                # Общее количество = (последняя страница - 1) * per_page + коммиты на последней странице
                # Для простоты возвращаем приблизительное значение
                # Делаем ещё один запрос с per_page=100 для более точного подсчёта
                params_accurate = params.copy()
                params_accurate["per_page"] = 100
                response_accurate = requests.get(url, headers=headers, params=params_accurate, timeout=30)
                response_accurate.raise_for_status()

                link_accurate = response_accurate.headers.get("Link", "")
                if "last" in link_accurate:
                    match_accurate = re.search(r'page=(\d+)>; rel="last"', link_accurate)
                    if match_accurate:
                        last_page_accurate = int(match_accurate.group(1))
                        # Приблизительное количество
                        count = (last_page_accurate - 1) * 100 + len(response_accurate.json())
                        logger.info("[github_stats_manual:get_commits_count] ✓ Estimated count: %d commits", count)
                        return count

                # Если не удалось получить точное количество, используем приблизительное
                count = last_page * 1
                logger.info("[github_stats_manual:get_commits_count] ✓ Approximate count: %d commits", count)
                return count

        # Если Link header отсутствует, значит все коммиты на первой странице
        count = len(response.json())
        logger.info("[github_stats_manual:get_commits_count] ✓ Single page count: %d commits", count)
        return count

    except Exception as e:
        logger.warning("[github_stats_manual:get_commits_count] ⚠ Failed to get commits count: %s, returning 0", e)
        return 0


def get_commits_paginated(
    owner: str,
    repo: str,
    token: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    per_page: int = 100,
):
    """
    Генератор для постраничной загрузки коммитов.
    Позволяет начать обработку сразу после получения первой страницы.

    Args:
        owner: Владелец репозитория
        repo: Название репозитория
        token: GitHub токен
        since: Загружать коммиты начиная с этой даты
        until: Загружать коммиты до этой даты
        per_page: Количество коммитов на страницу (макс 100)

    Yields:
        dict: Информация о странице:
            - commits: list[dict] - список коммитов на странице
            - page: int - номер страницы
            - has_more: bool - есть ли еще страницы
            - total_on_page: int - количество коммитов на текущей странице
    """
    logger.info("[github_stats_manual:get_commits_paginated] Starting paginated fetch for %s/%s (per_page=%d, since=%s, until=%s)",
               owner, repo, per_page, since.isoformat() if since else None, until.isoformat() if until else None)

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

    page = 1
    per_page = min(per_page, 100)  # GitHub максимум 100

    while True:
        params = {
            "page": page,
            "per_page": per_page,
        }

        if since:
            params["since"] = since.isoformat()
        if until:
            params["until"] = until.isoformat()

        try:
            logger.debug("[github_stats_manual:get_commits_paginated] Fetching page %d", page)
            response = github_request_with_retry(url, headers, params)
        except requests.RequestException as e:
            logger.error("[github_stats_manual:get_commits_paginated] ✗ Failed to fetch commits page %d: %s", page, e)
            raise

        commits = response.json()

        if not commits:
            # Нет больше коммитов
            logger.info("[github_stats_manual:get_commits_paginated] ✓ Pagination complete: no more commits")
            break

        has_more = "next" in response.links and len(commits) == per_page

        logger.info("[github_stats_manual:get_commits_paginated] ✓ Fetched page %d: %d commits (has_more=%s)",
                   page, len(commits), has_more)

        yield {
            "commits": commits,
            "page": page,
            "has_more": has_more,
            "total_on_page": len(commits),
        }

        if not has_more:
            logger.info("[github_stats_manual:get_commits_paginated] ✓ Pagination complete: last page reached")
            break

        page += 1



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

    response = github_request_with_retry(url, headers)
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
