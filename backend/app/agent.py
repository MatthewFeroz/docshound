from app import events
from app.run_outcomes import apply_run_outcome
from app.run_store import save_run
from app.state import RUNS, AgentState, GapCluster, Issue, PullRequest, RunRequest
from app.tracing import set_run_output, setup_tracing, traced_run

setup_tracing()

from app.langgraph_agent import graph  # noqa: E402


async def run_agent(request: RunRequest, state: AgentState | None = None) -> AgentState:
    state = state or AgentState(repo=request.repo, dry_run=request.dry_run)
    RUNS[state.run_id] = state
    save_run(state)

    events.publish(
        state.run_id,
        {"type": "run_started", "run_id": state.run_id, "repo": state.repo},
    )

    try:
        documentation_source = (
            request.documentation_source.model_dump(mode="json")
            if request.documentation_source
            else None
        )
        with traced_run(
            state.run_id,
            request.repo,
            documentation_source=documentation_source,
            docs_url=request.docs_url,
        ) as run_span:
            result = await graph.ainvoke(
                {
                    "run_id": state.run_id,
                    "repo": request.repo,
                    "docs_url": request.docs_url,
                    "documentation_source": documentation_source,
                    "include_documentation_activity": (
                        request.include_documentation_activity
                    ),
                    "limit": request.limit,
                    "dry_run": request.dry_run,
                    "issues": [],
                    "pull_requests": [],
                    "clusters": [],
                    "docs_sources": [],
                    "docs_candidates_inspected": 0,
                    "documentation_issues_scraped": 0,
                    "documentation_pull_requests_scraped": 0,
                    "errors": [],
                    "warnings": [],
                    "decisions": [],
                    "researched": False,
                    "analyzed": False,
                    "docs_searched": False,
                    "drafted": False,
                    "stored": False,
                },
                config={
                    "metadata": {
                        "run_id": state.run_id,
                        "repo": request.repo,
                        "dry_run": request.dry_run,
                    },
                    "tags": ["docshound", request.repo],
                },
            )
            set_run_output(run_span, result)
    except Exception as exc:
        state.errors.append(str(exc))
        state.status = "failed"
        apply_run_outcome(state)
        events.publish(
            state.run_id,
            {
                "type": "run_completed",
                "status": state.status,
                "outcome": state.outcome,
                "summary": state.summary,
                "errors": state.errors,
            },
        )
        events.close(state.run_id)
        save_run(state)
        return state

    state.issues = [Issue.model_validate(issue) for issue in result.get("issues", [])]
    state.pull_requests = [
        PullRequest.model_validate(pull_request)
        for pull_request in result.get("pull_requests", [])
    ]
    state.clusters = [
        GapCluster.model_validate(cluster) for cluster in result.get("clusters", [])
    ]
    from app.state import DocSource

    state.docs_sources = [
        DocSource.model_validate(source) for source in result.get("docs_sources", [])
    ]
    state.docs_candidates_inspected = result.get("docs_candidates_inspected", 0)
    state.documentation_issues_scraped = result.get("documentation_issues_scraped", 0)
    state.documentation_pull_requests_scraped = result.get(
        "documentation_pull_requests_scraped", 0
    )
    state.decisions = result.get("decisions", [])
    state.warnings = result.get("warnings", [])
    state.errors = result.get("errors", [])
    state.status = "completed_with_errors" if state.errors else "completed"
    apply_run_outcome(state)

    events.publish(
        state.run_id,
        {
            "type": "run_completed",
            "status": state.status,
            "outcome": state.outcome,
            "summary": state.summary,
            "issues_scraped": len(state.issues),
            "pull_requests_scraped": len(state.pull_requests),
            "clusters_found": len(state.clusters),
            "docs_sources_found": len(state.docs_sources),
            "docs_candidates_inspected": state.docs_candidates_inspected,
            "documentation_issues_scraped": state.documentation_issues_scraped,
            "documentation_pull_requests_scraped": (
                state.documentation_pull_requests_scraped
            ),
            "warnings": state.warnings,
            "errors": state.errors,
        },
    )
    events.close(state.run_id)
    save_run(state)
    return state
