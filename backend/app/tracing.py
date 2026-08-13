import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from time import perf_counter
from typing import Any

from dotenv import load_dotenv
from openinference.instrumentation.langchain import LangChainInstrumentor
from openinference.instrumentation.openai import OpenAIInstrumentor
from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode, Tracer

from app import events


_tracer: Tracer = trace.get_tracer("docshound.agent")
_tracing_initialized = False


def setup_tracing() -> bool:
    """Configure optional OTLP export and AI framework instrumentation once.

    Tracing is deliberately opt-in: without an OTLP endpoint, DocsHound keeps
    publishing its existing UI events but does not create an SDK/exporter.
    """
    global _tracer, _tracing_initialized

    if _tracing_initialized:
        return True

    # Backend configuration supports both backend/.env and the legacy root .env.
    # The launcher sources those files; this also covers direct Python execution.
    load_dotenv(override=False)
    disabled = os.getenv("OTEL_SDK_DISABLED", "false").lower() == "true"
    endpoint_configured = bool(
        os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        or os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    )
    if disabled or not endpoint_configured:
        return False

    current_provider = trace.get_tracer_provider()
    if isinstance(current_provider, TracerProvider):
        provider = current_provider
    else:
        provider = TracerProvider(
            resource=Resource.create(
                {SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", "docshound")}
            )
        )
        # Constructing the exporter without explicit options makes it honor the
        # standard OTEL endpoint, headers, certificate, compression, and timeout
        # environment variables.
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)

    # The OpenAI SDK instrumentor also covers calls made through Merge
    # Gateway's OpenAI-compatible endpoint.
    LangChainInstrumentor().instrument(tracer_provider=provider)
    OpenAIInstrumentor().instrument(tracer_provider=provider)
    _tracer = provider.get_tracer("docshound.agent")
    _tracing_initialized = True
    return True


def _span_attributes(
    kind: OpenInferenceSpanKindValues,
    run_id: str,
    repo: str,
) -> dict[str, Any]:
    metadata = {"run_id": run_id, "repo": repo}
    return {
        SpanAttributes.OPENINFERENCE_SPAN_KIND: kind.value,
        SpanAttributes.SESSION_ID: run_id,
        SpanAttributes.METADATA: json.dumps(metadata, sort_keys=True),
        SpanAttributes.TAG_TAGS: ["docshound", repo],
        "docshound.run.id": run_id,
        "docshound.repo": repo,
    }


@contextmanager
def traced_tool(name: str, run_id: str, repo: str) -> Iterator[Span]:
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
    attributes = _span_attributes(OpenInferenceSpanKindValues.TOOL, run_id, repo)
    attributes[SpanAttributes.TOOL_NAME] = name
    attributes[SpanAttributes.INPUT_VALUE] = json.dumps(
        {"repo": repo, "run_id": run_id},
        sort_keys=True,
    )
    attributes[SpanAttributes.INPUT_MIME_TYPE] = "application/json"

    try:
        with _tracer.start_as_current_span(
            f"tool.{name}", attributes=attributes
        ) as span:
            try:
                yield span
            except Exception as exc:
                status = "error"
                error_msg = str(exc)
                span.set_status(Status(StatusCode.ERROR, error_msg))
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
def traced_run(run_id: str, repo: str) -> Iterator[Span]:
    """Create the OpenInference root AGENT span for a DocsHound run."""
    attributes = _span_attributes(OpenInferenceSpanKindValues.AGENT, run_id, repo)
    attributes[SpanAttributes.AGENT_NAME] = "DocsHound"
    attributes[SpanAttributes.INPUT_VALUE] = json.dumps(
        {"repo": repo, "run_id": run_id},
        sort_keys=True,
    )
    attributes[SpanAttributes.INPUT_MIME_TYPE] = "application/json"
    with _tracer.start_as_current_span(
        "docshound.agent", attributes=attributes
    ) as span:
        yield span


def set_run_output(span: Span, result: dict[str, Any]) -> None:
    """Attach a content-free result summary to the root agent span."""
    summary = {
        "issues_count": len(result.get("issues", [])),
        "pull_requests_count": len(result.get("pull_requests", [])),
        "clusters_count": len(result.get("clusters", [])),
        "docs_sources_count": len(result.get("docs_sources", [])),
        "errors_count": len(result.get("errors", [])),
    }
    span.set_attribute(
        SpanAttributes.OUTPUT_VALUE,
        json.dumps(summary, sort_keys=True),
    )
    span.set_attribute(SpanAttributes.OUTPUT_MIME_TYPE, "application/json")
    if summary["errors_count"]:
        span.set_status(Status(StatusCode.ERROR, "Agent completed with errors"))


async def run_traced(
    name: str,
    run_id: str,
    repo: str,
    fn: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    with traced_tool(name, run_id, repo) as span:
        result = fn(*args, **kwargs)
        if hasattr(result, "__await__"):
            result = await result
        span.set_attribute(SpanAttributes.OUTPUT_VALUE, _summarize_result(result))
        span.set_attribute(SpanAttributes.OUTPUT_MIME_TYPE, "application/json")
        return result


def _summarize_result(result: Any) -> str:
    """Record cardinality and type without repository or document content."""
    if result is None:
        summary: dict[str, Any] = {"type": "null"}
    elif isinstance(result, (list, tuple, set, dict)):
        summary = {"type": type(result).__name__, "count": len(result)}
    else:
        summary = {"type": type(result).__name__}
    return json.dumps(summary, sort_keys=True)
