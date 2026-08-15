from datetime import datetime
from urllib.parse import quote

import httpx2 as httpx

from app.config import get_settings
from app.demo_scenarios import (
    include_recent_activity,
    pinned_issue_numbers,
    pinned_pull_request_numbers,
)
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


async def research_repo(
    repo: str,
    limit: int,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[Issue]:
    headers = _github_headers(configured_github_token())
    issues: list[Issue] = []
    seen: set[int] = set()
    owns_client = client is None
    github = client or httpx.AsyncClient(
        base_url="https://api.github.com",
        timeout=20,
    )
    try:
        for number in pinned_issue_numbers(repo):
            response = await github.get(
                f"/repos/{repo}/issues/{number}",
                headers=headers,
            )
            payload = _github_payload(response, repo)
            if "pull_request" in payload:
                raise GitHubToolError(
                    f"Demo source {repo}#{number} is a pull request, not an issue."
                )
            issue = _issue_from_payload(payload, repo)
            issues.append(issue)
            seen.add(issue.number)
            if len(issues) >= limit:
                return issues

        if not include_recent_activity(repo):
            return issues

        for page in range(1, 6):
            response = await github.get(
                f"/repos/{repo}/issues",
                headers=headers,
                params={
                    "state": "all",
                    "per_page": 100,
                    "page": page,
                    "sort": "updated",
                    "direction": "desc",
                },
            )
            items = _github_payload(response, repo)
            if not isinstance(items, list):
                raise GitHubToolError("GitHub returned an invalid issues response.")
            if not items:
                break
            for item in items:
                if "pull_request" in item or item["number"] in seen:
                    continue
                issue = _issue_from_payload(item, repo)
                issues.append(issue)
                seen.add(issue.number)
                if len(issues) >= limit:
                    return issues
        return issues
    finally:
        if owns_client:
            await github.aclose()


async def research_pull_requests(
    repo: str,
    limit: int,
    include_open: bool = False,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[PullRequest]:
    """Fetch merged PRs, plus open PRs for a separate documentation repo."""
    headers = _github_headers(configured_github_token())
    pull_requests: list[PullRequest] = []
    seen: set[int] = set()
    target = min(limit, 30)
    owns_client = client is None
    github = client or httpx.AsyncClient(
        base_url="https://api.github.com",
        timeout=20,
    )
    try:
        for number in pinned_pull_request_numbers(repo):
            response = await github.get(
                f"/repos/{repo}/pulls/{number}",
                headers=headers,
            )
            payload = _github_payload(response, repo)
            pull_request = _pull_request_from_payload(payload, repo)
            if pull_request.state != "merged" and not include_open:
                raise GitHubToolError(
                    f"Demo source {repo}#{number} is not a merged pull request."
                )
            pull_requests.append(pull_request)
            seen.add(pull_request.number)
            if len(pull_requests) >= target:
                return pull_requests

        if not include_recent_activity(repo):
            return pull_requests

        for page in range(1, 6):
            response = await github.get(
                f"/repos/{repo}/pulls",
                headers=headers,
                params={
                    "state": "all" if include_open else "closed",
                    "per_page": 100,
                    "page": page,
                    "sort": "updated",
                    "direction": "desc",
                },
            )
            items = _github_payload(response, repo)
            if not isinstance(items, list):
                raise GitHubToolError("GitHub returned an invalid pull-request response.")
            if not items:
                break
            for item in items:
                if item["number"] in seen:
                    continue
                pull_request = _pull_request_from_payload(item, repo)
                if pull_request.state != "merged" and not (
                    include_open and item.get("state") == "open"
                ):
                    continue
                pull_requests.append(pull_request)
                seen.add(pull_request.number)
                if len(pull_requests) >= target:
                    return pull_requests
        return pull_requests
    finally:
        if owns_client:
            await github.aclose()


def _github_payload(response: httpx.Response, repo: str):
    if response.status_code == 404:
        raise GitHubToolError(f"Repository or demo source not found: {repo}")
    if response.status_code >= 400:
        raise GitHubToolError(
            f"GitHub API failed with {response.status_code}: {response.text[:300]}"
        )
    return response.json()


def _issue_from_payload(item: dict, repo: str) -> Issue:
    return Issue(
        number=item["number"],
        title=item["title"],
        body=item.get("body"),
        url=item["html_url"],
        state=item["state"],
        labels=[label["name"] for label in item.get("labels", [])],
        comments_count=item.get("comments", 0),
        created_at=datetime.fromisoformat(item["created_at"].replace("Z", "+00:00")),
        updated_at=datetime.fromisoformat(item["updated_at"].replace("Z", "+00:00")),
        source_repo=repo,
    )


def _pull_request_from_payload(item: dict, repo: str) -> PullRequest:
    merged_at = item.get("merged_at")
    return PullRequest(
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
        created_at=datetime.fromisoformat(item["created_at"].replace("Z", "+00:00")),
        updated_at=datetime.fromisoformat(item["updated_at"].replace("Z", "+00:00")),
        source_repo=repo,
    )
