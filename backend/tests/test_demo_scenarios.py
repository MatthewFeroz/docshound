import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.demo_scenarios import (
    documentation_target_path,
    include_recent_activity,
    load_demo_scenario,
    pinned_issue_numbers,
    pinned_issue_relationships,
    pinned_pull_request_numbers,
)
from app.tools.github import research_pull_requests, research_repo


NOW = "2026-08-15T12:00:00Z"


def _issue(number: int, title: str) -> dict:
    return {
        "number": number,
        "title": title,
        "body": "Concrete documentation request.",
        "html_url": f"https://github.com/anomalyco/opencode/issues/{number}",
        "state": "open",
        "labels": [{"name": "documentation"}],
        "comments": 2,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _pull_request(number: int, title: str) -> dict:
    return {
        "number": number,
        "title": title,
        "body": "Shipped CLI behavior.",
        "html_url": f"https://github.com/anomalyco/opencode/pull/{number}",
        "state": "closed",
        "merged_at": NOW,
        "labels": [],
        "created_at": NOW,
        "updated_at": NOW,
    }


class DemoScenarioTests(unittest.TestCase):
    def test_opencode_scenario_has_pinned_sources_and_publish_target(self) -> None:
        scenario = load_demo_scenario("opencode")

        self.assertEqual(scenario.source_repository, "anomalyco/opencode")
        self.assertEqual(scenario.publish_repository, "MatthewFeroz/opencode")
        self.assertEqual(
            tuple(reference.number for reference in scenario.issues),
            (42484, 41537),
        )
        self.assertEqual(
            tuple(reference.number for reference in scenario.pull_requests),
            (31054,),
        )
        self.assertEqual(
            scenario.target_path,
            "packages/web/src/content/docs/cli.mdx",
        )
        self.assertFalse(scenario.include_recent_activity)
        self.assertEqual(
            pinned_issue_relationships("anomalyco/opencode"),
            {},
            "Relationships require an explicitly active scenario.",
        )

    def test_pins_apply_only_to_the_scenario_source_repository(self) -> None:
        settings = SimpleNamespace(docshound_demo_scenario="opencode")
        with patch("app.demo_scenarios.get_settings", return_value=settings):
            self.assertEqual(
                pinned_issue_numbers("anomalyco/opencode"),
                (42484, 41537),
            )
            self.assertEqual(
                pinned_pull_request_numbers("anomalyco/opencode"),
                (31054,),
            )
            self.assertEqual(pinned_issue_numbers("MatthewFeroz/opencode"), ())
            self.assertFalse(include_recent_activity("anomalyco/opencode"))
            self.assertTrue(include_recent_activity("MatthewFeroz/opencode"))
            self.assertEqual(
                pinned_issue_relationships("anomalyco/opencode"),
                {42484: (31054,), 41537: ()},
            )
            self.assertEqual(
                documentation_target_path("anomalyco/opencode"),
                "packages/web/src/content/docs/cli.mdx",
            )
            self.assertEqual(
                documentation_target_path("MatthewFeroz/opencode"),
                "packages/web/src/content/docs/cli.mdx",
            )
            self.assertIsNone(documentation_target_path("acme/other"))


class PinnedGitHubResearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_pinned_issue_is_fetched_first_and_deduplicated(self) -> None:
        pinned = _issue(42484, "Pinned documentation request")
        recent = _issue(7, "Recent issue")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/issues/42484"):
                return httpx.Response(200, json=pinned)
            if request.url.path.endswith("/issues"):
                return httpx.Response(200, json=[recent, pinned])
            return httpx.Response(404, json={"message": "not found"})

        async with httpx.AsyncClient(
            base_url="https://api.github.com",
            transport=httpx.MockTransport(handler),
        ) as client:
            with (
                patch(
                    "app.tools.github.pinned_issue_numbers",
                    return_value=(42484,),
                ),
                patch(
                    "app.tools.github.include_recent_activity",
                    return_value=True,
                ),
                patch("app.tools.github.configured_github_token", return_value=None),
            ):
                issues = await research_repo(
                    "anomalyco/opencode",
                    2,
                    client=client,
                )

        self.assertEqual([issue.number for issue in issues], [42484, 7])

    async def test_pinned_pull_request_is_fetched_first_and_deduplicated(self) -> None:
        pinned = _pull_request(31054, "Pinned shipped change")
        recent = _pull_request(8, "Recent shipped change")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/pulls/31054"):
                return httpx.Response(200, json=pinned)
            if request.url.path.endswith("/pulls"):
                return httpx.Response(200, json=[recent, pinned])
            return httpx.Response(404, json={"message": "not found"})

        async with httpx.AsyncClient(
            base_url="https://api.github.com",
            transport=httpx.MockTransport(handler),
        ) as client:
            with (
                patch(
                    "app.tools.github.pinned_pull_request_numbers",
                    return_value=(31054,),
                ),
                patch(
                    "app.tools.github.include_recent_activity",
                    return_value=True,
                ),
                patch("app.tools.github.configured_github_token", return_value=None),
            ):
                pull_requests = await research_pull_requests(
                    "anomalyco/opencode",
                    2,
                    client=client,
                )

        self.assertEqual(
            [pull_request.number for pull_request in pull_requests],
            [31054, 8],
        )

    async def test_pinned_only_mode_does_not_fetch_recent_activity(self) -> None:
        requests: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request.url.path)
            if request.url.path.endswith("/issues/42484"):
                return httpx.Response(200, json=_issue(42484, "Pinned request"))
            if request.url.path.endswith("/issues/41537"):
                return httpx.Response(200, json=_issue(41537, "Pinned request"))
            return httpx.Response(500, json={"message": "unexpected collection fetch"})

        async with httpx.AsyncClient(
            base_url="https://api.github.com",
            transport=httpx.MockTransport(handler),
        ) as client:
            with (
                patch(
                    "app.tools.github.pinned_issue_numbers",
                    return_value=(42484, 41537),
                ),
                patch(
                    "app.tools.github.include_recent_activity",
                    return_value=False,
                ),
                patch("app.tools.github.configured_github_token", return_value=None),
            ):
                issues = await research_repo(
                    "anomalyco/opencode",
                    50,
                    client=client,
                )

        self.assertEqual([issue.number for issue in issues], [42484, 41537])
        self.assertEqual(
            requests,
            [
                "/repos/anomalyco/opencode/issues/42484",
                "/repos/anomalyco/opencode/issues/41537",
            ],
        )


if __name__ == "__main__":
    unittest.main()
