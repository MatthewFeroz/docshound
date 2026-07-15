from typing import Literal, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from app import events
from app.config import get_settings
from app.state import DocSource, GapCluster, Issue, PullRequest
from app.tools.cluster import attach_review_drafts, cluster_issues
from app.tools.docs import search_official_docs
from app.tools.github import research_pull_requests, research_repo
from app.tracing import run_traced


class AgentDecision(BaseModel):
    action: Literal["research", "analyze", "search_docs", "store"] = Field(
        description="The next tool node the agent should run."
    )
    reason: str = Field(description="Short reason for the selected action.")


class DocsHoundGraphState(TypedDict, total=False):
    run_id: str
    repo: str
    docs_url: str | None
    limit: int
    dry_run: bool
    issues: list[dict]
    pull_requests: list[dict]
    clusters: list[dict]
    docs_sources: list[dict]
    errors: list[str]
    next_action: str
    decision_reason: str
    decisions: list[dict]
    researched: bool
    analyzed: bool
    docs_searched: bool
    stored: bool


async def llm_decide(state: DocsHoundGraphState) -> DocsHoundGraphState:
    fallback_action = _safe_next_action(state)
    settings = get_settings()
    if not settings.openai_api_key:
        state["next_action"] = fallback_action
        state["decision_reason"] = "OPENAI_API_KEY is not set; used fallback router."
        _record_decision(state)
        return state

    prompt = f"""
You are DocsHound, a ReAct-style documentation gap agent.

Goal:
Find documentation gaps in issues and shipped changes in merged pull requests,
then preserve the audit trail for review.

Available actions:
- research: fetch recent GitHub issues and merged pull requests for the repo
- analyze: identify recurring gaps and shipped changes that need documentation
- search_docs: inspect configured official docs for citation evidence
- store: finalize the run and its audit trail

Rules:
- Research must happen before analysis.
- Analysis should happen after issues are available.
- Search docs should happen after analysis.
- Store should happen after docs search, or after an error.
- Do not choose an action that has already completed unless there is no other valid action.

Current state:
- repo: {state.get("repo")}
- docs_url: {state.get("docs_url")}
- researched: {state.get("researched", False)}
- analyzed: {state.get("analyzed", False)}
- docs_searched: {state.get("docs_searched", False)}
- stored: {state.get("stored", False)}
- issues_count: {len(state.get("issues", []))}
- merged_pull_requests_count: {len(state.get("pull_requests", []))}
- clusters_count: {len(state.get("clusters", []))}
- docs_sources_count: {len(state.get("docs_sources", []))}
- errors_count: {len(state.get("errors", []))}

Choose the next action.
"""
    try:
        model = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=0,
        ).with_structured_output(AgentDecision)
        decision = await model.ainvoke(prompt)
        action = _guard_action(state, decision.action)
        state["next_action"] = action
        if action != decision.action:
            state["decision_reason"] = (
                f"LLM chose {decision.action}, but guardrail selected {action}. "
                f"LLM reason: {decision.reason}"
            )
        else:
            state["decision_reason"] = decision.reason
    except Exception as exc:
        state["next_action"] = fallback_action
        state["decision_reason"] = f"LLM routing failed, used fallback: {exc}"

    _record_decision(state)
    return state


def _safe_next_action(
    state: DocsHoundGraphState,
) -> Literal["research", "analyze", "search_docs", "store"]:
    if not state.get("researched") and not state.get("errors"):
        return "research"
    if (state.get("issues") or state.get("pull_requests")) and not state.get("analyzed"):
        return "analyze"
    if state.get("analyzed") and not state.get("docs_searched"):
        return "search_docs"
    return "store"


def _guard_action(
    state: DocsHoundGraphState,
    action: Literal["research", "analyze", "search_docs", "store"],
) -> Literal["research", "analyze", "search_docs", "store"]:
    safe = _safe_next_action(state)
    if action == safe:
        return action
    if action == "store" and state.get("errors"):
        return "store"
    return safe


