import asyncio
import base64
import ipaddress
import re
import socket
from contextlib import asynccontextmanager
from dataclasses import dataclass
from html import unescape
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx

from app.runtime_credentials import get_github_api_token
from app.config import get_settings
from app.state import DocumentationSource


GITHUB_API = "https://api.github.com"
DOC_EXTENSIONS = {".md", ".mdx"}
DOC_LINK_LABEL = re.compile(
    r"\b(documentation|docs?|api\s+reference|guides?|manual|handbook)\b",
    re.IGNORECASE,
)
MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+['\"][^)]*['\"])?\)")
HTML_LINK = re.compile(r"href\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
GITHUB_SOURCE_PATH = re.compile(
    r"^/([^/]+)/([^/]+)/(?:edit|blob|tree)/[^/]+(?:/(.*))?$",
    re.IGNORECASE,
)
MAX_WEBSITE_BYTES = 2_000_000


@dataclass(frozen=True)
class ResolvedDocumentationSources:
    product_repo: str
    documentation_sources: list[DocumentationSource]
    selected_source: DocumentationSource
    documentation_activity_repos: list[str]


@dataclass
class _Candidate:
    repo: str
    root: str | None
    url: str | None
    confidence: float
    discovered_by: str
    page_count: int | None = None
    score: float = 0


async def resolve_documentation_sources(
    repo: str,
    *,
    client: httpx.AsyncClient | None = None,
    fetch_websites: bool = True,
) -> ResolvedDocumentationSources:
    """Resolve the canonical first-party docs repo/root from one product repo."""
    token = get_github_api_token() or get_settings().github_token
    async with _github_client(token, client) as github:
        metadata, branch, tree = await _load_repository(github, repo)
        readme = await _load_readme(github, repo)

        candidates = _repository_candidates(repo, branch, tree, readme)
        documentation_urls = _documentation_urls(metadata, readme)

        for docs_url in documentation_urls[:4]:
            github_source = _github_source_from_url(docs_url)
            if github_source:
                source_repo, source_root = github_source
                candidates.append(
                    _Candidate(
                        repo=source_repo,
                        root=source_root,
                        url=docs_url,
                        confidence=0.97,
                        discovered_by="readme_github_link",
                        score=970,
                    )
                )
                continue
            if not fetch_websites:
                continue
            try:
                html, final_url = await _fetch_public_html(docs_url)
            except Exception:
                continue
            edit_source = _edit_source_from_html(html, final_url)
            if edit_source:
                source_repo, source_root, edit_url = edit_source
                candidates.append(
                    _Candidate(
                        repo=source_repo,
                        root=source_root,
                        url=final_url,
                        confidence=0.99,
                        discovered_by="edit_on_github",
                        score=1_000,
                    )
                )
            else:
                for linked_repo in _docs_site_repository_links(
                    html,
                    product_repo=repo,
                ):
                    candidates.append(
                        _Candidate(
                            repo=linked_repo,
                            root=None,
                            url=final_url,
                            confidence=0.93,
                            discovered_by="docs_site_github_link",
                            score=940,
                        )
                    )

        candidates = await _hydrate_candidates(github, candidates)
        sources = _deduplicate_candidates(candidates)
        if not sources:
            fallback_count = _count_docs_pages(tree, None)
            sources = [
                DocumentationSource(
                    kind="github",
                    repo=repo,
                    root=None,
                    url=_github_tree_url(repo, branch, None),
                    confidence=0.55,
                    discovered_by="repository_fallback",
                    page_count=fallback_count,
                )
            ]

        selected = sources[0]
        activity_repos = (
            [selected.repo]
            if selected.kind == "github"
            and selected.repo
            and selected.repo.lower() != repo.lower()
            else []
        )
        return ResolvedDocumentationSources(
            product_repo=repo,
            documentation_sources=sources,
            selected_source=selected,
            documentation_activity_repos=activity_repos,
        )


async def enrich_documentation_source(
    source: DocumentationSource,
    *,
    product_repo: str,
    client: httpx.AsyncClient | None = None,
) -> DocumentationSource:
    """Validate a user override and fill its page count and browse URL."""
    if source.kind != "github" or not source.repo:
        return source
    token = get_github_api_token() or get_settings().github_token
    async with _github_client(token, client) as github:
        _metadata, branch, tree = await _load_repository(github, source.repo)
    return source.model_copy(
        update={
            "page_count": _count_docs_pages(tree, source.root),
            "url": source.url or _github_tree_url(source.repo, branch, source.root),
            "discovered_by": source.discovered_by or "user_override",
        }
    )


def _repository_candidates(
    repo: str,
    branch: str,
    tree: list[dict],
    readme: str,
) -> list[_Candidate]:
    markdown_paths = _canonical_markdown_paths(tree)
    root_counts: dict[str, int] = {}
    for path in markdown_paths:
        root = _infer_docs_root(path)
        if root:
            root_counts[root] = root_counts.get(root, 0) + 1

    candidates: list[_Candidate] = []
    manifest_roots = _manifest_roots(tree)
    for root, count in root_counts.items():
        if count < 2:
            continue
        manifest = root in manifest_roots or any(
            root.startswith(f"{manifest_root}/") for manifest_root in manifest_roots
        )
        confidence = 0.95 if manifest else 0.86
        method = "docs_manifest" if manifest else "conventional_docs_root"
        candidates.append(
            _Candidate(
                repo=repo,
                root=root,
                url=_github_tree_url(repo, branch, root),
                confidence=confidence,
                discovered_by=method,
                page_count=count,
                score=(900 if manifest else 700) + min(count, 100),
            )
        )

    for label, href in MARKDOWN_LINK.findall(readme):
        if not DOC_LINK_LABEL.search(unescape(label)):
            continue
        internal_root = _internal_docs_root(href)
        if internal_root and _count_docs_pages(tree, internal_root):
            count = _count_docs_pages(tree, internal_root)
            candidates.append(
                _Candidate(
                    repo=repo,
                    root=internal_root,
                    url=_github_tree_url(repo, branch, internal_root),
                    confidence=0.97,
                    discovered_by="readme_docs_link",
                    page_count=count,
                    score=950 + min(count, 100),
                )
            )
    return candidates


def _documentation_urls(metadata: dict, readme: str) -> list[str]:
    urls: list[str] = []
    homepage = str(metadata.get("homepage") or "").strip()
    if _is_external_http_url(homepage):
        urls.append(homepage)
        parsed_homepage = urlparse(homepage)
        if parsed_homepage.path.rstrip("/") in {"", "/"}:
            urls.append(urljoin(f"{homepage.rstrip('/')}/", "docs/"))
    for label, href in MARKDOWN_LINK.findall(readme):
        if DOC_LINK_LABEL.search(unescape(label)) and _is_external_http_url(href):
            urls.append(unescape(href))
    return list(dict.fromkeys(urls))


async def _hydrate_candidates(
    github: httpx.AsyncClient,
    candidates: list[_Candidate],
) -> list[_Candidate]:
    hydrated: list[_Candidate] = []
    tree_cache: dict[str, tuple[str, list[dict]]] = {}
    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
        if candidate.repo not in tree_cache:
            try:
                _metadata, branch, tree = await _load_repository(github, candidate.repo)
            except Exception:
                continue
            tree_cache[candidate.repo] = (branch, tree)
        branch, tree = tree_cache[candidate.repo]
        root = candidate.root
        if root is None and candidate.discovered_by == "docs_site_github_link":
            root = _best_repository_root(tree)
        if root and not _count_docs_pages(tree, root):
            inferred = _closest_existing_root(tree, root)
            if not inferred:
                continue
            root = inferred
        candidate.root = root
        candidate.page_count = _count_docs_pages(tree, root)
        candidate.url = candidate.url or _github_tree_url(candidate.repo, branch, root)
        hydrated.append(candidate)
    return hydrated


def _deduplicate_candidates(candidates: list[_Candidate]) -> list[DocumentationSource]:
    unique: dict[tuple[str, str | None], _Candidate] = {}
    for candidate in candidates:
        key = (candidate.repo.lower(), candidate.root)
        previous = unique.get(key)
        if previous is None or candidate.score > previous.score:
            unique[key] = candidate
    ranked = sorted(unique.values(), key=lambda item: item.score, reverse=True)
    return [
        DocumentationSource(
            kind="github",
            repo=candidate.repo,
            root=candidate.root,
            url=candidate.url,
            confidence=candidate.confidence,
            discovered_by=candidate.discovered_by,
            page_count=candidate.page_count,
        )
        for candidate in ranked[:5]
    ]


def _canonical_markdown_paths(tree: list[dict]) -> list[str]:
    paths = [
        str(item.get("path") or "")
        for item in tree
        if item.get("type") == "blob"
        and PurePosixPath(str(item.get("path") or "")).suffix.lower()
        in DOC_EXTENSIONS
        and not any(
            part.startswith(".")
            for part in PurePosixPath(str(item.get("path") or "")).parts[:-1]
        )
    ]
    localized = re.compile(r"^[a-z]{2}(?:-[a-z]{2})?$", re.IGNORECASE)
    preferred: dict[str, tuple[str, int]] = {}
    for path in paths:
        parts = list(PurePosixPath(path).parts)
        normalized = path
        locale_priority = 2
        for index, part in enumerate(parts[:-1]):
            if part.lower() == "docs" and index + 1 < len(parts) - 1:
                locale = parts[index + 1]
                if localized.fullmatch(locale):
                    normalized = str(
                        PurePosixPath(*(parts[: index + 1] + parts[index + 2 :]))
                    )
                    locale_priority = 1 if locale.lower().startswith("en") else 0
                break
        previous = preferred.get(normalized)
        if previous is None or locale_priority > previous[1]:
            preferred[normalized] = (path, locale_priority)
    return [path for path, _priority in preferred.values()]


def _infer_docs_root(path: str) -> str | None:
    parts = list(PurePosixPath(path).parts)
    lowered = [part.lower() for part in parts[:-1]]
    patterns = (
        ("src", "content", "docs"),
        ("content", "en", "docs"),
        ("website", "docs"),
    )
    for pattern in patterns:
        for index in range(0, len(lowered) - len(pattern) + 1):
            if tuple(lowered[index : index + len(pattern)]) == pattern:
                return str(PurePosixPath(*parts[: index + len(pattern)]))
    for marker in ("docs", "documentation", "handbook", "guides"):
        indexes = [index for index, part in enumerate(lowered) if part == marker]
        if indexes:
            return str(PurePosixPath(*parts[: indexes[-1] + 1]))
    return None


def _manifest_roots(tree: list[dict]) -> set[str]:
    roots: set[str] = set()
    for item in tree:
        if item.get("type") != "blob":
            continue
        path = PurePosixPath(str(item.get("path") or ""))
        name = path.name.lower()
        if name in {"docs.json", "mint.json", "mkdocs.yml", "mkdocs.yaml"} or name.startswith(
            ("docusaurus.config.", "astro.config.")
        ):
            parent = str(path.parent)
            if parent != ".":
                roots.add(parent)
    return roots


def _count_docs_pages(tree: list[dict], root: str | None) -> int:
    prefix = f"{root.strip('/')}/" if root else ""
    paths = _canonical_markdown_paths(tree)
    return sum(1 for path in paths if not prefix or path.startswith(prefix))


def _best_repository_root(tree: list[dict]) -> str | None:
    counts: dict[str, int] = {}
    for path in _canonical_markdown_paths(tree):
        root = _infer_docs_root(path)
        if root:
            counts[root] = counts.get(root, 0) + 1
    if not counts:
        return None
    return max(
        counts,
        key=lambda root: (
            root.lower().split("/").count("en"),
            counts[root],
            -len(PurePosixPath(root).parts),
        ),
    )


def _closest_existing_root(tree: list[dict], root: str) -> str | None:
    if _count_docs_pages(tree, root):
        return root
    inferred = _infer_docs_root(f"{root.rstrip('/')}/index.md")
    return inferred if inferred and _count_docs_pages(tree, inferred) else None


def _internal_docs_root(href: str) -> str | None:
    parsed = urlparse(unescape(href))
    if parsed.scheme or parsed.netloc or href.startswith("#"):
        return None
    path = unquote(parsed.path).strip().lstrip("./").strip("/")
    if not path or any(part == ".." for part in PurePosixPath(path).parts):
        return None
    pure = PurePosixPath(path)
    return str(pure.parent) if pure.suffix else str(pure)


def _github_source_from_url(url: str) -> tuple[str, str | None] | None:
    parsed = urlparse(unescape(url))
    if parsed.hostname not in {"github.com", "www.github.com"}:
        return None
    match = GITHUB_SOURCE_PATH.match(parsed.path)
    if not match:
        return None
    owner, repo, source_path = match.groups()
    repo = repo.removesuffix(".git")
    if not source_path:
        return f"{owner}/{repo}", None
    pure = PurePosixPath(unquote(source_path))
    root = _infer_docs_root(str(pure))
    if not root:
        root = str(pure.parent) if pure.suffix else str(pure)
    return f"{owner}/{repo}", None if root == "." else root


def _edit_source_from_html(
    html: str, base_url: str
) -> tuple[str, str | None, str] | None:
    for href in HTML_LINK.findall(html):
        absolute = urljoin(base_url, unescape(href))
        parsed = urlparse(absolute)
        if parsed.hostname not in {"github.com", "www.github.com"}:
            continue
        if "/edit/" not in parsed.path and "/blob/" not in parsed.path:
            continue
        source = _github_source_from_url(absolute)
        if source:
            return source[0], source[1], absolute
    return None


def _docs_site_repository_links(html: str, *, product_repo: str) -> list[str]:
    repositories: list[str] = []
    for href in HTML_LINK.findall(html):
        parsed = urlparse(unescape(href))
        if parsed.hostname not in {"github.com", "www.github.com"}:
            continue
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2:
            continue
        repo = f"{parts[0]}/{parts[1].removesuffix('.git')}"
        if repo.lower() == product_repo.lower():
            continue
        repositories.append(repo)
    return list(dict.fromkeys(repositories))[:3]


def _is_external_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


async def _fetch_public_html(url: str) -> tuple[str, str]:
    current = url
    async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
        for _redirect in range(4):
            await _validate_public_url(current)
            async with client.stream(
                "GET",
                current,
                headers={"User-Agent": "DocsHound/1.0 documentation-source-resolver"},
            ) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Documentation site returned an empty redirect")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if content_type and not any(
                    item in content_type.lower()
                    for item in ("text/html", "application/xhtml+xml")
                ):
                    raise ValueError("Documentation URL did not return HTML")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_WEBSITE_BYTES:
                        raise ValueError("Documentation homepage exceeded the size limit")
                    chunks.append(chunk)
                return b"".join(chunks).decode(response.encoding or "utf-8", "replace"), str(
                    response.url
                )
    raise ValueError("Documentation site redirected too many times")


