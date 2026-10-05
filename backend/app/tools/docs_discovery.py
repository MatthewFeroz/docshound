import asyncio
import ipaddress
import re
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse
from xml.etree import ElementTree

import httpx

from app.config import get_settings
from app.runtime_credentials import get_github_api_token

MAX_DOCUMENT_URLS = 40
MAX_SITEMAPS = 8
PAGE_CACHE_TTL_SECONDS = 600
PAGE_CACHE_MAX_ENTRIES = 128

_LOCALE_SEGMENTS = {
    "ar",
    "da",
    "de",
    "en",
    "es",
    "fr",
    "it",
    "ja",
    "ko",
    "nb",
    "pl",
    "pt",
    "pt-br",
    "ru",
    "th",
    "tr",
    "uk",
    "zh",
    "zh-cn",
    "zh-tw",
    "zht",
}
_NON_DOCUMENT_EXTENSIONS = {
    ".avif",
    ".css",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".map",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".svg",
    ".webm",
    ".webp",
    ".xml",
    ".zip",
}
_PAGE_CACHE: OrderedDict[str, tuple[float, "DocumentPage | None"]] = OrderedDict()


@dataclass(frozen=True)
class DocumentPage:
    title: str
    url: str
    text: str
    source_type: str = "official_docs"
    links: tuple[tuple[str, str], ...] = ()


def _prune_page_cache() -> None:
    now = time.monotonic()
    expired = [
        url
        for url, (stored_at, _) in _PAGE_CACHE.items()
        if now - stored_at >= PAGE_CACHE_TTL_SECONDS
    ]
    for url in expired:
        del _PAGE_CACHE[url]


def _cached_document_page(url: str) -> tuple[float, DocumentPage | None] | None:
    _prune_page_cache()
    cached = _PAGE_CACHE.get(url)
    if cached is not None:
        _PAGE_CACHE.move_to_end(url)
    return cached


def _cache_document_page(url: str, page: DocumentPage | None) -> None:
    _prune_page_cache()
    _PAGE_CACHE[url] = (time.monotonic(), page)
    _PAGE_CACHE.move_to_end(url)
    while len(_PAGE_CACHE) > PAGE_CACHE_MAX_ENTRIES:
        _PAGE_CACHE.popitem(last=False)


class _ReadableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.main_parts: list[str] = []
        self.body_parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._ignored_depth = 0
        self._main_depth = 0
        self._title_depth = 0
        self._anchor_href: str | None = None
        self._anchor_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag in {"script", "style", "noscript", "svg", "template"}:
            self._ignored_depth += 1
            return
        if tag == "title":
            self._title_depth += 1
        if tag in {"main", "article"}:
            self._main_depth += 1
        if tag == "a":
            self._anchor_href = attrs_dict.get("href")
            self._anchor_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "template"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if tag == "title":
            self._title_depth = max(0, self._title_depth - 1)
        if tag in {"main", "article"}:
            self._main_depth = max(0, self._main_depth - 1)
        if tag == "a" and self._anchor_href:
            anchor_text = " ".join(self._anchor_parts).strip()
            self.links.append((self._anchor_href, anchor_text))
            self._anchor_href = None
            self._anchor_parts = []

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self._title_depth:
            self.title_parts.append(text)
        self.body_parts.append(text)
        if self._main_depth:
            self.main_parts.append(text)
        if self._anchor_href is not None:
            self._anchor_parts.append(text)


async def discover_docs_root(
    client: httpx.AsyncClient,
    repo: str,
    explicit_docs_url: str | None,
) -> str | None:
    if explicit_docs_url:
        return _normalize_public_url(explicit_docs_url)

    candidates: list[tuple[int, str]] = []
    metadata = await _fetch_repo_metadata(client, repo)
    homepage = metadata.get("homepage") if metadata else None
    if isinstance(homepage, str):
        normalized_homepage = _normalize_public_url(homepage)
        if normalized_homepage:
            candidates.extend(
                [
                    (90, urljoin(f"{normalized_homepage.rstrip('/')}/", "docs")),
                    (50, normalized_homepage),
                ]
            )

    readme = await fetch_repository_readme(client, repo)
    if readme:
        for label, url in _extract_markdown_links(readme.text):
            score = _docs_url_score(url)
            if "doc" in label.lower():
                score += 60
            if score:
                candidates.append((score, url))

    for _, candidate in sorted(set(candidates), reverse=True):
        page = await fetch_document_page(client, candidate)
        if not page:
            continue
        if _looks_like_docs_page(candidate, page):
            return page.url
        for href, anchor_text in page.links:
            if "doc" not in anchor_text.lower():
                continue
            resolved = _normalize_public_url(urljoin(page.url, href))
            if resolved:
                linked_page = await fetch_document_page(client, resolved)
                if linked_page:
                    return linked_page.url

    return None