def _record_decision(state: DocsHoundGraphState) -> None:
    decision = {
        "action": state.get("next_action"),
        "reason": state.get("decision_reason", ""),
        "issues_count": len(state.get("issues", [])),
        "pull_requests_count": len(state.get("pull_requests", [])),
        "clusters_count": len(state.get("clusters", [])),
        "docs_sources_count": len(state.get("docs_sources", [])),
        "errors_count": len(state.get("errors", [])),
    }
    state.setdefault("decisions", []).append(decision)
    events.publish(state["run_id"], {"type": "agent_decision", **decision})


def route(
    state: DocsHoundGraphState,
) -> Literal["research", "analyze", "search_docs", "store"]:
    return state["next_action"]  # type: ignore[return-value]


async def research(state: DocsHoundGraphState) -> DocsHoundGraphState:
    try:
        issues = await run_traced(
            "research_repo",
            state["run_id"],
            state["repo"],
            research_repo,
            state["repo"],
            state.get("limit", 50),
        )
        state["issues"] = [issue.model_dump(mode="json") for issue in issues]
        events.publish(
            state["run_id"],
            {"type": "issues_fetched", "count": len(issues)},
        )
        pull_requests = await run_traced(
            "research_pull_requests",
            state["run_id"],
            state["repo"],
            research_pull_requests,
            state["repo"],
            state.get("limit", 50),
        )
        state["pull_requests"] = [
            pull_request.model_dump(mode="json")
            for pull_request in pull_requests
        ]
        events.publish(
            state["run_id"],
            {"type": "pull_requests_fetched", "count": len(pull_requests)},
        )
    except Exception as exc:
        state.setdefault("errors", []).append(str(exc))
    finally:
        state["researched"] = True
    return state


async def analyze(state: DocsHoundGraphState) -> DocsHoundGraphState:
    try:
        issues = [Issue.model_validate(issue) for issue in state.get("issues", [])]
        pull_requests = [
            PullRequest.model_validate(pull_request)
            for pull_request in state.get("pull_requests", [])
        ]
        clusters = await run_traced(
            "cluster_issues",
            state["run_id"],
            state["repo"],
            cluster_issues,
            issues,
            pull_requests,
        )
        clusters = attach_review_drafts(clusters, issues, pull_requests)
        cluster_dicts = [cluster.model_dump(mode="json") for cluster in clusters]
        state["clusters"] = cluster_dicts
        for index, cluster in enumerate(cluster_dicts):
            events.publish(
                state["run_id"],
                {"type": "gap_found", "index": index, "cluster": cluster},
            )
    except Exception as exc:
        state.setdefault("errors", []).append(str(exc))
    finally:
        state["analyzed"] = True
    return state


async def search_docs(state: DocsHoundGraphState) -> DocsHoundGraphState:
    try:
        clusters = [
            GapCluster.model_validate(cluster)
            for cluster in state.get("clusters", [])
        ]
        sources = await run_traced(
            "search_official_docs",
            state["run_id"],
            state["repo"],
            search_official_docs,
            state["repo"],
            state.get("docs_url"),
            clusters,
        )
        source_dicts = [source.model_dump(mode="json") for source in sources]
        state["docs_sources"] = source_dicts
        events.publish(
            state["run_id"],
            {
                "type": "docs_sources_found",
                "count": len(source_dicts),
                "sources": source_dicts,
            },
        )
    except Exception as exc:
        state.setdefault("errors", []).append(str(exc))
    finally:
        state["docs_searched"] = True
    return state


async def store(state: DocsHoundGraphState) -> DocsHoundGraphState:
    state["stored"] = True
    return state


builder = StateGraph(DocsHoundGraphState)
builder.add_node("llm_decide", llm_decide)
builder.add_node("research", research)
builder.add_node("analyze", analyze)
builder.add_node("search_docs", search_docs)
builder.add_node("store", store)

builder.set_entry_point("llm_decide")
builder.add_conditional_edges(
    "llm_decide",
    route,
    {
        "research": "research",
        "analyze": "analyze",
        "search_docs": "search_docs",
        "store": "store",
    },
)
builder.add_edge("research", "llm_decide")
builder.add_edge("analyze", "llm_decide")
builder.add_edge("search_docs", "llm_decide")
builder.add_edge("store", END)

graph = builder.compile()