async def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Documentation URL must be an HTTP or HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError("Documentation URL cannot contain credentials")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = await asyncio.get_running_loop().getaddrinfo(
        parsed.hostname,
        port,
        type=socket.SOCK_STREAM,
    )
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("Documentation URL must resolve to a public address")


async def _load_repository(
    github: httpx.AsyncClient, repo: str
) -> tuple[dict, str, list[dict]]:
    metadata = await _request_json(github, f"/repos/{repo}")
    branch = str(metadata.get("default_branch") or "main")
    tree_payload = await _request_json(
        github,
        f"/repos/{repo}/git/trees/{quote(branch, safe='')}",
        params={"recursive": "1"},
    )
    tree = tree_payload.get("tree") or []
    return metadata, branch, tree if isinstance(tree, list) else []


async def _load_readme(github: httpx.AsyncClient, repo: str) -> str:
    try:
        payload = await _request_json(github, f"/repos/{repo}/readme")
        encoded = str(payload.get("content") or "").replace("\n", "")
        return base64.b64decode(encoded).decode("utf-8", "replace") if encoded else ""
    except Exception:
        return ""


def _github_tree_url(repo: str, branch: str, root: str | None) -> str:
    if not root:
        return f"https://github.com/{repo}"
    return (
        f"https://github.com/{repo}/tree/{quote(branch, safe='')}/"
        f"{quote(root, safe='/')}"
    )


@asynccontextmanager
async def _github_client(token: str | None, client: httpx.AsyncClient | None):
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
    path: str,
    *,
    params: dict[str, str] | None = None,
) -> dict:
    response = await client.get(path, params=params)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}
