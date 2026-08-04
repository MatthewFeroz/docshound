import json
from collections.abc import Callable
from contextlib import contextmanager
from time import perf_counter
from typing import Any

from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes
from opentelemetry import trace as trace_api
from opentelemetry.trace import Status, StatusCode

from app import events

@contextmanager
def traced_tool(name: str, run_id: str, repo: str):
    start = perf_counter()
    normalized_name = name.lower()
    events.publish(
        run_id,
        {
            "type": "tool_start",
            "name": normalized_name,
            "repo": repo,
        },
    )

    status = "ok"
    error_msg: str | None = None
    tracer = trace_api.get_tracer("docshound")
    with tracer.start_as_current_span(normalized_name) as span:
        span.set_attributes(
            {
                SpanAttributes.OPENINFERENCE_SPAN_KIND: (
                    OpenInferenceSpanKindValues.TOOL.value
                ),
                SpanAttributes.TOOL_NAME: normalized_name,
                SpanAttributes.INPUT_MIME_TYPE: "application/json",
                SpanAttributes.INPUT_VALUE: json.dumps(
                    {"repo": repo, "run_id": run_id},
                    sort_keys=True,
                ),
                SpanAttributes.SESSION_ID: run_id,
            }
        )
        try:
            yield span
        except Exception as exc:
            status = "error"
            error_msg = str(exc)
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, error_msg))
            raise
        finally:
            duration_ms = (perf_counter() - start) * 1000
            span.set_attributes(
                {
                    SpanAttributes.OUTPUT_MIME_TYPE: "application/json",
                    SpanAttributes.OUTPUT_VALUE: json.dumps(
                        {"status": status},
                        sort_keys=True,
                    ),
                }
            )
            events.publish(
                run_id,
                {
                    "type": "tool_end",
                    "name": normalized_name,
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
