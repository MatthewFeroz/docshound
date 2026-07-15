import base64
import difflib
import json
import re
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import httpx

from app.approved_documents import ApprovedDocument, document_body_markdown
from app.config import get_settings


DB_PATH = Path(__file__).parent.parent / "data" / "docshound.db"
GITHUB_API = "https://api.github.com"
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class DocumentationPullRequestError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class DocumentationChange:
    document_slug: str
    target_repo: str
    base_branch: str
    branch_name: str
    file_path: str
    file_format: str
    detected_by: str
    content: str
    patch: str
    existing_sha: str | None
    status: str
    pr_number: int | None
    pr_url: str | None
    error: str | None
    created_at: str
    updated_at: str


async def prepare_documentation_change(
    document: ApprovedDocument,
    *,
    target_repo: str,
    requested_path: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> DocumentationChange:
    target_repo = _validate_repo(target_repo)
    token = get_settings().github_write_token or get_settings().github_token
    async with _github_client(token, client) as github:
        repository = await _request_json(
            github,
            "GET",
            f"/repos/{target_repo}",
        )
        base_branch = str(repository.get("default_branch") or "main")
        tree = await _request_json(
            github,
            "GET",
            f"/repos/{target_repo}/git/trees/{quote(base_branch, safe='')}",
            params={"recursive": "1"},
        )
        tree_items = tree.get("tree") or []
        paths = {
            str(item.get("path")): item
            for item in tree_items
            if item.get("path") and item.get("type") == "blob"
        }
        file_path, file_format, detected_by = _choose_document_path(
            document,
            set(paths),
            requested_path,
        )
        existing_sha = None
        previous_content = ""
        if file_path in paths:
            existing_sha = str(paths[file_path].get("sha") or "") or None
            existing = await _request_json(
                github,
                "GET",
                f"/repos/{target_repo}/contents/{quote(file_path, safe='/')}",
                params={"ref": base_branch},
            )
            encoded = str(existing.get("content") or "").replace("\n", "")
            if encoded:
                previous_content = base64.b64decode(encoded).decode("utf-8")

    content = _build_document_content(document, file_format)
    patch = _build_patch(file_path, previous_content, content)
    now = datetime.now(timezone.utc).isoformat()
    change = DocumentationChange(
        document_slug=document.slug,
        target_repo=target_repo,
        base_branch=base_branch,
        branch_name=_branch_name(document),
        file_path=file_path,
        file_format=file_format,
        detected_by=detected_by,
        content=content,
        patch=patch,
        existing_sha=existing_sha,
        status="preview_ready",
        pr_number=None,
        pr_url=None,
        error=None,
        created_at=now,
        updated_at=now,
    )
    save_documentation_change(change)
    return change


async def create_documentation_pull_request(
    document: ApprovedDocument,
    change: DocumentationChange,
    *,
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> DocumentationChange:
    if change.status == "created" and change.pr_url:
        return change

    write_token = token or get_settings().github_write_token
    if not write_token:
        raise DocumentationPullRequestError(
            "Set GITHUB_WRITE_TOKEN to create the documentation pull request."
        )

    try:
        async with _github_client(write_token, client) as github:
            base_ref = await _request_json(
                github,
                "GET",
                f"/repos/{change.target_repo}/git/ref/heads/"
                f"{quote(change.base_branch, safe='')}",
            )
            base_sha = str((base_ref.get("object") or {}).get("sha") or "")
            if not base_sha:
                raise DocumentationPullRequestError(
                    f"Could not resolve the {change.base_branch} branch."
                )

            branch_already_exists = False
            try:
                await _request_json(
                    github,
                    "POST",
                    f"/repos/{change.target_repo}/git/refs",
                    json_body={
                        "ref": f"refs/heads/{change.branch_name}",
                        "sha": base_sha,
                    },
                )
            except DocumentationPullRequestError as exc:
                if exc.status_code != 422:
                    raise
                branch_already_exists = True
                await _request_json(
                    github,
                    "GET",
                    f"/repos/{change.target_repo}/git/ref/heads/"
                    f"{quote(change.branch_name, safe='')}",
                )

            branch_file_sha = change.existing_sha
            branch_content: str | None = None
            if branch_already_exists:
                response = await github.get(
                    f"/repos/{change.target_repo}/contents/"
                    f"{quote(change.file_path, safe='/')}",
                    params={"ref": change.branch_name},
                )
                if response.status_code == 200:
                    branch_file = response.json()
                    branch_file_sha = str(branch_file.get("sha") or "") or None
                    encoded = str(branch_file.get("content") or "").replace("\n", "")
                    if encoded:
                        branch_content = base64.b64decode(encoded).decode("utf-8")
                elif response.status_code != 404:
                    await _raise_for_github_response(response)

            content_payload: dict[str, object] = {
                "message": f"docs: {document.title}",
                "content": base64.b64encode(change.content.encode("utf-8")).decode(
                    "ascii"
                ),
                "branch": change.branch_name,
            }
            if branch_file_sha:
                content_payload["sha"] = branch_file_sha
            if branch_content != change.content:
                await _request_json(
                    github,
                    "PUT",
                    f"/repos/{change.target_repo}/contents/"
                    f"{quote(change.file_path, safe='/')}",
                    json_body=content_payload,
                )

            owner = change.target_repo.split("/", 1)[0]
            pr_payload = {
                "title": f"docs: {document.title}",
                "head": f"{owner}:{change.branch_name}",
                "base": change.base_branch,
                "body": _pull_request_body(document, change),
            }
            try:
                pull_request = await _request_json(
                    github,
                    "POST",
                    f"/repos/{change.target_repo}/pulls",
                    json_body=pr_payload,
                )
            except DocumentationPullRequestError as exc:
                if exc.status_code != 422:
                    raise
                existing = await _request_json(
                    github,
                    "GET",
                    f"/repos/{change.target_repo}/pulls",
                    params={
                        "state": "open",
                        "head": f"{owner}:{change.branch_name}",
                    },
                )
                if not isinstance(existing, list) or not existing:
                    raise
                pull_request = existing[0]

        completed = replace(
            change,
            status="created",
            pr_number=int(pull_request["number"]),
            pr_url=str(pull_request["html_url"]),
            error=None,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        save_documentation_change(completed)
        return completed
    except DocumentationPullRequestError as exc:
        failed = replace(
            change,
            status="failed",
            error=str(exc),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        save_documentation_change(failed)
        raise


def get_documentation_change(document_slug: str) -> DocumentationChange | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM documentation_changes WHERE document_slug = ?",
            (document_slug,),
        ).fetchone()
    return _change_from_row(row) if row else None


def save_documentation_change(change: DocumentationChange) -> None:
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO documentation_changes (
                document_slug, target_repo, base_branch, branch_name, file_path,
                file_format, detected_by, content, patch, existing_sha, status,
                pr_number, pr_url, error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_slug) DO UPDATE SET
                target_repo = excluded.target_repo,
                base_branch = excluded.base_branch,
                branch_name = excluded.branch_name,
                file_path = excluded.file_path,
                file_format = excluded.file_format,
                detected_by = excluded.detected_by,
                content = excluded.content,
                patch = excluded.patch,
                existing_sha = excluded.existing_sha,
                status = excluded.status,
                pr_number = excluded.pr_number,
                pr_url = excluded.pr_url,
                error = excluded.error,
                updated_at = excluded.updated_at
            """,
            (
                change.document_slug,
                change.target_repo,
                change.base_branch,
                change.branch_name,
                change.file_path,
                change.file_format,
                change.detected_by,
                change.content,
                change.patch,
                change.existing_sha,
                change.status,
                change.pr_number,
                change.pr_url,
                change.error,
                change.created_at,
                change.updated_at,
            ),
        )


def write_enabled() -> bool:
    return bool(get_settings().github_write_token)


def _choose_document_path(
    document: ApprovedDocument,
    paths: set[str],
    requested_path: str | None,
) -> tuple[str, str, str]:
    if requested_path and requested_path.strip():
        path = _validate_path(requested_path)
        extension = PurePosixPath(path).suffix.lower()
        return path, "mdx" if extension == ".mdx" else "markdown", "manual path"

    configs = sorted(
        (
            path
            for path in paths
            if PurePosixPath(path).name in {"docs.json", "mint.json"}
        ),
        key=lambda path: (path.count("/"), len(path)),
    )
    slug = _slugify(document.title)
    if configs:
        config_parent = str(PurePosixPath(configs[0]).parent)
        root = "" if config_parent == "." else f"{config_parent}/"
        existing_directories = {
            path.rsplit("/", 1)[0] for path in paths if "/" in path
        }
        directory = next(
            (
                f"{root}{candidate}".rstrip("/")
                for candidate in ("guides", "documentation", "reference")
                if f"{root}{candidate}".rstrip("/") in existing_directories
            ),
            f"{root}guides".rstrip("/"),
        )
        return f"{directory}/{slug}.mdx", "mdx", configs[0]

    docusaurus = next(
        (path for path in paths if PurePosixPath(path).name.startswith("docusaurus.config")),
        None,
    )
    if docusaurus:
        parent = str(PurePosixPath(docusaurus).parent)
        root = "" if parent == "." else f"{parent}/"
        return f"{root}docs/{slug}.mdx", "mdx", docusaurus

    mkdocs = next(
        (path for path in paths if PurePosixPath(path).name in {"mkdocs.yml", "mkdocs.yaml"}),
        None,
    )
    if mkdocs:
        parent = str(PurePosixPath(mkdocs).parent)
        root = "" if parent == "." else f"{parent}/"
        return f"{root}docs/{slug}.md", "markdown", mkdocs

    if any(path.startswith("docs/") for path in paths):
        return f"docs/{slug}.md", "markdown", "docs directory"
    if any(path.startswith("documentation/") for path in paths):
        return f"documentation/{slug}.md", "markdown", "documentation directory"
    return f"docs/{slug}.md", "markdown", "default docs directory"


def _build_document_content(document: ApprovedDocument, file_format: str) -> str:
    body = document_body_markdown(document.markdown).strip()
    if file_format == "mdx":
        title = _yaml_string(document.title)
        summary = _yaml_string(document.summary)
        body = (
            "---\n"
            f"title: {title}\n"
            f"description: {summary}\n"
            "---\n\n"
            f"{body}"
        )
    return f"{body.rstrip()}\n"


def _build_patch(file_path: str, previous: str, content: str) -> str:
    from_name = f"a/{file_path}" if previous else "/dev/null"
    return "".join(
        difflib.unified_diff(
            previous.splitlines(keepends=True),
            content.splitlines(keepends=True),
            fromfile=from_name,
            tofile=f"b/{file_path}",
        )
    )


def _pull_request_body(
    document: ApprovedDocument, change: DocumentationChange
) -> str:
    source_lines = []
    for source in document.source_issues:
        kind = "Merged PR" if source.get("kind") == "pull_request" else "Issue"
        source_lines.append(
            f"- [{kind} #{source['number']}: {source['title']}]({source['url']})"
        )
    sources = "\n".join(source_lines) or "- No linked repository sources."
    return (
        "## Documentation update\n\n"
        f"Adds `{change.file_path}` from an approved DocsHound finding.\n\n"
        f"{document.summary}\n\n"
        "## Evidence\n\n"
        f"{sources}\n\n"
        "## Review\n\n"
        "- [ ] Confirm the technical details\n"
        "- [ ] Confirm the page location and navigation\n"
        "- [ ] Merge when the documentation preview is ready\n"
    )


def _branch_name(document: ApprovedDocument) -> str:
    return f"docshound/{_slugify(document.title)[:38]}-{document.run_id[:8]}"


def _validate_repo(repo: str) -> str:
    cleaned = repo.strip()
    if not REPO_PATTERN.fullmatch(cleaned):
        raise DocumentationPullRequestError(
            "Enter the target repository as owner/repository."
        )
    return cleaned


def _validate_path(path: str) -> str:
    cleaned = path.strip().lstrip("/")
    pure = PurePosixPath(cleaned)
    if not cleaned or ".." in pure.parts or pure.suffix.lower() not in {".md", ".mdx"}:
        raise DocumentationPullRequestError(
            "The documentation path must be a repository-relative .md or .mdx file."
        )
    return str(pure)


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "documentation"


def _yaml_string(value: str) -> str:
    compact = " ".join(value.split())
    return json.dumps(compact, ensure_ascii=False)


@asynccontextmanager
async def _github_client(
    token: str | None, client: httpx.AsyncClient | None
):
    if client is not None:
        yield client
        return
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "docshound",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(
        base_url=GITHUB_API,
        headers=headers,
        timeout=25,
    ) as github:
        yield github


async def _request_json(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
    json_body: dict[str, object] | None = None,
):
    response = await client.request(method, path, params=params, json=json_body)
    if response.status_code >= 400:
        await _raise_for_github_response(response)
    if response.status_code == 204 or not response.content:
        return {}
    return response.json()


async def _raise_for_github_response(response: httpx.Response) -> None:
    try:
        detail = response.json().get("message")
    except Exception:
        detail = response.text[:240]
    raise DocumentationPullRequestError(
        f"GitHub returned {response.status_code}: {detail or 'request failed'}",
        status_code=response.status_code,
    )


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS documentation_changes (
            document_slug TEXT PRIMARY KEY,
            target_repo TEXT NOT NULL,
            base_branch TEXT NOT NULL,
            branch_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_format TEXT NOT NULL,
            detected_by TEXT NOT NULL,
            content TEXT NOT NULL,
            patch TEXT NOT NULL,
            existing_sha TEXT,
            status TEXT NOT NULL,
            pr_number INTEGER,
            pr_url TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    return connection


def _change_from_row(row: sqlite3.Row) -> DocumentationChange:
    return DocumentationChange(
        document_slug=row["document_slug"],
        target_repo=row["target_repo"],
        base_branch=row["base_branch"],
        branch_name=row["branch_name"],
        file_path=row["file_path"],
        file_format=row["file_format"],
        detected_by=row["detected_by"],
        content=row["content"],
        patch=row["patch"],
        existing_sha=row["existing_sha"],
        status=row["status"],
        pr_number=row["pr_number"],
        pr_url=row["pr_url"],
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
