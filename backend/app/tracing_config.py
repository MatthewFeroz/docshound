import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import unquote


DEFAULT_LANGSMITH_ENDPOINT = "https://api.smith.langchain.com"
DEFAULT_LANGSMITH_PROJECT = "docshound"


@dataclass(frozen=True)
class TraceExportConfig:
    """Resolved OTLP destination without coupling instrumentation to a vendor."""

    destination: str
    endpoint: str
    headers: dict[str, str] = field(default_factory=dict, repr=False)
    use_standard_environment: bool = False


def resolve_trace_export_config(
    environ: Mapping[str, str] | None = None,
) -> TraceExportConfig | None:
    """Prefer explicit OTLP configuration, then default to LangSmith.

    Explicit OTEL exporter variables remain the portability escape hatch for a
    collector or another OTLP backend. When they are absent, a LangSmith API key
    is enough to route the same OpenTelemetry spans to LangSmith.
    """
    environment = environ if environ is not None else os.environ
    if _value(environment, "OTEL_SDK_DISABLED").lower() == "true":
        return None

    traces_endpoint = _value(environment, "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    base_endpoint = _value(environment, "OTEL_EXPORTER_OTLP_ENDPOINT")
    if traces_endpoint or base_endpoint:
        return TraceExportConfig(
            destination="otlp",
            endpoint=traces_endpoint or base_endpoint,
            use_standard_environment=True,
        )

    api_key = _value(environment, "LANGSMITH_API_KEY") or _value(
        environment, "LANGCHAIN_API_KEY"
    )
    if not api_key:
        return None

    api_endpoint = (
        _value(environment, "LANGSMITH_ENDPOINT")
        or _value(environment, "LANGCHAIN_ENDPOINT")
        or DEFAULT_LANGSMITH_ENDPOINT
    )
    project = (
        _value(environment, "LANGSMITH_PROJECT")
        or _value(environment, "LANGCHAIN_PROJECT")
        or DEFAULT_LANGSMITH_PROJECT
    )
    headers = _parse_otel_headers(
        _value(environment, "OTEL_EXPORTER_OTLP_HEADERS")
    )
    headers.setdefault("x-api-key", api_key)
    headers.setdefault("Langsmith-Project", project)
    workspace_id = _value(environment, "LANGSMITH_WORKSPACE_ID")
    if workspace_id:
        headers.setdefault("x-tenant-id", workspace_id)

    return TraceExportConfig(
        destination="langsmith",
        endpoint=_langsmith_traces_endpoint(api_endpoint),
        headers=headers,
    )


def _langsmith_traces_endpoint(api_endpoint: str) -> str:
    endpoint = api_endpoint.rstrip("/")
    if endpoint.endswith("/otel/v1/traces"):
        return endpoint
    if endpoint.endswith("/otel"):
        return f"{endpoint}/v1/traces"
    return f"{endpoint}/otel/v1/traces"


def _parse_otel_headers(raw_headers: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw_header in raw_headers.split(","):
        if "=" not in raw_header:
            continue
        key, value = raw_header.split("=", 1)
        key = unquote(key.strip())
        if key:
            headers[key] = unquote(value.strip())
    return headers


def _value(environment: Mapping[str, str], name: str) -> str:
    return str(environment.get(name) or "").strip()
