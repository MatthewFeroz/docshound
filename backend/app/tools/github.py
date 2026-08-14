from datetime import datetime
from urllib.parse import quote

import httpx

from app.config import get_settings
from app.runtime_credentials import get_github_api_token
from app.state import Issue, PullRequest


class GitHubToolError(RuntimeError):
    pass


def configured_github_token() -> str | None:
    """Prefer a locally supplied token over the server environment credential."""
    return get_github_api_token() or get_settings().github_token


def _github_headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "docshound",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def validate_github_access(
    repo: str,
    token: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> tuple[str, str]:
    """Verify that a token can read repo metadata, activity, and documentation."""
    headers = _github_headers(token)
    owns_client = client is None
    github = client or httpx.AsyncClient(
        base_url="https://api.github.com",
        timeout=20,
    )

    async def request(path: str, *, params: dict[str, str | int] | None = None):
        response = await github.get(path, headers=headers, params=params)
        if response.status_code == 401:
            raise GitHubToolError(
                "GitHub rejected this token. Create a new token and try again."
            )
        if response.status_code == 403:
            raise GitHubToolError(
                "This token cannot read the selected repository's contents, "
                "issues, and pull requests."
            )
        if response.status_code == 404:
            raise GitHubToolError(f"Repository not found or inaccessible: {repo}")
        if response.status_code >= 400:
            raise GitHubToolError(
                f"GitHub access check failed with {response.status_code}."
            )
        return response.json()

    try:
        account_payload = await request("/user")
        repository = await request(f"/repos/{repo}")
        await request(f"/repos/{repo}/issues", params={"per_page": 1})
        await request(f"/repos/{repo}/pulls", params={"per_page": 1})
        branch = str(repository.get("default_branch") or "main")
        await request(
            f"/repos/{repo}/git/trees/{quote(branch, safe='')}",
            params={"recursive": 0},
        )
    finally:
        if owns_client:
            await github.aclose()

    account = str(account_payload.get("login") or "GitHub user")
    repository_name = str(repository.get("full_name") or repo)
    return account, repository_name


async def research_repo(repo: str, limit: int) -> list[Issue]:
    headers = _github_headers(configured_github_token())

    url = f"https://api.github.com/repos/{repo}/issues"

    issues: list[Issue] = []
    async with httpx.AsyncClient(timeout=20) as client:
        for page in range(1, 6):
            response = await client.get(
                url,
                headers=headers,
                params={
                    "state": "all",
                    "per_page": 100,
                    "page": page,
                    "sort": "updated",
                    "direction": "desc",
                },
            )
            if response.status_code == 404:
                raise GitHubToolError(f"Repository not found or inaccessible: {repo}")
            if response.status_code >= 400:
                raise GitHubToolError(
                    f"GitHub API failed with {response.status_code}: {response.text[:300]}"
                )
            items = response.json()
            if not items:
                break
            for item in items:
                if "pull_request" in item:
                    continue
                issues.append(
                    Issue(
                        number=item["number"],
                        title=item["title"],
                        body=item.get("body"),
                        url=item["html_url"],
                        state=item["state"],
                        labels=[label["name"] for label in item.get("labels", [])],
                        comments_count=item.get("comments", 0),
                        created_at=datetime.fromisoformat(
                            item["created_at"].replace("Z", "+00:00")
                        ),
                        updated_at=datetime.fromisoformat(
                            item["updated_at"].replace("Z", "+00:00")
                        ),
                        source_repo=repo,
                    )
                )
                if len(issues) >= limit:
                    return issues
    return issues


async def research_pull_requests(
    repo: str,
    limit: int,
    include_open: bool = False,
) -> list[PullRequest]:
    """Fetch merged PRs, plus open PRs for a separate documentation repo."""
    headers = _github_headers(configured_github_token())

    url = f"https://api.github.com/repos/{repo}/pulls"
    pull_requests: list[PullRequest] = []
    target = min(limit, 30)
    async with httpx.AsyncClient(timeout=20) as client:
        for page in range(1, 6):
            response = await client.get(
                url,
                headers=headers,
                params={
                    "state": "all" if include_open else "closed",
                    "per_page": 100,
                    "page": page,
                    "sort": "updated",
                    "direction": "desc",
                },
            )
            if response.status_code == 404:
                raise GitHubToolError(f"Repository not found or inaccessible: {repo}")
            if response.status_code >= 400:
                raise GitHubToolError(
                    f"GitHub API failed with {response.status_code}: {response.text[:300]}"
                )
            items = response.json()
            if not items:
                break
            for item in items:
                merged_at = item.get("merged_at")
                if not merged_at and not (include_open and item.get("state") == "open"):
                    continue
                pull_requests.append(
                    PullRequest(
                        number=item["number"],
                        title=item["title"],
                        body=item.get("body"),
                        url=item["html_url"],
                        state="merged" if merged_at else "open",
                        merged_at=(
                            datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
                            if merged_at
                            else None
                        ),
                        labels=[label["name"] for label in item.get("labels", [])],
                        created_at=datetime.fromisoformat(
                            item["created_at"].replace("Z", "+00:00")
                        ),
                        updated_at=datetime.fromisoformat(
                            item["updated_at"].replace("Z", "+00:00")
                        ),
                        source_repo=repo,
                    )
                )
                if len(pull_requests) >= target:
                    return pull_requests
    return pull_requests
