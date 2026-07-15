from collections.abc import Callable
from contextlib import contextmanager
from time import perf_counter
from typing import Any

from app import events

@contextmanager
def traced_tool(name: str, run_id: str, repo: str):
    start = perf_counter()
    events.publish(
        run_id,
        {
            "type": "tool_start",
            "name": name,
            "repo": repo,
        },
    )

    status = "ok"
    error_msg: str | None = None
    try:
        yield None
    except Exception as exc:
        status = "error"
        error_msg = str(exc)
        raise
    finally:
        duration_ms = (perf_counter() - start) * 1000
        events.publish(
            run_id,
            {
                "type": "tool_end",
                "name": name,
                "status": status,
                "duration_ms": round(duration_ms, 1),
                "error": error_msg,
            },
        )


@contextmanager
def traced_run(run_id: str, repo: str):
    """Keep the agent execution API observable without a hosted tracing service."""
    yield None


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
