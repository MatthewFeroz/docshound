import base64
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from app.langgraph_agent import _safe_next_action, llm_decide
from app.state import (
    DocumentationCoverage,
    DocumentationSource,
    GapCluster,
    PullRequest,
)
from app.tools.cluster import draft_review_documents
from app.tools.docs import search_official_docs


class DocumentationSearchTests(unittest.IsolatedAsyncioTestCase):
    async def _search_pages(
        self,
        pages: dict[str, str],
        cluster: GapCluster,
        *,
        authenticated: bool = False,
        documentation_source: DocumentationSource | None = None,
        activity_pull_requests: list[PullRequest] | None = None,
    ) -> tuple[list[GapCluster], list[str], list[str], int]:
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
                patch(
                    "app.tools.docs.get_github_api_token",
                    return_value="github-token" if authenticated else None,
                ),
                patch("app.tools.docs.llm_is_configured", return_value=False),
            ):
                clusters, sources, inspected_count = await search_official_docs(
                    "acme/opencode",
                    None,
                    [cluster],
                    documentation_source=documentation_source,
                    activity_pull_requests=activity_pull_requests,
                    client=client,
                )
        return (
            clusters,
            requested_paths,
            [source.repository_path or "" for source in sources],
            inspected_count,
        )

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
                clusters, sources, inspected_count = await search_official_docs(
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
        self.assertEqual(inspected_count, 3)

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

        clusters, requested_paths, _sources, _inspected_count = await self._search_pages(
            pages, cluster
        )

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
            ".repos/vendor/website/src/content/docs/tools.mdx": (
                "# Vendored tools\n\nDocumentation owned by an embedded repository."
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

        clusters, requested_paths, _sources, _inspected_count = await self._search_pages(
            pages, cluster
        )

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
        self.assertNotIn(
            ".repos/vendor/website/src/content/docs/tools.mdx",
            requested_paths,
        )

    async def test_authenticated_search_goes_deeper_per_finding(self) -> None:
        pages = {
            f"docs/retry-behavior-{index}.md": (
                f"# Retry behavior {index}\n\nConfigure retry attempts and backoff."
            )
            for index in range(14)
        }
        cluster = GapCluster(
            name="Retry behavior",
            summary="Retry attempts and backoff need documentation.",
            recurring_question="How do retry attempts work?",
            issue_numbers=[12],
            severity="medium",
            confidence=0.8,
        )

        _clusters, requested_paths, sources, inspected_count = await self._search_pages(
            pages,
            cluster,
            authenticated=True,
        )

        self.assertEqual(len(requested_paths), 14)
        self.assertEqual(len(sources), 8)
        self.assertEqual(inspected_count, 14)

    async def test_confirmed_small_docs_root_reads_the_complete_corpus(self) -> None:
        pages = {
            **{
                f"packages/coding-agent/docs/page-{index}.md": (
                    f"# Page {index}\n\nOfficial user guide content for topic {index}."
                )
                for index in range(30)
            },
            "packages/internal/README.md": "# Internal architecture",
        }
        cluster = GapCluster(
            name="Terminal session recovery",
            summary="Users need session recovery guidance.",
            recurring_question="How can a terminal session be recovered?",
            issue_numbers=[12],
            severity="medium",
            confidence=0.8,
        )
        source = DocumentationSource(
            repo="acme/opencode",
            root="packages/coding-agent/docs",
            confidence=0.97,
            discovered_by="readme_docs_link",
            page_count=30,
        )

        _clusters, requested_paths, _sources, inspected_count = await self._search_pages(
            pages,
            cluster,
            authenticated=True,
            documentation_source=source,
        )

        self.assertEqual(inspected_count, 30)
        self.assertEqual(len(requested_paths), 30)
        self.assertNotIn("packages/internal/README.md", requested_paths)

    async def test_active_demo_updates_its_researched_existing_target(self) -> None:
        target_path = "packages/web/src/content/docs/cli.mdx"
        pages = {
            target_path: "# CLI\n\nThe command-line reference.",
            "packages/web/src/content/docs/mcp-servers.mdx": (
                "# MCP servers\n\nConfigure local and remote MCP servers."
            ),
        }
        cluster = GapCluster(
            name="Non-interactive MCP registration",
            summary="The CLI can register a remote MCP server non-interactively.",
            recurring_question="How do I use opencode mcp add with flags?",
            issue_numbers=[42484],
            severity="medium",
            confidence=0.9,
        )
        source = DocumentationSource(
            repo="acme/opencode",
            root="packages/web/src/content/docs",
            confidence=0.99,
            discovered_by="user_override",
            page_count=2,
        )

        with patch(
            "app.tools.docs.documentation_target_path",
            return_value=target_path,
        ):
            clusters, _paths, sources, _count = await self._search_pages(
                pages,
                cluster,
                authenticated=True,
                documentation_source=source,
            )

        coverage = clusters[0].documentation_coverage
        self.assertEqual(coverage.status, "partial")
        self.assertEqual(coverage.recommended_action, "update_page")
        self.assertEqual(coverage.recommended_path, target_path)
        self.assertEqual(coverage.relevant_sources[0].repository_path, target_path)
        self.assertIn(target_path, sources)

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

    async def test_open_docs_pull_request_marks_finding_in_progress(self) -> None:
        source = DocumentationSource(
            repo="acme/opencode",
            root="docs",
            confidence=0.99,
            discovered_by="edit_on_github",
            page_count=1,
        )
        cluster = GapCluster(
            name="Authentication setup",
            summary="Token setup may need documentation.",
            recurring_question="How do I configure a token?",
            issue_numbers=[12],
            pr_numbers=[55],
            pr_refs=["acme/opencode#55"],
            severity="medium",
            confidence=0.9,
        )
        now = datetime.now(timezone.utc)
        pull_request = PullRequest(
            number=55,
            title="docs: add authentication guide",
            body="Adds the missing token setup steps.",
            url="https://github.com/acme/opencode/pull/55",
            state="open",
            created_at=now,
            updated_at=now,
            source_repo="acme/opencode",
        )

        clusters, _paths, _sources, _count = await self._search_pages(
            {"docs/overview.md": "# Overview\n\nGeneral product overview."},
            cluster,
            authenticated=True,
            documentation_source=source,
            activity_pull_requests=[pull_request],
        )

        coverage = clusters[0].documentation_coverage
        self.assertEqual(coverage.status, "in_progress")
        self.assertEqual(coverage.recommended_action, "no_change")
        self.assertEqual(
            coverage.relevant_sources[0].source_type,
            "documentation_pull_request",
        )


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


class WorkflowCompletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_terminal_workflow_skips_an_extra_model_request(self) -> None:
        state = {
            "run_id": "run-complete",
            "repo": "pingdotgg/t3code",
            "researched": True,
            "analyzed": True,
            "docs_searched": True,
            "drafted": True,
            "decisions": [],
            "errors": [],
        }

        with (
            patch("app.langgraph_agent.llm_is_configured", return_value=True),
            patch(
                "app.langgraph_agent.complete_json",
                new_callable=AsyncMock,
            ) as complete_json,
        ):
            result = await llm_decide(state)

        self.assertEqual(result["next_action"], "store")
        self.assertIn("without another model request", result["decision_reason"])
        complete_json.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
