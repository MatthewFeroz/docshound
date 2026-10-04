import asyncio
import logging

from app import events
from app.config import get_settings
from app.run_outcomes import apply_run_outcome
from app.run_store import save_run
from app.state import RUNS, AgentState, RunRequest
from app.tracing import set_run_output, setup_tracing, traced_run
from app.usage import RunUsage, track_run_usage

setup_tracing()

from app.langgraph_agent import graph  # noqa: E402

logger = logging.getLogger(__name__)


async def run_agent(request: RunRequest, state: AgentState | None = None) -> AgentState:
    state = state or AgentState(repo=request.repo, dry_run=request.dry_run)

    def save_usage() -> None:
        save_run(state)
        events.publish(
            state.run_id, {"type": "usage_updated", "usage": state.usage.summary()}
        )

    RUNS[state.run_id] = state

    try:
        settings = get_settings()
        state.scan_limits = {
            "issues": request.limit,
            "merged_pull_requests": request.limit,
            "repository_documents": request.repo_docs_max_files
            or settings.repo_docs_max_files,
            "semantic_passages": request.nvidia_embed_max_passages
            or settings.nvidia_embed_max_passages,
        }
        state.usage = state.usage or RunUsage()
        save_run(state)
        events.publish(
            state.run_id,
            {"type": "run_started", "run_id": state.run_id, "repo": state.repo},
        )
        documentation_source = (
            request.documentation_source.model_dump(mode="json")
            if request.documentation_source
            else None
        )
        with (
            track_run_usage(state.usage, save_usage),
            traced_run(
                state.run_id,
                request.repo,
                documentation_source=documentation_source,
                docs_url=request.docs_url,
            ) as run_span,
        ):
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
                    "repo_docs_max_files": state.scan_limits["repository_documents"],
                    "nvidia_embed_max_passages": state.scan_limits["semantic_passages"],
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
            _apply_graph_result(state, result)
            set_run_output(run_span, result)
    except asyncio.CancelledError:
        state.errors.append("The run was cancelled before completion.")
        state.status = "failed"
        raise
    except Exception as exc:
        state.errors.append(str(exc))
        state.status = "failed"
    finally:
        finalize_run(state)
    return state


def _apply_graph_result(state: AgentState, result: dict) -> None:
    updates = {
        "issues": result.get("issues", []),
        "pull_requests": result.get("pull_requests", []),
        "clusters": result.get("clusters", []),
        "docs_sources": result.get("docs_sources", []),
        "docs_candidates_inspected": result.get("docs_candidates_inspected", 0),
        "documentation_issues_scraped": result.get("documentation_issues_scraped", 0),
        "documentation_pull_requests_scraped": result.get(
            "documentation_pull_requests_scraped", 0
        ),
        "decisions": result.get("decisions", []),
        "warnings": result.get("warnings", []),
        "errors": result.get("errors", []),
    }
    # Validate before replacing any partial state with an invalid graph result.
    parsed = AgentState.model_validate(state.model_dump() | updates)
    for name in updates:
        setattr(state, name, getattr(parsed, name))
    state.status = "completed_with_errors" if state.errors else "completed"


def finalize_run(state: AgentState) -> None:
    if state.status == "running":
        state.status = "failed"
        state.errors.append("The run stopped before completion.")
    apply_run_outcome(state)
    try:
        save_run(state)
    except Exception:
        state.status = "failed"
        state.errors.append("Could not save the final run state.")
        apply_run_outcome(state)
        logger.exception("Could not save final state for run %s", state.run_id)

    try:
        events.publish(
            state.run_id,
            {
                "type": "run_completed",
                "run_id": state.run_id,
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
    finally:
        events.close(state.run_id)
