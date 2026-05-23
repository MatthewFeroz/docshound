from urllib.parse import urlparse

import httpx

from app.state import DocSource, GapCluster


async def search_official_docs(
    repo: str,
    docs_url: str | None,
    clusters: list[GapCluster],
) -> list[DocSource]:
    sources: list[DocSource] = []
    if docs_url:
        sources.extend(await _fetch_docs_url(docs_url, clusters))

    owner, name = repo.split("/", 1)
    sources.append(
        DocSource(
            title=f"{repo} GitHub README",
            url=f"https://github.com/{owner}/{name}",
            snippet=(
                "Repository README and project metadata are treated as first-party "
                "documentation evidence for the agent's gap analysis."
            ),
            source_type="repo_readme",
            confidence=0.75,
        )
    )
    return sources[:8]


async def _fetch_docs_url(
    docs_url: str, clusters: list[GapCluster]
) -> list[DocSource]:
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
            response = await client.get(
                docs_url,
                headers={"User-Agent": "docs-gap-agent-hackathon"},
            )
        response.raise_for_status()
    except Exception as exc:
        return [
            DocSource(
                title="Official docs source unavailable",
                url=docs_url,
                snippet=f"The configured docs URL could not be fetched: {exc}",
                source_type="official_docs_error",
                confidence=0.25,
            )
        ]

    text = " ".join(response.text.split())
    parsed = urlparse(str(response.url))
    title = parsed.netloc or docs_url
    if "<title>" in response.text.lower():
        lower = response.text.lower()
        start = lower.find("<title>")
        end = lower.find("</title>", start)
        if start != -1 and end != -1:
            title = response.text[start + 7 : end].strip()[:120] or title

    gap_terms = ", ".join(cluster.name for cluster in clusters[:3])
    snippet = text[:600]
    if gap_terms:
        snippet = f"Configured first-party docs source for gaps: {gap_terms}. {snippet}"

    return [
        DocSource(
            title=title,
            url=str(response.url),
            snippet=snippet,
            source_type="official_docs",
            confidence=0.85,
        )
    ]
