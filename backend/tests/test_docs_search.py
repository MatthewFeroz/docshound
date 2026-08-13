import base64
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.langgraph_agent import _safe_next_action
from app.state import DocumentationCoverage, GapCluster
from app.tools.cluster import draft_review_documents
from app.tools.docs import search_official_docs


class DocumentationSearchTests(unittest.IsolatedAsyncioTestCase):
    async def _search_pages(
        self,
        pages: dict[str, str],
        cluster: GapCluster,
    ) -> tuple[list[GapCluster], list[str]]:
        requested_paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/repos/acme/opencode":
                return httpx.Response(200, json={"default_branch": "main"})
            if request.url.path == "/repos/acme/opencode/git/trees/main":
                return httpx.Response(
                    200,
                    json={
                        "tree": [
                            {"path": path, "type": "blob", "sha": str(index)}
                            for index, path in enumerate(pages)
                        ]
                    },
                )
            prefix = "/repos/acme/opencode/contents/"
            if request.url.path.startswith(prefix):
                path = request.url.path.removeprefix(prefix)
                requested_paths.append(path)
                return httpx.Response(
                    200,
                    json={
                        "content": base64.b64encode(pages[path].encode()).decode()
                    },
                )
            return httpx.Response(404, json={"message": "not found"})

        async with httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            with (
                patch(
                    "app.tools.docs.get_settings",
                    return_value=SimpleNamespace(github_token=None),
                ),
                patch("app.tools.docs.llm_is_configured", return_value=False),
            ):
                clusters, _sources = await search_official_docs(
                    "acme/opencode",
                    None,
                    [cluster],
                    client=client,
                )
        return clusters, requested_paths

    async def test_search_ranks_relevant_repository_page_per_finding(self) -> None:
        pages = {
            "packages/web/src/content/docs/tui.mdx": (
                "---\ntitle: Terminal UI\n---\n\n"
                "# Terminal UI\n\nUse keyboard commands to control the terminal interface."
            ),
            "packages/web/src/content/docs/providers.mdx": (
                "# Providers\n\nConfigure model providers and credentials."
            ),
            "README.md": "# OpenCode\n\nAn AI coding agent.",
        }

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/repos/acme/opencode":
                return httpx.Response(200, json={"default_branch": "main"})
            if request.url.path == "/repos/acme/opencode/git/trees/main":
                return httpx.Response(
                    200,
                    json={
                        "tree": [
                            {"path": path, "type": "blob", "sha": str(index)}
                            for index, path in enumerate(pages)
                        ]
                    },
                )
            prefix = "/repos/acme/opencode/contents/"
            if request.url.path.startswith(prefix):
                path = request.url.path.removeprefix(prefix)
                return httpx.Response(
                    200,
                    json={
                        "content": base64.b64encode(pages[path].encode()).decode()
                    },
                )
            return httpx.Response(404, json={"message": "not found"})

        cluster = GapCluster(
            name="Terminal UI keyboard commands",
            summary="Users need a clearer terminal interface command reference.",
            recurring_question="How do I control the terminal UI with keyboard commands?",
            issue_numbers=[12],
            severity="medium",
            confidence=0.9,
        )
        async with httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            with (
                patch(
                    "app.tools.docs.get_settings",
                    return_value=SimpleNamespace(github_token=None),
                ),
                patch("app.tools.docs.llm_is_configured", return_value=False),
            ):
                clusters, sources = await search_official_docs(
                    "acme/opencode",
                    None,
                    [cluster],
                    client=client,
                )

        coverage = clusters[0].documentation_coverage
        self.assertIsNotNone(coverage)
        self.assertEqual(coverage.status, "partial")
        self.assertEqual(coverage.recommended_action, "update_page")
        self.assertEqual(
            coverage.recommended_path,
            "packages/web/src/content/docs/tui.mdx",
        )
        self.assertEqual(sources[0].repository_path, coverage.recommended_path)

    async def test_prefers_canonical_page_over_translated_duplicate(self) -> None:
        pages = {
            "packages/web/src/content/docs/plugins.mdx": (
                "# Plugins\n\nConfigure and activate plugins in the terminal UI."
            ),
            "packages/web/src/content/docs/ar/plugins.mdx": (
                "# الإضافات\n\nتكوين الإضافات في واجهة المستخدم الطرفية."
            ),
            "README.md": "# OpenCode\n\nAn AI coding agent.",
        }
        cluster = GapCluster(
            name="Plugin activation persistence",
            summary="Plugin activation should persist across terminal UI sessions.",
            recurring_question="How are plugins activated and disabled?",
            issue_numbers=[12],
            severity="medium",
            confidence=0.8,
        )

        clusters, requested_paths = await self._search_pages(pages, cluster)

        coverage = clusters[0].documentation_coverage
        self.assertIsNotNone(coverage)
        self.assertEqual(
            coverage.recommended_path,
            "packages/web/src/content/docs/plugins.mdx",
        )
        self.assertNotIn(
            "packages/web/src/content/docs/ar/plugins.mdx",
            requested_paths,
        )

    async def test_excludes_unrelated_nested_readmes(self) -> None:
        pages = {
            "packages/web/src/content/docs/tools.mdx": (
                "# Tools\n\nThe shell tool returns command output to the model."
            ),
            "packages/opencode/src/sync/README.md": (
                "# Goal\n\nInternal synchronization architecture and output events."
            ),
            "packages/app/e2e/performance/README.md": (
                "# Manual app performance suite\n\nMeasure shell rendering output."
            ),
            "README.md": "# OpenCode\n\nAn AI coding agent.",
        }
        cluster = GapCluster(
            name="Shell tool output truncation",
            summary="Long shell output can be truncated incorrectly.",
            recurring_question="How does the shell tool truncate long output?",
            issue_numbers=[12],
            severity="high",
            confidence=0.8,
        )

        clusters, requested_paths = await self._search_pages(pages, cluster)

        coverage = clusters[0].documentation_coverage
        self.assertIsNotNone(coverage)
        self.assertEqual(
            coverage.recommended_path,
            "packages/web/src/content/docs/tools.mdx",
        )
        self.assertNotIn("packages/opencode/src/sync/README.md", requested_paths)
        self.assertNotIn(
            "packages/app/e2e/performance/README.md",
            requested_paths,
        )

    async def test_documented_finding_is_kept_without_creating_a_draft(self) -> None:
        cluster = GapCluster(
            name="Authentication setup",
            summary="Token setup may need documentation.",
            recurring_question="How do I configure a token?",
            issue_numbers=[12],
            severity="medium",
            confidence=0.9,
            documentation_coverage=DocumentationCoverage(
                status="documented",
                rationale="The authentication page fully answers the question.",
                recommended_action="no_change",
            ),
        )
        with patch("app.tools.cluster.llm_is_configured", return_value=False):
            drafted = await draft_review_documents([cluster], [], [])

        self.assertEqual(drafted[0].review_status, "no_change_needed")
        self.assertIsNone(drafted[0].draft_markdown)


class WorkflowOrderingTests(unittest.TestCase):
    def test_drafting_follows_documentation_search(self) -> None:
        self.assertEqual(
            _safe_next_action({"researched": True, "analyzed": True}),
            "search_docs",
        )
        self.assertEqual(
            _safe_next_action(
                {"researched": True, "analyzed": True, "docs_searched": True}
            ),
            "draft",
        )
        self.assertEqual(
            _safe_next_action(
                {
                    "researched": True,
                    "analyzed": True,
                    "docs_searched": True,
                    "drafted": True,
                }
            ),
            "store",
        )
        self.assertEqual(
            _safe_next_action(
                {
                    "researched": True,
                    "analyzed": True,
                    "docs_searched": True,
                    "errors": ["documentation search failed"],
                }
            ),
            "store",
        )


if __name__ == "__main__":
    unittest.main()
