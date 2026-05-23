from collections.abc import Callable
from contextlib import contextmanager
from time import perf_counter
from typing import Any

from app import events

try:
    from ddtrace import tracer
except Exception:  # pragma: no cover - optional dependency
    tracer = None


_TOOL_TO_SPONSOR = {
    "research_repo": "github",
    "cluster_issues": "openai",
    "store_results": "clickhouse",
    "publish_citeable": "senso",
    "search_official_docs": "nimble",
    "nimble_search": "nimble",
}


@contextmanager
def traced_tool(name: str, run_id: str, repo: str):
    start = perf_counter()
    events.publish(
        run_id,
        {
            "type": "tool_start",
            "name": name,
            "sponsor": _TOOL_TO_SPONSOR.get(name),
            "repo": repo,
        },
    )

    span = tracer.trace(f"tool.{name}", service="docs-gap-agent") if tracer else None
    if span is not None:
        span.set_tag("agent.run_id", run_id)
        span.set_tag("github.repo", repo)

    status = "ok"
    error_msg: str | None = None
    try:
        yield span
    except Exception as exc:
        status = "error"
        error_msg = str(exc)
        if span is not None:
            span.set_tag("status", "error")
            span.set_tag("error.msg", error_msg)
        raise
    finally:
        duration_ms = (perf_counter() - start) * 1000
        if span is not None:
            if status == "ok":
                span.set_tag("status", "ok")
            span.set_metric("duration_ms", duration_ms)
            span.finish()
        events.publish(
            run_id,
            {
                "type": "tool_end",
                "name": name,
                "sponsor": _TOOL_TO_SPONSOR.get(name),
                "status": status,
                "duration_ms": round(duration_ms, 1),
                "error": error_msg,
            },
        )


async def run_traced(
    name: str,
    run_id: str,
    repo: str,
    fn: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    with traced_tool(name, run_id, repo):
        result = fn(*args, **kwargs)
        if hasattr(result, "__await__"):
            return await result
        return result
