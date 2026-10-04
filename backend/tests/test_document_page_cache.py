import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx

from app.tools import docs_discovery
from app.tools.docs_discovery import PAGE_CACHE_TTL_SECONDS, fetch_document_page


class DocumentPageCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        docs_discovery._PAGE_CACHE.clear()
        self.clock = Mock(return_value=1_000)
        clock = patch(
            "app.tools.docs_discovery.time", SimpleNamespace(monotonic=self.clock)
        )
        clock.start()
        self.addCleanup(clock.stop)
        limit = patch.object(docs_discovery, "PAGE_CACHE_MAX_ENTRIES", 3, create=True)
        limit.start()
        self.addCleanup(limit.stop)

    async def test_successes_and_failures_share_a_bounded_cache(self):
        def handler(request):
            index = int(request.url.path.rsplit("/", 1)[-1])
            return httpx.Response(200 if index % 2 == 0 else 503, text="Documentation")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            for index in range(9):
                await fetch_document_page(client, f"https://8.8.8.8/docs/{index}")
                self.assertLessEqual(len(docs_discovery._PAGE_CACHE), 3)
        self.assertEqual(
            list(docs_discovery._PAGE_CACHE),
            [f"https://8.8.8.8/docs/{index}" for index in (6, 7, 8)],
        )
        self.assertIsNone(docs_discovery._PAGE_CACHE["https://8.8.8.8/docs/7"][1])

    async def test_hits_preserve_recent_pages_and_evict_the_least_recently_used(self):
        requested = []

        def handler(request):
            requested.append(request.url.path)
            return httpx.Response(200, text="Documentation")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            for index in (0, 1, 2, 0, 3, 0):
                await fetch_document_page(client, f"https://8.8.8.8/docs/{index}")
            self.assertEqual(requested, ["/docs/0", "/docs/1", "/docs/2", "/docs/3"])
            self.assertNotIn("https://8.8.8.8/docs/1", docs_discovery._PAGE_CACHE)
            await fetch_document_page(client, "https://8.8.8.8/docs/1")
        self.assertEqual(requested[-1], "/docs/1")
        self.assertEqual(len(requested), 5)
        self.assertEqual(len(docs_discovery._PAGE_CACHE), 3)

    async def test_a_new_lookup_removes_all_expired_entries(self):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text="Documentation")
            )
        ) as client:
            for index in range(3):
                await fetch_document_page(client, f"https://8.8.8.8/docs/{index}")
            self.clock.return_value += PAGE_CACHE_TTL_SECONDS
            await fetch_document_page(client, "https://8.8.8.8/docs/fresh")
        self.assertEqual(
            list(docs_discovery._PAGE_CACHE), ["https://8.8.8.8/docs/fresh"]
        )

    async def test_hits_do_not_extend_the_existing_freshness_ttl(self):
        requested = []

        def handler(request):
            requested.append(request.url.path)
            return httpx.Response(200, text=f"Documentation revision {len(requested)}")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first = await fetch_document_page(client, "https://8.8.8.8/docs/reference")
            self.clock.return_value += PAGE_CACHE_TTL_SECONDS - 1
            cached = await fetch_document_page(client, "https://8.8.8.8/docs/reference")
            self.clock.return_value += 1
            refreshed = await fetch_document_page(
                client, "https://8.8.8.8/docs/reference"
            )
        self.assertIs(cached, first)
        self.assertNotEqual(refreshed.text, first.text)
        self.assertEqual(len(requested), 2)

    async def test_failure_retry_ttl_remains_unchanged(self):
        requested = []

        def handler(request):
            requested.append(request.url.path)
            return httpx.Response(
                503 if len(requested) == 1 else 200, text="Documentation"
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first = await fetch_document_page(client, "https://8.8.8.8/docs/reference")
            self.clock.return_value += PAGE_CACHE_TTL_SECONDS - 1
            cached = await fetch_document_page(client, "https://8.8.8.8/docs/reference")
            self.clock.return_value += 1
            refreshed = await fetch_document_page(
                client, "https://8.8.8.8/docs/reference"
            )
        self.assertIsNone(first)
        self.assertIsNone(cached)
        self.assertIsNotNone(refreshed)
        self.assertEqual(len(requested), 2)


if __name__ == "__main__":
    unittest.main()
