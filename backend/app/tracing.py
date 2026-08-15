import json
import logging
import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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
from app.tracing_config import TraceExportConfig, resolve_trace_export_config


_tracer: Tracer = trace.get_tracer("docshound.agent")
_tracing_initialized = False
logger = logging.getLogger(__name__)


def setup_tracing() -> bool:
    """Configure one portable OTLP/OpenInference trace pipeline once.

    Explicit OTLP configuration wins. Otherwise LANGSMITH_API_KEY makes
    LangSmith the default OTLP destination without changing the span schema.
    """
    global _tracer, _tracing_initialized

    if _tracing_initialized:
        return True

    # Backend configuration supports both backend/.env and the legacy root .env.
    # The launcher sources those files; this also covers direct Python execution.
    load_dotenv(override=False)
    export_config = resolve_trace_export_config()
    if export_config is None:
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
        trace.set_tracer_provider(provider)

    provider.add_span_processor(
        BatchSpanProcessor(_build_span_exporter(export_config))
    )

    # The OpenAI SDK instrumentor also covers calls made through Merge
    # Gateway's OpenAI-compatible endpoint.
    LangChainInstrumentor().instrument(tracer_provider=provider)
    OpenAIInstrumentor().instrument(tracer_provider=provider)
    _tracer = provider.get_tracer("docshound.agent")
    _tracing_initialized = True
    logger.info(
        "OpenTelemetry/OpenInference tracing enabled for %s",
        export_config.destination,
    )
    return True


def _build_span_exporter(config: TraceExportConfig) -> OTLPSpanExporter:
    if config.use_standard_environment:
        # Preserve every standard OTEL exporter option, including certificates,
        # compression, timeout, headers, and endpoint path behavior.
        return OTLPSpanExporter()
    return OTLPSpanExporter(endpoint=config.endpoint, headers=config.headers)


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
        # Supplemental mapping for LangSmith's OTLP UI. OpenInference remains
        # the canonical semantic representation used by other exporters.
        "langsmith.span.kind": (
            "chain" if kind == OpenInferenceSpanKindValues.AGENT else "tool"
        ),
        "langsmith.span.tags": f"docshound,{repo}",
        "langsmith.metadata.run_id": run_id,
        "langsmith.metadata.repo": repo,
    }


@contextmanager
def traced_tool(
    name: str,
    run_id: str,
    repo: str,
    *,
    input_summary: dict[str, Any] | None = None,
) -> Iterator[Span]:
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
    attributes["langsmith.trace.name"] = name
    attributes[SpanAttributes.INPUT_VALUE] = json.dumps(
        input_summary or {"repo": repo, "run_id": run_id}, sort_keys=True
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


def summarize_documentation_route(
    product_repo: str,
    documentation_source: Mapping[str, Any] | None = None,
    docs_url: str | None = None,
) -> dict[str, Any]:
    """Return non-sensitive repository routing context for trace inputs."""
    summary: dict[str, Any] = {"product_repo": product_repo}
    source = documentation_source or {}
    source_kind = str(source.get("kind") or "").strip()
    documentation_repo = str(source.get("repo") or "").strip()
    documentation_root = str(source.get("root") or "").strip().strip("/")
    documentation_url = _safe_trace_url(
        str(source.get("url") or docs_url or "").strip()
    )

    if source_kind:
        summary["documentation_source_kind"] = source_kind
    elif documentation_url:
        summary["documentation_source_kind"] = "website"
    if documentation_repo:
        summary["documentation_repo"] = documentation_repo
    if documentation_root:
        summary["documentation_root"] = documentation_root
    if documentation_url:
        summary["documentation_url"] = documentation_url
    return summary


def _safe_trace_url(value: str) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


@contextmanager
def traced_run(
    run_id: str,
    repo: str,
    *,
    documentation_source: Mapping[str, Any] | None = None,
    docs_url: str | None = None,
) -> Iterator[Span]:
    """Create the OpenInference root AGENT span for a DocsHound run."""
    route_summary = summarize_documentation_route(
        repo,
        documentation_source,
        docs_url,
    )
    attributes = _span_attributes(OpenInferenceSpanKindValues.AGENT, run_id, repo)
    attributes[SpanAttributes.AGENT_NAME] = "DocsHound"
    attributes["langsmith.trace.name"] = "DocsHound"
    for input_name, attribute_name in (
        ("documentation_source_kind", "source_kind"),
        ("documentation_repo", "repo"),
        ("documentation_root", "root"),
        ("documentation_url", "url"),
    ):
        value = route_summary.get(input_name)
        if value:
            attributes[f"docshound.documentation.{attribute_name}"] = value
            attributes[f"langsmith.metadata.documentation_{attribute_name}"] = value
    attributes[SpanAttributes.INPUT_VALUE] = json.dumps(
        {"run_id": run_id, **route_summary},
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
    trace_input: dict[str, Any] | None = None,
    trace_output: Callable[[Any], Any] | None = None,
    **kwargs: Any,
) -> Any:
    with traced_tool(name, run_id, repo, input_summary=trace_input) as span:
        result = fn(*args, **kwargs)
        if hasattr(result, "__await__"):
            result = await result
        output = trace_output(result) if trace_output else _summarize_result(result)
        span.set_attribute(
            SpanAttributes.OUTPUT_VALUE,
            output if isinstance(output, str) else json.dumps(output, sort_keys=True),
        )
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
