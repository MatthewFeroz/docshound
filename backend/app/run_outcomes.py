from app.state import AgentState, RunOutcome


def apply_run_outcome(state: AgentState) -> None:
    """Attach the user-facing terminal outcome to an agent run."""
    state.outcome, state.summary = resolve_run_outcome(state)


def resolve_run_outcome(state: AgentState) -> tuple[RunOutcome, str]:
    if state.status == "running":
        return "in_progress", "Run is in progress."

    if state.status == "failed":
        return "failed", "The run could not be completed."

    if state.errors:
        return (
            "partial_failure",
            "The run completed with errors, so its recommendations may be incomplete.",
        )

    coverage_unverified = any(
        cluster.documentation_coverage is not None
        and cluster.documentation_coverage.status == "unable_to_verify"
        for cluster in state.clusters
    )
    if coverage_unverified:
        return (
            "partial_failure",
            "The run could not verify official documentation coverage, so its "
            "recommendations may be incomplete.",
        )

    if not state.issues and not state.pull_requests:
        return (
            "no_activity",
            "No relevant issues or merged pull requests were found.",
        )

    if not state.clusters:
        return (
            "no_recommendations",
            "Repository activity was found, but it did not produce a documentation "
            "recommendation.",
        )

    actionable_clusters = [
        cluster
        for cluster in state.clusters
        if cluster.review_status != "no_change_needed"
        and (
            cluster.documentation_coverage is None
            or cluster.documentation_coverage.recommended_action != "no_change"
        )
    ]
    if not actionable_clusters:
        return (
            "no_recommendations",
            "The identified activity is already documented or has documentation "
            "in progress. No changes are recommended.",
        )

    count = len(actionable_clusters)
    noun = "recommendation is" if count == 1 else "recommendations are"
    return "recommendations_found", f"{count} documentation {noun} ready."