async def discover_document_urls(
    client: httpx.AsyncClient,
    docs_root: str,
) -> list[str]:
    normalized_root = _normalize_public_url(docs_root)
    if not normalized_root:
        return []

    parsed_root = urlparse(normalized_root)
    origin = f"{parsed_root.scheme}://{parsed_root.netloc}"
    sitemap_urls: list[str] = []

    robots = await _fetch_text(client, f"{origin}/robots.txt")
    if robots:
        sitemap_urls.extend(
            match.group(1).strip()
            for match in re.finditer(
                r"^\s*Sitemap:\s*(\S+)\s*$",
                robots,
                flags=re.IGNORECASE | re.MULTILINE,
            )
        )
    sitemap_urls.extend(
        [
            f"{origin}/sitemap.xml",
            f"{origin}/sitemap_index.xml",
        ]
    )

    discovered: list[str] = []
    queue = deque(dict.fromkeys(sitemap_urls))
    visited_sitemaps: set[str] = set()
    while queue and len(visited_sitemaps) < MAX_SITEMAPS:
        sitemap_url = queue.popleft()
        if sitemap_url in visited_sitemaps:
            continue
        visited_sitemaps.add(sitemap_url)
        xml = await _fetch_text(client, sitemap_url)
        if not xml:
            continue
        page_urls, child_sitemaps = parse_sitemap_document(xml)
        queue.extend(child_sitemaps)
        discovered.extend(page_urls)

    filtered = _filter_document_urls(discovered, normalized_root)
    if normalized_root not in filtered:
        filtered.insert(0, normalized_root)

    if len(filtered) <= 1:
        landing_page = await fetch_document_page(client, normalized_root)
        if landing_page:
            navigation_urls = [
                urljoin(landing_page.url, href) for href, _ in landing_page.links
            ]
            filtered = _filter_document_urls(
                [normalized_root, *navigation_urls],
                normalized_root,
            )

    return filtered[:MAX_DOCUMENT_URLS]


def parse_sitemap_document(xml: str) -> tuple[list[str], list[str]]:
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return [], []

    root_name = root.tag.rsplit("}", 1)[-1].lower()
    locations = [
        (element.text or "").strip()
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1].lower() == "loc"
        and (element.text or "").strip()
    ]
    if root_name == "sitemapindex":
        return [], locations
    if root_name == "urlset":
        return locations, []
    return [], []


async def fetch_document_pages(
    client: httpx.AsyncClient,
    urls: list[str],
    progress: Callable[[int, int, str], None] | None = None,
) -> list[DocumentPage]:
    semaphore = asyncio.Semaphore(8)
    progress_lock = asyncio.Lock()
    completed = 0

    async def fetch(url: str) -> DocumentPage | None:
        nonlocal completed
        async with semaphore:
            page = await fetch_document_page(client, url)
        async with progress_lock:
            completed += 1
            if progress:
                label = page.title if page else "Page unavailable"
                progress(
                    completed,
                    len(urls),
                    f"{completed} of {len(urls)} · {label}",
                )
        return page

    pages = await asyncio.gather(*(fetch(url) for url in urls))
    return [page for page in pages if page and len(page.text) >= 80]


async def fetch_document_page(
    client: httpx.AsyncClient,
    url: str,
) -> DocumentPage | None:
    normalized = _normalize_public_url(url)
    if not normalized:
        return None

    cached = _cached_document_page(normalized)
    if cached is not None:
        return cached[1]

    try:
        response = await client.get(normalized)
        response.raise_for_status()
    except Exception:
        _cache_document_page(normalized, None)
        return None

    final_url = _normalize_public_url(str(response.url))
    if not final_url:
        _cache_document_page(normalized, None)
        return None

    content_type = response.headers.get("content-type", "").lower()
    raw = response.text[:500_000]
    if "html" in content_type or "<html" in raw[:500].lower():
        parser = _ReadableHTMLParser()
        parser.feed(raw)
        title = " ".join(parser.title_parts).strip() or _title_from_url(final_url)
        parts = parser.main_parts or parser.body_parts
        text = "\n".join(parts)
        links = tuple((href, anchor_text) for href, anchor_text in parser.links if href)
    else:
        title = _title_from_url(final_url)
        text = raw
        links = ()

    page = DocumentPage(
        title=title[:160],
        url=final_url,
        text=text[:150_000],
        links=links,
    )
    _cache_document_page(normalized, page)
    return page


