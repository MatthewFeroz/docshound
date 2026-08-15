import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.langgraph_agent import research
from app.state import DocumentationSource, GapCluster, Issue, PullRequest
from app.tools.cluster import _validate_cluster_sources

NOW = datetime(2026, 8, 14, tzinfo=timezone.utc)


def _issue(repo: str, number: int) -> Issue:
    return Issue(
        number=number,
        title=f"Issue in {repo}",
        body="Documentation question",
        url=f"https://github.com/{repo}/issues/{number}",
        state="open",
        created_at=NOW,
        updated_at=NOW,
        source_repo=repo,
    )


def _pull_request(repo: str, number: int) -> PullRequest:
    return PullRequest(
        number=number,
        title=f"Change in {repo}",
        body="Summary of the merged change",
        url=f"https://github.com/{repo}/pull/{number}",
        state="merged",
        merged_at=NOW,
        created_at=NOW,
        updated_at=NOW,
        source_repo=repo,
    )


class MultiRepositoryActivityTests(unittest.IsolatedAsyncioTestCase):
    async def test_research_includes_separate_docs_repo_activity(self) -> None:
        async def issues(repo: str, _limit: int):
            return [_issue(repo, 7)]

        async def pull_requests(repo: str, _limit: int, include_open: bool = False):
            pull_request = _pull_request(repo, 9)
            if include_open:
                pull_request = pull_request.model_copy(
                    update={"state": "open", "merged_at": None}
                )
            return [pull_request]

        state = {
            "run_id": "multi-repo-run",
            "repo": "acme/product",
            "limit": 50,
            "documentation_source": DocumentationSource(
                repo="acme/docs",
                root="content/en/docs",
                confidence=0.99,
                discovered_by="edit_on_github",
                page_count=42,
            ).model_dump(mode="json"),
            "include_documentation_activity": True,
            "issues": [],
            "pull_requests": [],
            "warnings": [],
            "errors": [],
        }
        with (
            patch(
                "app.langgraph_agent.research_repo", new=AsyncMock(side_effect=issues)
            ),
            patch(
                "app.langgraph_agent.research_pull_requests",
                new=AsyncMock(side_effect=pull_requests),
            ),
            patch("app.langgraph_agent.events.publish"),
        ):
            result = await research(state)

        self.assertEqual(
            [item["source_repo"] for item in result["issues"]],
            ["acme/product", "acme/docs"],
        )
        self.assertEqual(
            [item["source_repo"] for item in result["pull_requests"]],
            ["acme/product", "acme/docs"],
        )
        self.assertEqual(result["documentation_issues_scraped"], 1)
        self.assertEqual(result["documentation_pull_requests_scraped"], 1)

    async def test_source_refs_prevent_same_number_collisions(self) -> None:
        product_issue = _issue("acme/product", 7)
        docs_issue = _issue("acme/docs", 7)
        cluster = GapCluster(
            name="Docs navigation",
            summary="The docs issue reports unclear navigation.",
            recurring_question="Where is the API guide?",
            issue_numbers=[7],
            issue_refs=["acme/docs#7"],
            severity="medium",
            confidence=0.9,
        )

        validated = _validate_cluster_sources(
            [cluster],
            [product_issue, docs_issue],
            [],
            product_repo="acme/product",
        )

        self.assertEqual(validated[0].issue_refs, ["acme/docs#7"])
        self.assertEqual(validated[0].issue_numbers, [7])


if __name__ == "__main__":
    unittest.main()
