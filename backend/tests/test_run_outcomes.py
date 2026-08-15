import unittest
from datetime import datetime, timezone

from app.run_outcomes import apply_run_outcome
from app.state import AgentState, DocumentationCoverage, GapCluster, Issue


def issue() -> Issue:
    now = datetime.now(timezone.utc)
    return Issue(
        number=12,
        title="Document retry behavior",
        url="https://github.com/acme/product/issues/12",
        state="open",
        created_at=now,
        updated_at=now,
    )


def cluster(
    *,
    coverage: DocumentationCoverage | None = None,
    review_status: str = "pending_review",
) -> GapCluster:
    return GapCluster(
        name="Retry behavior",
        summary="Retry behavior needs documentation.",
        recurring_question="How do retries work?",
        issue_numbers=[12],
        severity="medium",
        confidence=0.9,
        review_status=review_status,
        documentation_coverage=coverage,
    )


class RunOutcomeTests(unittest.TestCase):
    def test_running_state_stays_in_progress(self) -> None:
        state = AgentState(repo="acme/product")

        apply_run_outcome(state)

        self.assertEqual(state.outcome, "in_progress")
        self.assertEqual(state.summary, "Run is in progress.")

    def test_no_activity_has_an_explicit_empty_outcome(self) -> None:
        state = AgentState(repo="acme/product", status="completed")

        self.assertEqual(state.outcome, "no_activity")
        self.assertEqual(
            state.summary,
            "No relevant issues or merged pull requests were found.",
        )

    def test_legacy_terminal_state_is_classified_during_validation(self) -> None:
        state = AgentState.model_validate(
            {
                "repo": "acme/product",
                "status": "completed",
                "issues": [issue().model_dump(mode="json")],
            }
        )

        self.assertEqual(state.outcome, "no_recommendations")
        self.assertNotEqual(state.summary, "Run is in progress.")

    def test_activity_without_clusters_has_an_explicit_empty_outcome(self) -> None:
        state = AgentState(
            repo="acme/product",
            status="completed",
            issues=[issue()],
        )

        apply_run_outcome(state)

        self.assertEqual(state.outcome, "no_recommendations")
        self.assertEqual(
            state.summary,
            "Repository activity was found, but it did not produce a "
            "documentation recommendation.",
        )

    def test_already_documented_clusters_are_not_recommendations(self) -> None:
        coverage = DocumentationCoverage(
            status="documented",
            rationale="The existing guide covers this behavior.",
            recommended_action="no_change",
        )
        state = AgentState(
            repo="acme/product",
            status="completed",
            issues=[issue()],
            clusters=[cluster(coverage=coverage, review_status="no_change_needed")],
        )

        apply_run_outcome(state)

        self.assertEqual(state.outcome, "no_recommendations")
        self.assertEqual(
            state.summary,
            "The identified activity is already documented or has documentation "
            "in progress. No changes are recommended.",
        )

    def test_actionable_clusters_report_recommendations(self) -> None:
        coverage = DocumentationCoverage(
            status="missing",
            rationale="No retry guide exists.",
            recommended_action="create_page",
        )
        state = AgentState(
            repo="acme/product",
            status="completed",
            issues=[issue()],
            clusters=[cluster(coverage=coverage)],
        )

        apply_run_outcome(state)

        self.assertEqual(state.outcome, "recommendations_found")
        self.assertEqual(state.summary, "1 documentation recommendation is ready.")

    def test_recoverable_errors_report_a_partial_failure(self) -> None:
        state = AgentState(
            repo="acme/product",
            status="completed_with_errors",
            issues=[issue()],
            errors=["Official documentation search could not be completed."],
        )

        apply_run_outcome(state)

        self.assertEqual(state.outcome, "partial_failure")
        self.assertEqual(
            state.summary,
            "The run completed with errors, so its recommendations may be incomplete.",
        )

    def test_unverified_documentation_coverage_is_a_partial_failure(self) -> None:
        coverage = DocumentationCoverage(
            status="unable_to_verify",
            rationale="GitHub returned 404 while reading the docs repository.",
            recommended_action="create_page",
        )
        state = AgentState(
            repo="acme/product",
            status="completed",
            issues=[issue()],
            clusters=[cluster(coverage=coverage)],
        )

        apply_run_outcome(state)

        self.assertEqual(state.outcome, "partial_failure")

    def test_fatal_errors_report_a_failed_outcome(self) -> None:
        state = AgentState(
            repo="acme/product",
            status="failed",
            errors=["GitHub authentication failed."],
        )

        apply_run_outcome(state)

        self.assertEqual(state.outcome, "failed")
        self.assertEqual(state.summary, "The run could not be completed.")


if __name__ == "__main__":
    unittest.main()
