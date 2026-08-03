import unittest
from datetime import datetime, timezone

from app.state import GapCluster, Issue, PullRequest
from app.tools.cluster import _trace_analysis_inputs, _trace_cluster_outputs


class ClusterTracingTests(unittest.TestCase):
    def test_trace_inputs_include_identifiers_but_not_source_bodies(self) -> None:
        now = datetime.now(timezone.utc)
        inputs = _trace_analysis_inputs(
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
                    )
                ],
            }
        )

        self.assertEqual(inputs["issue_count"], 1)
        self.assertEqual(inputs["issue_numbers"], [12])
        self.assertEqual(inputs["pull_request_count"], 1)
        self.assertEqual(inputs["pull_request_numbers"], [34])
        self.assertNotIn("body", str(inputs).lower())
        self.assertNotIn("sensitive", str(inputs).lower())

    def test_trace_outputs_explain_which_sources_formed_each_cluster(self) -> None:
        outputs = _trace_cluster_outputs(
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


if __name__ == "__main__":
    unittest.main()
