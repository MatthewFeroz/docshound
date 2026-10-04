import base64
import json
import tempfile
import unittest
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import httpx2 as httpx

from app import approved_documents, documentation_prs
from app.approved_documents import ApprovedDocument, save_approved_document
from app.documentation_prs import (
    StaleDocumentationPreviewError,
    create_documentation_pull_request,
    get_documentation_change,
    invalidate_documentation_preview,
    prepare_documentation_change,
    save_documentation_change,
)

RUN_ID = "run12345-aaaa-bbbb-cccc-dddddddddddd"


class FakeGitHub:
    """A writable repository that remembers its branch, file, and pull request."""

    def __init__(self) -> None:
        self.branch_content: str | None = None
        self.pull_request: dict | None = None
        self.writes: list[dict] = []
        self.on_base_ref: Callable[[], None] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        payload = json.loads(request.content) if request.content else None
        if path == "/repos/acme/docs":
            return httpx.Response(
                200, json={"default_branch": "main", "permissions": {"push": True}}
            )
        if path == "/repos/acme/docs/git/trees/main":
            return httpx.Response(200, json={"tree": []})
        if path == "/repos/acme/docs/git/ref/heads/main":
            if self.on_base_ref:
                self.on_base_ref()
            return httpx.Response(200, json={"object": {"sha": "base-sha"}})
        if request.method == "POST" and path.endswith("/git/refs"):
            if self.branch_content is not None:
                return httpx.Response(422, json={"message": "Reference already exists"})
            return httpx.Response(201, json={"ref": payload["ref"]})
        if "/git/ref/heads/docshound" in path:
            return httpx.Response(200, json={"object": {"sha": "branch-sha"}})
        if request.method == "GET" and "/contents/" in path:
            if self.branch_content is None:
                return httpx.Response(404, json={"message": "Not Found"})
            encoded = base64.b64encode(self.branch_content.encode()).decode()
            return httpx.Response(200, json={"sha": "branch-file", "content": encoded})
        if request.method == "PUT" and "/contents/" in path:
            self.writes.append(payload)
            self.branch_content = base64.b64decode(payload["content"]).decode()
            return httpx.Response(201, json={"commit": {"sha": "commit-sha"}})
        if request.method == "POST" and path.endswith("/pulls"):
            if self.pull_request:
                return httpx.Response(422, json={"message": "A pull request exists"})
            self.pull_request = {
                "number": 87,
                "html_url": "https://github.com/acme/docs/pull/87",
            }
            return httpx.Response(201, json=self.pull_request)
        if request.method == "GET" and path.endswith("/pulls"):
            return httpx.Response(200, json=[self.pull_request])
        raise AssertionError(f"Unexpected request {request.method} {path}")


class PreviewFreshnessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_paths = (approved_documents.DB_PATH, documentation_prs.DB_PATH)
        db_path = Path(self.temp_dir.name) / "docshound.db"
        approved_documents.DB_PATH = db_path
        documentation_prs.DB_PATH = db_path
        self.token_patcher = patch(
            "app.documentation_prs.configured_github_token",
            return_value="connected-token",
        )
        self.token_patcher.start()
        self.github = FakeGitHub()

    def tearDown(self) -> None:
        self.token_patcher.stop()
        approved_documents.DB_PATH, documentation_prs.DB_PATH = self.original_paths
        self.temp_dir.cleanup()

    def approve(self, markdown: str) -> ApprovedDocument:
        """Mirror the approval route: save the revision, then discard stale previews."""
        document = save_approved_document(
            run_id=RUN_ID,
            gap_index=0,
            repo="acme/product",
            title="Configure retries",
            summary="Use bounded retries.",
            markdown_source=markdown,
            source_issues=[],
        )
        invalidate_documentation_preview(document)
        return document

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(self.github),
        )

    async def preview(self, document: ApprovedDocument):
        async with self.client() as client:
            return await prepare_documentation_change(
                document, target_repo="acme/docs", client=client
            )

    async def publish(self, document: ApprovedDocument, change):
        async with self.client() as client:
            return await create_documentation_pull_request(
                document, change, client=client
            )

    async def test_changed_approval_discards_the_unpublished_preview(self) -> None:
        first = self.approve("# Retries\n\nUse three attempts.")
        stale = await self.preview(first)

        revised = self.approve("# Retries\n\nUse five attempts.")

        self.assertIsNone(get_documentation_change(revised.slug))
        with self.assertRaises(StaleDocumentationPreviewError):
            await self.publish(revised, stale)
        self.assertEqual(self.github.writes, [])

    async def test_unchanged_approval_keeps_the_preview(self) -> None:
        document = self.approve("# Retries\n\nUse three attempts.")
        change = await self.preview(document)

        self.approve("# Retries\n\nUse three attempts.")

        self.assertEqual(get_documentation_change(document.slug), change)

    async def test_edited_document_updates_the_existing_pull_request(self) -> None:
        first = self.approve("# Retries\n\nUse three attempts.")
        created = await self.publish(first, await self.preview(first))
        self.assertEqual(created.status, "created")

        revised = self.approve("# Retries\n\nUse five attempts.")
        self.assertEqual(get_documentation_change(revised.slug), created)
        with self.assertRaises(StaleDocumentationPreviewError):
            await self.publish(revised, created)

        refreshed = await self.preview(revised)
        self.assertEqual(refreshed.status, "preview_ready")
        self.assertEqual(refreshed.pr_number, 87)

        updated = await self.publish(revised, refreshed)

        self.assertEqual(updated.status, "created")
        self.assertEqual(updated.pr_number, 87)
        self.assertIn("Use five attempts.", self.github.branch_content)
        self.assertEqual(self.github.writes[-1]["sha"], "branch-file")
        stored = get_documentation_change(revised.slug)
        self.assertEqual(
            (stored.status, stored.pr_number, stored.document_fingerprint),
            ("created", 87, updated.document_fingerprint),
        )

    async def test_approval_during_publication_stops_before_the_write(self) -> None:
        first = self.approve("# Retries\n\nUse three attempts.")
        change = await self.preview(first)
        self.github.on_base_ref = lambda: self.approve(
            "# Retries\n\nUse five attempts."
        )

        with self.assertRaises(StaleDocumentationPreviewError):
            await self.publish(first, change)

        self.assertEqual(self.github.writes, [])
        self.assertIsNone(get_documentation_change(first.slug))

    async def test_preview_without_a_revision_requires_a_fresh_preview(self) -> None:
        document = self.approve("# Retries\n\nUse three attempts.")
        change = replace(await self.preview(document), document_fingerprint=None)
        save_documentation_change(change)

        with self.assertRaises(StaleDocumentationPreviewError):
            await self.publish(document, change)
        self.assertEqual(self.github.writes, [])


if __name__ == "__main__":
    unittest.main()
