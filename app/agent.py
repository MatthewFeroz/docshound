from app import events
from app.langgraph_agent import graph
from app.run_store import save_run
from app.state import RUNS, AgentState, GapCluster, Issue, PullRequest, RunRequest
from app.tracing import traced_run


async def run_agent(request: RunRequest, state: AgentState | None = None) -> AgentState:
    state = state or AgentState(repo=request.repo, dry_run=request.dry_run)
    RUNS[state.run_id] = state
    save_run(state)

    events.publish(
        state.run_id,
        {"type": "run_started", "run_id": state.run_id, "repo": state.repo},
    )

    try:
        with traced_run(state.run_id, request.repo):
            result = await graph.ainvoke(
                {
                    "run_id": state.run_id,
                    "repo": request.repo,
                    "docs_url": request.docs_url,
                    "limit": request.limit,
                    "dry_run": request.dry_run,
                    "issues": [],
                    "pull_requests": [],
                    "clusters": [],
                    "docs_sources": [],
                    "errors": [],
                    "decisions": [],
                    "researched": False,
                    "analyzed": False,
                    "docs_searched": False,
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
    except Exception as exc:
        state.errors.append(str(exc))
        state.status = "failed"
        events.publish(
            state.run_id,
            {"type": "run_completed", "status": "failed", "errors": state.errors},
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
    state.decisions = result.get("decisions", [])
    state.errors = result.get("errors", [])
    state.status = "completed_with_errors" if state.errors else "completed"

    events.publish(
        state.run_id,
        {
            "type": "run_completed",
            "status": state.status,
            "issues_scraped": len(state.issues),
            "pull_requests_scraped": len(state.pull_requests),
            "clusters_found": len(state.clusters),
            "docs_sources_found": len(state.docs_sources),
            "errors": state.errors,
        },
    )
    events.close(state.run_id)
    save_run(state)
    return state
