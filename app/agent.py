from app import events
from app.langgraph_agent import graph
from app.state import RUNS, AgentState, GapCluster, Issue, RunRequest


async def run_agent(request: RunRequest, state: AgentState | None = None) -> AgentState:
    state = state or AgentState(repo=request.repo, dry_run=request.dry_run)
    RUNS[state.run_id] = state

    events.publish(
        state.run_id,
        {"type": "run_started", "run_id": state.run_id, "repo": state.repo},
    )

    try:
        result = await graph.ainvoke(
            {
                "run_id": state.run_id,
                "repo": request.repo,
                "docs_url": request.docs_url,
                "limit": request.limit,
                "dry_run": request.dry_run,
                "issues": [],
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
                "tags": ["docs-gap-agent", request.repo],
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
        return state

    state.issues = [Issue.model_validate(issue) for issue in result.get("issues", [])]
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
            "clusters_found": len(state.clusters),
            "docs_sources_found": len(state.docs_sources),
            "errors": state.errors,
        },
    )
    events.close(state.run_id)
    return state
