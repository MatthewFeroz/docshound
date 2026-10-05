import asyncio
import unittest
from unittest.mock import patch

import httpx2 as httpx

from app.tools.github import GitHubToolError, validate_github_access


class GitHubAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_validates_activity_and_documentation_permissions(self) -> None:
        requested_paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested_paths.append(request.url.path)
            self.assertEqual(request.headers["authorization"], "Bearer github-token")
            payloads = {
                "/user": {"login": "octocat"},
                "/repos/acme/product": {
                    "full_name": "acme/product",
                    "default_branch": "main",
                },
                "/repos/acme/product/issues": [],
                "/repos/acme/product/pulls": [],
                "/repos/acme/product/git/trees/main": {"tree": []},
            }
            payload = payloads.get(request.url.path)
            if payload is None:
                return httpx.Response(404, json={"message": "not found"})
            return httpx.Response(200, json=payload)

        async with httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            account, repo = await validate_github_access(
                "acme/product",
                "github-token",
                client=client,
            )

        self.assertEqual(account, "octocat")
        self.assertEqual(repo, "acme/product")
        self.assertEqual(
            requested_paths,
            [
                "/user",
                "/repos/acme/product",
                "/repos/acme/product/issues",
                "/repos/acme/product/pulls",
                "/repos/acme/product/git/trees/main",
            ],
        )

    async def test_reports_an_invalid_token_without_exposing_it(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"message": "bad credentials"})

        async with httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            with self.assertRaisesRegex(GitHubToolError, "rejected this token"):
                await validate_github_access(
                    "acme/product",
                    "github-token",
                    client=client,
                )

    async def test_repository_permission_reads_overlap_after_metadata(self):
        started = asyncio.Event()
        release = asyncio.Event()
        paths = []
        active = 0
        peak = 0

        async def handler(request):
            nonlocal active, peak
            path = request.url.path
            paths.append(path)
            if path == "/user":
                return httpx.Response(200, json={"login": "octocat"})
            if path == "/repos/acme/product":
                return httpx.Response(200, json={"default_branch": "release/stable"})
            self.assertEqual(paths[:2], ["/user", "/repos/acme/product"])
            active += 1
            peak = max(peak, active)
            if active == 3:
                started.set()
            try:
                await release.wait()
                return httpx.Response(200, json=[])
            finally:
                active -= 1

        async with httpx.AsyncClient(
            base_url="https://api.github.test", transport=httpx.MockTransport(handler)
        ) as client:
            task = asyncio.create_task(validate_github_access(
                "acme/product", "github-token", client=client
            ))
            try:
                await asyncio.wait_for(started.wait(), timeout=1)
                self.assertEqual(peak, 3)
                self.assertEqual(len(paths), 5)
                self.assertIn("/repos/acme/product/git/trees/release/stable", paths)
                release.set()
                self.assertEqual(await task, ("octocat", "acme/product"))
                self.assertEqual(active, 0)
                self.assertFalse(client.is_closed)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_permission_failure_cancels_and_awaits_other_reads_before_closing(self):
        started = asyncio.Event()
        active = set()
        cancelled = set()

        async def handler(request):
            path = request.url.path
            if path == "/user":
                return httpx.Response(200, json={"login": "octocat"})
            if path == "/repos/acme/product":
                return httpx.Response(200, json={"default_branch": "main"})
            active.add(path)
            if len(active) == 3:
                started.set()
            try:
                await started.wait()
                if path.endswith("/issues"):
                    return httpx.Response(403, json={"message": "denied"})
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.add(path)
                raise
            finally:
                active.remove(path)

        client = httpx.AsyncClient(
            base_url="https://api.github.test", transport=httpx.MockTransport(handler)
        )
        with patch("app.tools.github.httpx.AsyncClient", return_value=client):
            with self.assertRaisesRegex(GitHubToolError, "cannot read"):
                await asyncio.wait_for(validate_github_access(
                    "acme/product", "github-token"
                ), timeout=1)
        self.assertEqual(active, set())
        self.assertEqual(cancelled, {
            "/repos/acme/product/pulls", "/repos/acme/product/git/trees/main"
        })
        self.assertTrue(client.is_closed)

    async def test_caller_cancellation_drains_reads_and_keeps_supplied_client_open(self):
        started = asyncio.Event()
        active = 0
        cancelled = 0

        async def handler(request):
            nonlocal active, cancelled
            if request.url.path in {"/user", "/repos/acme/product"}:
                return httpx.Response(200, json={"login": "octocat", "default_branch": "main"})
            active += 1
            if active == 3:
                started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled += 1
                raise
            finally:
                active -= 1

        async with httpx.AsyncClient(
            base_url="https://api.github.test", transport=httpx.MockTransport(handler)
        ) as client:
            task = asyncio.create_task(validate_github_access(
                "acme/product", "github-token", client=client
            ))
            try:
                await asyncio.wait_for(started.wait(), timeout=1)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertEqual(active, 0)
            self.assertEqual(cancelled, 3)
            self.assertFalse(client.is_closed)


if __name__ == "__main__":
    unittest.main()