async def fetch_repository_readme(
    client: httpx.AsyncClient,
    repo: str,
) -> DocumentPage | None:
    try:
        response = await client.get(
            f"https://api.github.com/repos/{repo}/readme",
            headers={
                **_github_headers(),
                "Accept": "application/vnd.github.raw+json",
            },
        )
        response.raise_for_status()
    except Exception:
        return None

    return DocumentPage(
        title=f"{repo} README",
        url=f"https://github.com/{repo}#readme",
        text=response.text[:150_000],
        source_type="repo_readme",
    )


async def _fetch_repo_metadata(
    client: httpx.AsyncClient,
    repo: str,
) -> dict:
    try:
        response = await client.get(
            f"https://api.github.com/repos/{repo}",
            headers=_github_headers(),
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


async def _fetch_text(client: httpx.AsyncClient, url: str) -> str | None:
    normalized = _normalize_public_url(url)
    if not normalized:
        return None
    try:
        response = await client.get(normalized)
        response.raise_for_status()
    except Exception:
        return None
    return response.text[:2_000_000]


def _filter_document_urls(urls: list[str], docs_root: str) -> list[str]:
    parsed_root = urlparse(docs_root)
    root_origin = (parsed_root.scheme, parsed_root.netloc)
    scope, root_locale = _docs_scope(parsed_root.path)
    filtered: list[str] = []
    seen: set[str] = set()

    for url in urls:
        normalized = _normalize_public_url(url)
        if not normalized or normalized in seen:
            continue
        parsed = urlparse(normalized)
        if (parsed.scheme, parsed.netloc) != root_origin:
            continue
        if scope and not (
            parsed.path == scope or parsed.path.startswith(f"{scope.rstrip('/')}/")
        ):
            continue
        suffix = _path_suffix(parsed.path)
        if suffix in _NON_DOCUMENT_EXTENSIONS:
            continue
        candidate_locale = _locale_after_scope(parsed.path, scope)
        if candidate_locale and candidate_locale != root_locale:
            continue
        seen.add(normalized)
        filtered.append(normalized)
        if len(filtered) >= MAX_DOCUMENT_URLS:
            break

    return filtered


def _docs_scope(path: str) -> tuple[str, str | None]:
    segments = [segment for segment in path.split("/") if segment]
    if "docs" in segments:
        index = segments.index("docs")
        scope_segments = segments[: index + 1]
        locale = None
        if (
            len(segments) > index + 1
            and segments[index + 1].lower() in _LOCALE_SEGMENTS
        ):
            locale = segments[index + 1].lower()
            scope_segments.append(segments[index + 1])
        return f"/{'/'.join(scope_segments)}", locale
    if path and path != "/":
        return path.rstrip("/"), None
    return "", None


def _locale_after_scope(path: str, scope: str) -> str | None:
    if not scope:
        return None
    remainder = path[len(scope) :].strip("/")
    if not remainder:
        return None
    first = remainder.split("/", 1)[0].lower()
    return first if first in _LOCALE_SEGMENTS else None


def _normalize_public_url(url: str) -> str | None:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return None
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
    ):
        return None
    clean, _ = urldefrag(urlunparse(parsed._replace(query="")))
    return clean.rstrip("/") or clean


def _extract_markdown_links(markdown: str) -> list[tuple[str, str]]:
    links = [
        (match.group(1), match.group(2))
        for match in re.finditer(
            r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
            markdown,
        )
    ]
    linked_urls = {url for _, url in links}
    links.extend(
        ("", match.group(0).rstrip(".,"))
        for match in re.finditer(r"(?<!\()https?://[^\s<>)]+", markdown)
        if match.group(0).rstrip(".,") not in linked_urls
    )
    return list(dict.fromkeys(links))


def _docs_url_score(url: str) -> int:
    normalized = _normalize_public_url(url)
    if not normalized:
        return 0
    parsed = urlparse(normalized)
    score = 0
    if parsed.hostname and parsed.hostname.startswith("docs."):
        score += 100
    if "/docs" in parsed.path.lower():
        score += 90
    if "documentation" in parsed.path.lower():
        score += 80
    return score


def _looks_like_docs_page(url: str, page: DocumentPage) -> bool:
    parsed = urlparse(url)
    text = f"{page.title} {page.text[:2000]}".lower()
    return (
        (parsed.hostname is not None and parsed.hostname.startswith("docs."))
        or "/docs" in parsed.path.lower()
        or "documentation" in text
        or "on this page" in text
    )


def _github_headers() -> dict[str, str]:
    settings = get_settings()
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "docshound",
    }
    token = get_github_api_token() or settings.github_token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _title_from_url(url: str) -> str:
    parsed = urlparse(url)
    slug = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    return (slug or parsed.netloc).replace("-", " ").replace("_", " ").title()


def _path_suffix(path: str) -> str:
    leaf = path.rstrip("/").rsplit("/", 1)[-1]
    if "." not in leaf:
        return ""
    return f".{leaf.rsplit('.', 1)[-1].lower()}"
