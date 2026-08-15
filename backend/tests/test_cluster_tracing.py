import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.state import GapCluster, Issue, PullRequest
from app.tools.cluster import (
    _ensure_demo_source_coverage,
    summarize_analysis_inputs,
    summarize_cluster_outputs,
)


class ClusterTracingTests(unittest.TestCase):
    def test_trace_inputs_include_identifiers_but_not_source_bodies(self) -> None:
        now = datetime.now(timezone.utc)
        inputs = summarize_analysis_inputs(
            {
                "issues": [
                    Issue(
                        number=12,
                        title="Secret-bearing issue title",
                        body="large and potentially sensitive source body",
                        url="https://example.com/issues/12",
                        state="open",
                        created_at=now,
                        updated_at=now,
                        source_repo="acme/product",
                    )
                ],
                "pull_requests": [
                    PullRequest(
                        number=34,
                        title="A merged change",
                        body="large pull request body",
                        url="https://example.com/pulls/34",
                        state="closed",
                        merged_at=datetime.now(timezone.utc),
                        created_at=now,
                        updated_at=now,
                        source_repo="acme/product",
                    )
                ],
            }
        )

        self.assertEqual(inputs["issue_count"], 1)
        self.assertEqual(inputs["issue_numbers"], [12])
        self.assertEqual(inputs["issue_refs"], ["acme/product#12"])
        self.assertEqual(inputs["pull_request_count"], 1)
        self.assertEqual(inputs["pull_request_numbers"], [34])
        self.assertEqual(inputs["pull_request_refs"], ["acme/product#34"])
        self.assertNotIn("body", str(inputs).lower())
        self.assertNotIn("sensitive", str(inputs).lower())

    def test_trace_outputs_explain_which_sources_formed_each_cluster(self) -> None:
        outputs = summarize_cluster_outputs(
            [
                GapCluster(
                    name="Authentication documentation gap",
                    summary="Users cannot find token setup instructions.",
                    recurring_question="How do I configure a token?",
                    issue_numbers=[12, 13],
                    pr_numbers=[34],
                    severity="high",
                    confidence=0.91,
                )
            ]
        )

        self.assertEqual(outputs["cluster_count"], 1)
        self.assertEqual(outputs["clusters"][0]["issue_numbers"], [12, 13])
        self.assertEqual(outputs["clusters"][0]["pr_numbers"], [34])
        self.assertEqual(outputs["clusters"][0]["confidence"], 0.91)

    def test_demo_guardrail_links_an_omitted_issue_to_its_shipped_change(self) -> None:
        now = datetime.now(timezone.utc)
        issue = Issue(
            number=42484,
            title="Document non-interactive MCP add",
            body="The CLI supports this behavior, but the reference omits it.",
            url="https://github.com/anomalyco/opencode/issues/42484",
            state="open",
            created_at=now,
            updated_at=now,
            source_repo="anomalyco/opencode",
        )
        pull_request = PullRequest(
            number=31054,
            title="Support non-interactive MCP add",
            url="https://github.com/anomalyco/opencode/pull/31054",
            state="merged",
            merged_at=now,
            created_at=now,
            updated_at=now,
            source_repo="anomalyco/opencode",
        )
        finding = GapCluster(
            name="Support non-interactive MCP add",
            summary="The CLI behavior shipped.",
            recurring_question="How do I use it?",
            issue_numbers=[],
            pr_numbers=[31054],
            pr_refs=["anomalyco/opencode#31054"],
            finding_type="shipped_change",
            severity="medium",
            confidence=0.9,
        )

        with patch(
            "app.tools.cluster.pinned_issue_relationships",
            return_value={42484: (31054,)},
        ):
            findings = _ensure_demo_source_coverage(
                [finding],
                [issue],
                [pull_request],
                product_repo="anomalyco/opencode",
            )

        self.assertEqual(findings[0].issue_numbers, [42484])
        self.assertEqual(
            findings[0].issue_refs,
            ["anomalyco/opencode#42484"],
        )


if __name__ == "__main__":
    unittest.main()
