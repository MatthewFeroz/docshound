import asyncio
import gzip
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import httpx2

from app.source_resolver import _fetch_public_html
from app.tools import docs_discovery
from app.tools.docs_discovery import (
    _fetch_text,
    fetch_document_page,
    fetch_repository_readme,
)
from app.tools.public_web import MAX_REDIRECTS, fetch_public_text, validate_public_url


class TrackingStream(httpx.AsyncByteStream):
    def __init__(self, chunks=100, block=False):
        self.chunks = chunks
        self.block = block
        self.read_count = 0
        self.closed = False
        self.entered = asyncio.Event()

    async def __aiter__(self):
        for _ in range(self.chunks):
            self.read_count += 1
            self.entered.set()
            if self.block:
                await asyncio.Future()
            yield b"x" * 65_536

    async def aclose(self):
        self.closed = True


class ContentStream(httpx.AsyncByteStream):
    def __init__(self, content, chunk_size=65_536):
        self.content = content
        self.chunk_size = chunk_size
        self.read_count = 0
        self.closed = False

    async def __aiter__(self):
        for start in range(0, len(self.content), self.chunk_size):
            self.read_count += 1
            yield self.content[start : start + self.chunk_size]

    async def aclose(self):
        self.closed = True


class PublicWebTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        docs_discovery._PAGE_CACHE.clear()
        self.resolver = AsyncMock(return_value=["8.8.8.8"])
        resolver = patch("app.tools.public_web._resolve_addresses", self.resolver)
        resolver.start()
        self.addCleanup(resolver.stop)

    async def test_private_redirect_is_rejected_before_both_readers_send_it(self):
        for reader in (fetch_document_page, _fetch_text):
            with self.subTest(reader=reader.__name__):
                docs_discovery._PAGE_CACHE.clear()
                requested = []

                def handler(request):
                    requested.append(str(request.url))
                    return httpx.Response(
                        302, headers={"location": "http://127.0.0.1/internal"}
                    )

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler), follow_redirects=True
                ) as client:
                    self.assertIsNone(
                        await reader(client, "https://public.example/docs")
                    )
                self.assertEqual(requested, ["https://public.example/docs"])

    async def test_redirected_hostname_is_dns_checked_before_request(self):
        self.resolver.side_effect = lambda host, port: (
            ["10.0.0.1"] if host == "internal.example" else ["8.8.8.8"]
        )
        requested = []

        def handler(request):
            requested.append(str(request.url))
            return httpx.Response(
                302, headers={"location": "http://internal.example/metadata"}
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            self.assertIsNone(
                await _fetch_text(client, "https://public.example/robots.txt")
            )
        self.assertEqual(requested, ["https://public.example/robots.txt"])
        self.assertEqual(
            [call.args[0] for call in self.resolver.await_args_list],
            ["public.example", "internal.example"],
        )

    async def test_nonpublic_and_credential_urls_make_no_request(self):
        urls = (
            "http://127.0.0.1/internal",
            "http://10.0.0.1/docs",
            "http://169.254.169.254/metadata",
            "http://100.64.0.1/docs",
            "http://224.0.0.1/docs",
            "http://[::1]/docs",
            "http://[fc00::1]/docs",
            "http://localhost./docs",
            "https://user:password@public.example/docs",
            "https://@public.example/docs",
            "https://public.example:99999/docs",
            "file:///etc/passwd",
            "https://public.exa\nmple/docs",
        )
        for url in urls:
            with self.subTest(url=url):
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(
                        lambda request: self.fail("Unexpected request")
                    )
                ) as client:
                    self.assertIsNone(await fetch_document_page(client, url))
                    self.assertIsNone(await _fetch_text(client, url))
        self.resolver.assert_not_awaited()

    async def test_dns_failures_and_mixed_answers_fail_closed(self):
        for addresses in ([], ["8.8.8.8", "192.168.1.1"], ["::ffff:127.0.0.1"]):
            with self.subTest(addresses=addresses):
                self.resolver.return_value = addresses
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(
                        lambda request: self.fail("Unexpected request")
                    )
                ) as client:
                    self.assertIsNone(
                        await _fetch_text(client, "https://public.example/sitemap.xml")
                    )
        self.resolver.side_effect = OSError("DNS unavailable")
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: self.fail("Unexpected request")
            )
        ) as client:
            self.assertIsNone(
                await _fetch_text(client, "https://public.example/sitemap.xml")
            )

    async def test_public_http_https_and_relative_redirects_remain_available(self):
        requested = []

        def handler(request):
            requested.append(str(request.url))
            if request.url.path == "/docs":
                return httpx.Response(
                    302, headers={"location": "https://cdn.example/docs/start"}
                )
            if request.url.path == "/docs/start":
                return httpx.Response(301, headers={"location": "../guide"})
            return httpx.Response(200, text="Public documentation content.")

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=True
        ) as client:
            page = await fetch_document_page(client, "http://public.example/docs")
        self.assertEqual(page.url, "https://cdn.example/guide")
        self.assertEqual(page.text, "Public documentation content.")
        self.assertEqual(
            requested,
            [
                "http://public.example/docs",
                "https://cdn.example/docs/start",
                "https://cdn.example/guide",
            ],
        )

    async def test_default_auth_headers_cookies_and_params_are_not_sent_to_web(self):
        requested = []

        def handler(request):
            requested.append(request)
            return httpx.Response(200, text="Public documentation")

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            headers={"Authorization": "Bearer inherited", "X-Api-Key": "inherited"},
            auth=httpx.BasicAuth("user", "password"),
            cookies={"session": "inherited"},
            params={"api_key": "inherited"},
        ) as client:
            await fetch_public_text(
                client, "https://public.example/docs?topic=usage", max_bytes=100
            )
            self.assertEqual(client.headers["Authorization"], "Bearer inherited")
        self.assertEqual(
            str(requested[0].url), "https://public.example/docs?topic=usage"
        )
        self.assertNotIn("authorization", requested[0].headers)
        self.assertNotIn("cookie", requested[0].headers)
        self.assertNotIn("x-api-key", requested[0].headers)

    async def test_github_readme_keeps_its_authorization_after_public_fetch(self):
        requested = []

        def handler(request):
            requested.append(request)
            return httpx.Response(200, text="Documentation reference")

        with (
            patch(
                "app.tools.docs_discovery.get_settings",
                return_value=SimpleNamespace(github_token="github-token"),
            ),
            patch("app.tools.docs_discovery.get_github_api_token", return_value=None),
        ):
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            ) as client:
                await fetch_document_page(client, "https://public.example/docs")
                readme = await fetch_repository_readme(client, "acme/project")
        self.assertIsNotNone(readme)
        self.assertNotIn("authorization", requested[0].headers)
        self.assertEqual(requested[1].headers["authorization"], "Bearer github-token")

    async def test_oversized_streams_stop_early_and_close(self):
        for reader in (fetch_document_page, _fetch_text):
            with self.subTest(reader=reader.__name__):
                docs_discovery._PAGE_CACHE.clear()
                stream = TrackingStream()
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(
                        lambda request: httpx.Response(200, stream=stream)
                    )
                ) as client:
                    result = await reader(client, "https://public.example/docs")
                    if reader is fetch_document_page:
                        self.assertEqual(result.text, "x" * 150_000)
                    else:
                        self.assertIsNone(result)
                self.assertTrue(stream.closed)
                self.assertLess(stream.read_count, stream.chunks)
                self.assertLessEqual(
                    stream.read_count, 31 if reader is _fetch_text else 8
                )

    async def test_unexpected_compression_is_rejected_before_body_expansion(self):
        compressed = gzip.compress(b"x" * (8 * 1024 * 1024))
        for reader in (fetch_document_page, _fetch_text):
            with self.subTest(reader=reader.__name__):
                docs_discovery._PAGE_CACHE.clear()
                stream = ContentStream(compressed)

                def handler(request):
                    self.assertEqual(request.headers["accept-encoding"], "identity")
                    return httpx.Response(
                        200, headers={"content-encoding": "gzip"}, stream=stream
                    )

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as client:
                    self.assertIsNone(
                        await reader(client, "https://public.example/docs")
                    )
                self.assertEqual(stream.read_count, 0)
                self.assertTrue(stream.closed)

    async def test_large_html_retains_a_usable_prefix_without_reading_the_remainder(
        self,
    ):
        content = (
            b"<html><title>Reference</title><main>Starting documentation steps. "
            + b"Reference material. " * 60_000
            + b"</main></html>"
        )
        stream = ContentStream(content)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, headers={"content-type": "text/html"}, stream=stream
                )
            )
        ) as client:
            page = await fetch_document_page(client, "https://public.example/docs")
        self.assertEqual(page.title, "Reference")
        self.assertTrue(page.text.startswith("Starting documentation steps."))
        self.assertEqual(len(page.text), 150_000)
        self.assertEqual(stream.read_count, 8)
        self.assertTrue(stream.closed)

    async def test_redirect_loop_is_bounded_and_closes_each_response(self):
        streams = []

        def handler(request):
            stream = TrackingStream()
            streams.append(stream)
            return httpx.Response(302, headers={"location": "/docs"}, stream=stream)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=True
        ) as client:
            self.assertIsNone(await _fetch_text(client, "https://public.example/docs"))
        self.assertEqual(len(streams), MAX_REDIRECTS + 1)
        self.assertTrue(
            all(stream.closed and stream.read_count == 0 for stream in streams)
        )

    async def test_cancellation_closes_active_stream_and_propagates(self):
        stream = TrackingStream(block=True)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, stream=stream)
            )
        ) as client:
            task = asyncio.create_task(
                fetch_document_page(client, "https://public.example/docs")
            )
            await stream.entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(stream.closed)
        self.assertNotIn("https://public.example/docs", docs_discovery._PAGE_CACHE)

    async def test_source_resolver_uses_the_same_guard_with_httpx2(self):
        requested = []

        def handler(request):
            requested.append(str(request.url))
            if request.url.path == "/docs":
                return httpx2.Response(302, headers={"location": "/guide"})
            return httpx2.Response(
                200,
                headers={"content-type": "text/html"},
                text="<html>Public docs</html>",
            )

        client = httpx2.AsyncClient(
            transport=httpx2.MockTransport(handler), follow_redirects=True
        )
        with patch("app.source_resolver.httpx.AsyncClient", return_value=client):
            html, url = await _fetch_public_html("https://public.example/docs")
        self.assertEqual(html, "<html>Public docs</html>")
        self.assertEqual(url, "https://public.example/guide")
        self.assertEqual(len(requested), 2)

    async def test_source_resolver_rejects_non_html_and_private_dns(self):
        client = httpx2.AsyncClient(
            transport=httpx2.MockTransport(
                lambda request: httpx2.Response(200, json={})
            )
        )
        with patch("app.source_resolver.httpx.AsyncClient", return_value=client):
            with self.assertRaisesRegex(ValueError, "did not return HTML"):
                await _fetch_public_html("https://public.example/docs")
        self.resolver.return_value = ["10.0.0.1"]
        with self.assertRaisesRegex(ValueError, "public address"):
            await validate_public_url("https://internal.example/docs")

    async def test_nat64_addresses_are_checked_by_their_embedded_ipv4(self):
        self.resolver.return_value = ["64:ff9b::a9fe:a9fe"]
        with self.assertRaisesRegex(ValueError, "public address"):
            await validate_public_url("https://metadata.example/latest")
        self.resolver.return_value = ["64:ff9b::808:808"]
        await validate_public_url("https://public.example/docs")


if __name__ == "__main__":
    unittest.main()
