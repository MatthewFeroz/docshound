import base64
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx2 as httpx

from app import documentation_prs, run_store
from app.approved_documents import ApprovedDocument
from app.documentation_prs import (
    create_documentation_pull_request,
    prepare_documentation_change,
)
from app.state import AgentState, GapCluster


class DocumentationFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_change_db = documentation_prs.DB_PATH
        documentation_prs.DB_PATH = Path(self.temp_dir.name) / "changes.db"
        self.configured_token_patcher = patch(
            "app.documentation_prs.configured_github_token",
            return_value=None,
        )
        self.configured_token = self.configured_token_patcher.start()
        self.document = ApprovedDocument(
            slug="retry-guide-run12345-1",
            run_id="run12345-aaaa-bbbb-cccc-dddddddddddd",
            gap_index=0,
            repo="acme/product",
            title="Configure reliable retries",
            summary="Use bounded retries for transient requests.",
            markdown=(
                "# Configure reliable retries\n\n"
                "## What changed\n\nUse three bounded attempts.\n\n"
                "## Sources\n\n- [Merged PR #42](https://example.com/pr/42)"
            ),
            source_issues=[
                {
                    "number": 42,
                    "title": "Add bounded retries",
                    "url": "https://example.com/pr/42",
                    "kind": "pull_request",
                }
            ],
            approved_at="2026-07-15T00:00:00+00:00",
            updated_at="2026-07-15T00:00:00+00:00",
        )

    def tearDown(self) -> None:
        self.configured_token_patcher.stop()
        documentation_prs.DB_PATH = self.original_change_db
        self.temp_dir.cleanup()

    def test_write_enabled_uses_the_connected_token(self) -> None:
        self.assertFalse(documentation_prs.write_enabled())
        self.configured_token.return_value = "connected-token"
        self.assertTrue(documentation_prs.write_enabled())

    async def test_prepare_detects_mdx_repository_and_builds_patch(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/repos/acme/docs":
                return httpx.Response(200, json={"default_branch": "main"})
            if request.url.path == "/repos/acme/docs/git/trees/main":
                return httpx.Response(
                    200,
                    json={
                        "tree": [
                            {"path": "docs.json", "type": "blob", "sha": "config"},
                            {
                                "path": "guides/getting-started.mdx",
                                "type": "blob",
                                "sha": "guide",
                            },
                        ]
                    },
                )
            return httpx.Response(404, json={"message": "not found"})

        async with httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            change = await prepare_documentation_change(
                self.document,
                target_repo="acme/docs",
                client=client,
            )

        self.assertEqual(change.base_branch, "main")
        self.assertEqual(
            change.file_path,
            "guides/configure-reliable-retries.mdx",
        )
        self.assertEqual(change.file_format, "mdx")
        self.assertIn('title: "Configure reliable retries"', change.content)
        self.assertNotIn("## Sources", change.content)
        self.assertTrue(change.patch.startswith("--- /dev/null"))

    async def test_connected_token_creates_branch_commit_and_pull_request(
        self,
    ) -> None:
        requests: list[tuple[str, str, dict | None]] = []
        self.configured_token.return_value = "connected-token"

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content) if request.content else None
            requests.append((request.method, request.url.path, payload))
            if request.url.path == "/repos/acme/docs":
                return httpx.Response(
                    200,
                    json={
                        "default_branch": "main",
                        "permissions": {"push": True},
                    },
                )
            if request.url.path == "/repos/acme/docs/git/trees/main":
                return httpx.Response(
                    200,
                    json={
                        "tree": [
                            {"path": "docs.json", "type": "blob", "sha": "config"},
                            {
                                "path": "guides/start.mdx",
                                "type": "blob",
                                "sha": "start",
                            },
                        ]
                    },
                )
            if request.method == "GET" and "/git/ref/heads/main" in request.url.path:
                return httpx.Response(200, json={"object": {"sha": "base-sha"}})
            if request.method == "POST" and request.url.path.endswith("/git/refs"):
                return httpx.Response(201, json={"ref": payload["ref"]})
            if request.method == "PUT" and "/contents/" in request.url.path:
                return httpx.Response(201, json={"commit": {"sha": "commit-sha"}})
            if request.method == "POST" and request.url.path.endswith("/pulls"):
                return httpx.Response(
                    201,
                    json={
                        "number": 87,
                        "html_url": "https://github.com/acme/docs/pull/87",
                    },
                )
            return httpx.Response(404, json={"message": "not found"})

        async with httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            change = await prepare_documentation_change(
                self.document,
                target_repo="acme/docs",
                client=client,
            )
            created = await create_documentation_pull_request(
                self.document,
                change,
                client=client,
            )

        self.assertEqual(created.status, "created")
        self.assertEqual(created.pr_number, 87)
        self.assertEqual(created.pr_url, "https://github.com/acme/docs/pull/87")
        branch_request = next(
            payload for method, path, payload in requests
            if method == "POST" and path.endswith("/git/refs")
        )
        self.assertEqual(branch_request["sha"], "base-sha")
        content_request = next(
            payload for method, path, payload in requests
            if method == "PUT" and "/contents/" in path
        )
        committed = base64.b64decode(content_request["content"]).decode("utf-8")
        self.assertEqual(committed, change.content)
        pull_request = next(
            payload for method, path, payload in requests
            if method == "POST" and path.endswith("/pulls")
        )
        self.assertEqual(pull_request["base"], "main")
        self.assertIn("Evidence", pull_request["body"])

    async def test_readable_upstream_recommends_writable_fork(self) -> None:
        self.configured_token.return_value = "connected-token"

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/repos/upstream/pi":
                return httpx.Response(
                    200,
                    json={
                        "full_name": "upstream/pi",
                        "default_branch": "main",
                        "permissions": {"push": False},
                    },
                )
            if request.url.path == "/user":
                return httpx.Response(200, json={"login": "matt"})
            if request.url.path == "/repos/matt/pi":
                return httpx.Response(
                    200,
                    json={
                        "full_name": "matt/pi",
                        "fork": True,
                        "parent": {"full_name": "upstream/pi"},
                        "source": {"full_name": "upstream/pi"},
                        "permissions": {"push": True},
                    },
                )
            return httpx.Response(404, json={"message": "not found"})

        async with httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            with self.assertRaisesRegex(
                documentation_prs.DocumentationPullRequestError,
                "Change Documentation repository to matt/pi",
            ) as raised:
                await prepare_documentation_change(
                    self.document,
                    target_repo="upstream/pi",
                    client=client,
                )

        message = str(raised.exception)
        self.assertIn("can read upstream/pi", message)
        self.assertIn("cannot publish there", message)
        self.assertIn("Contents: read/write", message)
        self.assertIn("Pull requests: read/write", message)
        self.assertIn("This attempt did not create a branch", message)

    async def test_branch_permission_error_explains_contents_access(self) -> None:
        self.configured_token.return_value = "connected-token"

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/repos/acme/docs":
                return httpx.Response(
                    200,
                    json={
                        "default_branch": "main",
                        "permissions": {"push": True},
                    },
                )
            if request.url.path == "/repos/acme/docs/git/trees/main":
                return httpx.Response(200, json={"tree": []})
            if request.method == "GET" and request.url.path.endswith(
                "/git/ref/heads/main"
            ):
                return httpx.Response(200, json={"object": {"sha": "base-sha"}})
            if request.method == "POST" and request.url.path.endswith("/git/refs"):
                return httpx.Response(403, json={"message": "Resource not accessible"})
            return httpx.Response(404, json={"message": "not found"})

        async with httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            change = await prepare_documentation_change(
                self.document,
                target_repo="acme/docs",
                client=client,
            )
            with self.assertRaises(
                documentation_prs.DocumentationPullRequestError
            ) as raised:
                await create_documentation_pull_request(
                    self.document,
                    change,
                    client=client,
                )

        message = str(raised.exception)
        self.assertIn("writing documentation to acme/docs", message)
        self.assertIn("Contents: read/write", message)
        self.assertIn("No pull request was created", message)

    async def test_pull_request_permission_error_explains_safe_retry(self) -> None:
        self.configured_token.return_value = "connected-token"

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/repos/acme/docs":
                return httpx.Response(
                    200,
                    json={
                        "default_branch": "main",
                        "permissions": {"push": True},
                    },
                )
            if request.url.path == "/repos/acme/docs/git/trees/main":
                return httpx.Response(200, json={"tree": []})
            if request.method == "GET" and request.url.path.endswith(
                "/git/ref/heads/main"
            ):
                return httpx.Response(200, json={"object": {"sha": "base-sha"}})
            if request.method == "POST" and request.url.path.endswith("/git/refs"):
                return httpx.Response(201, json={"ref": "refs/heads/docs"})
            if request.method == "PUT" and "/contents/" in request.url.path:
                return httpx.Response(201, json={"commit": {"sha": "commit-sha"}})
            if request.method == "POST" and request.url.path.endswith("/pulls"):
                return httpx.Response(403, json={"message": "Resource not accessible"})
            return httpx.Response(404, json={"message": "not found"})

        async with httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            change = await prepare_documentation_change(
                self.document,
                target_repo="acme/docs",
                client=client,
            )
            with self.assertRaises(
                documentation_prs.DocumentationPullRequestError
            ) as raised:
                await create_documentation_pull_request(
                    self.document,
                    change,
                    client=client,
                )

        message = str(raised.exception)
        self.assertIn("documentation branch was prepared", message)
        self.assertIn("Pull requests: read/write", message)
        self.assertIn("reuse the existing branch", message)

    async def test_update_preserves_existing_page_and_appends_focused_section(self) -> None:
        existing_page = (
            "---\ntitle: Reliability\n---\n\n"
            "# Reliability\n\nExisting guidance stays exactly as written.\n"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/repos/acme/docs":
                return httpx.Response(200, json={"default_branch": "main"})
            if request.url.path == "/repos/acme/docs/git/trees/main":
                return httpx.Response(
                    200,
                    json={
                        "tree": [
                            {
                                "path": "guides/reliability.mdx",
                                "type": "blob",
                                "sha": "existing-sha",
                            }
                        ]
                    },
                )
            if request.url.path.endswith("/contents/guides/reliability.mdx"):
                return httpx.Response(
                    200,
                    json={
                        "content": base64.b64encode(existing_page.encode()).decode()
                    },
                )
            return httpx.Response(404, json={"message": "not found"})

        async with httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            change = await prepare_documentation_change(
                self.document,
                target_repo="acme/docs",
                requested_path="guides/reliability.mdx",
                edit_action="update_page",
                client=client,
            )

        self.assertEqual(change.edit_action, "update_page")
        self.assertTrue(change.content.startswith(existing_page.rstrip()))
        self.assertIn("## Configure reliable retries", change.content)
        self.assertIn("Existing guidance stays exactly as written.", change.content)
        self.assertNotIn("-Existing guidance stays exactly as written.", change.patch)


class RunStoreTests(unittest.TestCase):
    def test_run_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original = run_store.DB_PATH
            run_store.DB_PATH = Path(temp_dir) / "runs.db"
            try:
                state = AgentState(
                    repo="acme/product",
                    status="completed",
                    clusters=[
                        GapCluster(
                            name="Retry behavior",
                            summary="Retries shipped.",
                            recurring_question="How do retries work?",
                            issue_numbers=[],
                            pr_numbers=[42],
                            finding_type="shipped_change",
                            severity="medium",
                            confidence=0.9,
                        )
                    ],
                    started_at=datetime.now(timezone.utc),
                )
                run_store.save_run(state)
                loaded = run_store.load_run(state.run_id)
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded.repo, "acme/product")
                self.assertEqual(loaded.clusters[0].pr_numbers, [42])
            finally:
                run_store.DB_PATH = original


if __name__ == "__main__":
    unittest.main()
