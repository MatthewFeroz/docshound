"""Optional OpenInference-compatible OpenTelemetry export."""

import os
from functools import lru_cache

from openinference.instrumentation.langchain import LangChainInstrumentor
from openinference.instrumentation.openai import OpenAIInstrumentor
from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes
from opentelemetry import trace as trace_api
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SERVICE_NAME = "docshound"
OPENINFERENCE_SPAN_KIND = SpanAttributes.OPENINFERENCE_SPAN_KIND
OPENINFERENCE_CHAIN_KIND = OpenInferenceSpanKindValues.CHAIN.value


class LowercaseSpanNameProcessor(SpanProcessor):
    """Normalize generated operation names without changing semantic values."""

    def on_start(self, span: Span, parent_context=None) -> None:
        span.update_name(span.name.lower())

    def on_end(self, span: ReadableSpan) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True


def _resolve_trace_endpoint(environ: dict[str, str]) -> str | None:
    traces_endpoint = environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if traces_endpoint:
        return traces_endpoint

    base_endpoint = environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if base_endpoint:
        return f"{base_endpoint.rstrip('/')}/v1/traces"
    return None


@lru_cache(maxsize=1)
def configure_openinference() -> TracerProvider | None:
    """Enable OpenInference when a standard OTLP endpoint is configured."""
    endpoint = _resolve_trace_endpoint(os.environ)
    if endpoint is None:
        return None

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": SERVICE_NAME,
                "openinference.project.name": SERVICE_NAME,
            }
        )
    )
    provider.add_span_processor(LowercaseSpanNameProcessor())
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace_api.set_tracer_provider(provider)

    LangChainInstrumentor().instrument(tracer_provider=provider)
    OpenAIInstrumentor().instrument(tracer_provider=provider)
    return provider
