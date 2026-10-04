"""Public website reads with DNS preflight, explicit redirects, and body limits."""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import ParseResult, urljoin, urlparse

import httpx

MAX_REDIRECTS = 3
FETCH_TIMEOUT_SECONDS = 12


@dataclass(frozen=True)
class PublicWebResponse:
    url: str
    text: str
    content_type: str


def public_url_parts(url: str) -> ParseResult:
    if any(ord(character) <= 32 or ord(character) == 127 for character in url):
        raise ValueError("Documentation URL cannot contain whitespace or controls")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Documentation URL must be an HTTP or HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Documentation URL cannot contain credentials")
    # Accessing port also rejects malformed or out-of-range ports before a request.
    parsed.port
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("Documentation URL must resolve to a public address")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not _is_public_address(address):
        raise ValueError("Documentation URL must resolve to a public address")
    return parsed


def _is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return address.is_global and not address.is_multicast


async def _resolve_addresses(hostname: str, port: int) -> list[str]:
    addresses = await asyncio.get_running_loop().getaddrinfo(
        hostname, port, type=socket.SOCK_STREAM
    )
    return [address[4][0] for address in addresses]


async def validate_public_url(url: str) -> None:
    """Reject nonpublic DNS answers; the HTTP transport still resolves separately."""
    parsed = public_url_parts(url)
    addresses = await _resolve_addresses(
        parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
    )
    if not addresses or any(
        not _is_public_address(ipaddress.ip_address(address)) for address in addresses
    ):
        raise ValueError("Documentation URL must resolve to a public address")


async def fetch_public_text(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int,
    html_only: bool = False,
    truncate: bool = False,
    user_agent: str = "DocsHound/1.0 documentation-reader",
) -> PublicWebResponse:
    current = url
    async with asyncio.timeout(FETCH_TIMEOUT_SECONDS):
        for _ in range(MAX_REDIRECTS + 1):
            await validate_public_url(current)
            request = client.build_request(
                "GET", current, timeout=FETCH_TIMEOUT_SECONDS
            )
            # Supplied clients may have GitHub credentials, cookies, or default params.
            request.url = type(request.url)(current)
            request.headers.clear()
            request.headers.update(
                {
                    "Host": request.url.netloc.decode("ascii"),
                    "User-Agent": user_agent,
                    "Accept": "*/*",
                    "Accept-Encoding": "identity",
                }
            )
            response = await client.send(
                request, auth=None, follow_redirects=False, stream=True
            )
            try:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError(
                            "Documentation site returned an empty redirect"
                        )
                    current = urljoin(str(response.url), location)
                    continue
                response.raise_for_status()
                encoding = response.headers.get("content-encoding", "").strip().lower()
                if encoding not in {"", "identity"}:
                    # HTTPX can expand a compressed chunk before our decoded-byte limit.
                    raise ValueError(
                        "Documentation response used unexpected content encoding"
                    )
                content_type = response.headers.get("content-type", "").lower()
                if (
                    html_only
                    and content_type
                    and not any(
                        item in content_type
                        for item in ("text/html", "application/xhtml+xml")
                    )
                ):
                    raise ValueError("Documentation URL did not return HTML")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes(chunk_size=16_384):
                    remaining = max_bytes - size
                    if len(chunk) > remaining:
                        if not truncate:
                            raise ValueError(
                                "Documentation response exceeded the size limit"
                            )
                        chunks.append(chunk[:remaining])
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if truncate and size == max_bytes:
                        break
                text = b"".join(chunks).decode(response.encoding or "utf-8", "replace")
                return PublicWebResponse(str(response.url), text, content_type)
            finally:
                await response.aclose()
    raise ValueError("Documentation site redirected too many times")
