import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID

import httpx

from app.state import GapCluster
from app.tools import docs_discovery
from app.tools.docs_discovery import (
    DocumentPage,
    discover_document_urls,
    parse_sitemap_document,
)
from app.tools.docs_retrieval import rank_chunks_for_gaps


class _NoopTraceRun:
    trace_id = UUID("22222222-2222-2222-2222-222222222222")

    def end(self, outputs=None) -> None:
        return None


class _NoopTrace:
    def __init__(self, *args, **kwargs) -> None:
        self.run = _NoopTraceRun()

    async def __aenter__(self) -> _NoopTraceRun:
        return self.run

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


def _gap() -> GapCluster:
    return GapCluster(
        name="MCP server environment variables",
        summary="Users cannot tell how to pass environment variables to MCP servers.",
        recurring_question="How do I configure environment variables for an MCP server?",
        issue_numbers=[101, 102],
        severity="high",
        confidence=0.91,
    )


class SitemapDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        docs_discovery._PAGE_CACHE.clear()
        resolver = patch(
            "app.tools.public_web._resolve_addresses",
            AsyncMock(return_value=["8.8.8.8"]),
        )
        resolver.start()
        self.addCleanup(resolver.stop)

    def test_parses_urlsets_and_sitemap_indexes(self) -> None:
        page_urls, child_sitemaps = parse_sitemap_document(
            """
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url><loc>https://example.com/docs/config</loc></url>
            </urlset>
            """
        )
        self.assertEqual(page_urls, ["https://example.com/docs/config"])
        self.assertEqual(child_sitemaps, [])

        page_urls, child_sitemaps = parse_sitemap_document(
            """
            <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <sitemap><loc>https://example.com/docs-sitemap.xml</loc></sitemap>
            </sitemapindex>
            """
        )
        self.assertEqual(page_urls, [])
        self.assertEqual(
            child_sitemaps,
            ["https://example.com/docs-sitemap.xml"],
        )

    async def test_keeps_docs_scope_and_excludes_other_locales(self) -> None:
        sitemap = """
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://example.com/docs</loc></url>
          <url><loc>https://example.com/docs/configuration</loc></url>
          <url><loc>https://example.com/docs/zh-cn/configuration</loc></url>
          <url><loc>https://example.com/blog/launch</loc></url>
          <url><loc>https://other.example/docs/configuration</loc></url>
        </urlset>
        """

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(
                    200,
                    text="Sitemap: https://example.com/sitemap.xml",
                )
            if request.url.path == "/sitemap.xml":
                return httpx.Response(200, text=sitemap)
            return httpx.Response(404)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            urls = await discover_document_urls(
                client,
                "https://example.com/docs",
            )

        self.assertEqual(
            urls,
            [
                "https://example.com/docs",
                "https://example.com/docs/configuration",
            ],
        )

    async def test_uses_landing_navigation_when_no_sitemap_exists(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/docs":
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html"},
                    text="""
                    <html><title>Product documentation</title><main>
                      Product documentation and guides for configuring the system.
                      <a href="/docs/config">Configuration guide</a>
                      <a href="/blog/news">News</a>
                    </main></html>
                    """,
                )
            return httpx.Response(404)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            urls = await discover_document_urls(
                client,
                "https://example.com/docs",
            )

        self.assertEqual(
            urls,
            [
                "https://example.com/docs",
                "https://example.com/docs/config",
            ],
        )


class DocsRetrievalTests(unittest.TestCase):
    def test_ranks_the_relevant_page_for_each_gap(self) -> None:
        pages = [
            DocumentPage(
                title="MCP servers",
                url="https://example.com/docs/mcp-servers",
                text=(
                    "Configure an MCP server with a local command. Use the env "
                    "mapping to pass environment variables such as API tokens. "
                    "Each key is the variable name and each value is passed to "
                    "the server process when it starts."
                ),
            ),
            DocumentPage(
                title="Themes",
                url="https://example.com/docs/themes",
                text=(
                    "Choose a color theme, customize syntax highlighting, and "
                    "change the appearance of the application interface."
                ),
            ),
        ]

        ranked = rank_chunks_for_gaps([_gap()], pages)

        self.assertEqual(ranked[0][0].page.url, pages[0].url)
        self.assertIn("environment", ranked[0][0].matched_terms)


if __name__ == "__main__":
    unittest.main()
