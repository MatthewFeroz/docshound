import unittest
from unittest.mock import patch

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from app.openinference import (
    OPENINFERENCE_CHAIN_KIND,
    OPENINFERENCE_SPAN_KIND,
    SERVICE_NAME,
    LowercaseSpanNameProcessor,
    _resolve_trace_endpoint,
)
from app.tracing import traced_tool


class OpenInferenceConfigurationTests(unittest.TestCase):
    def test_signal_specific_endpoint_takes_precedence(self) -> None:
        endpoint = _resolve_trace_endpoint(
            {
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318",
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": (
                    "http://traces:4318/custom/v1/traces"
                ),
            }
        )

        self.assertEqual(endpoint, "http://traces:4318/custom/v1/traces")

    def test_base_endpoint_gets_trace_path(self) -> None:
        endpoint = _resolve_trace_endpoint(
            {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318/"}
        )

        self.assertEqual(endpoint, "http://collector:4318/v1/traces")

    def test_configuration_is_opt_in(self) -> None:
        self.assertIsNone(_resolve_trace_endpoint({}))

    def test_service_name_is_lower_case(self) -> None:
        self.assertEqual(SERVICE_NAME, SERVICE_NAME.lower())

    def test_span_names_are_lower_case_and_semantic_kind_stays_compliant(self) -> None:
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(LowercaseSpanNameProcessor())
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        tracer = provider.get_tracer("docshound.test")
        with tracer.start_as_current_span("Analyze.LLM_Cluster") as span:
            span.set_attribute(OPENINFERENCE_SPAN_KIND, OPENINFERENCE_CHAIN_KIND)

        exported = exporter.get_finished_spans()
        self.assertEqual(len(exported), 1)
        self.assertEqual(exported[0].name, "analyze.llm_cluster")
        self.assertEqual(
            exported[0].attributes[OPENINFERENCE_SPAN_KIND],
            "CHAIN",
        )

    def test_tool_span_has_openinference_attributes(self) -> None:
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(LowercaseSpanNameProcessor())
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer("docshound.test")

        with (
            patch("app.tracing.trace_api.get_tracer", return_value=tracer),
            patch("app.tracing.events.publish"),
            traced_tool("Research_Repo", "run-123", "acme/product"),
        ):
            pass

        exported = exporter.get_finished_spans()
        self.assertEqual(len(exported), 1)
        self.assertEqual(exported[0].name, "research_repo")
        self.assertEqual(
            exported[0].attributes[OPENINFERENCE_SPAN_KIND],
            "TOOL",
        )
        self.assertEqual(exported[0].attributes["tool.name"], "research_repo")
        self.assertEqual(exported[0].attributes["session.id"], "run-123")


if __name__ == "__main__":
    unittest.main()
