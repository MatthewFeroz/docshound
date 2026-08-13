import asyncio
import json
import os
import unittest
from unittest.mock import patch

from openinference.instrumentation.langchain import LangChainInstrumentor
from openinference.instrumentation.openai import OpenAIInstrumentor
from openinference.semconv.trace import SpanAttributes
from opentelemetry.instrumentation.dependencies import get_dependency_conflicts
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode

from app import tracing


class TracingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_tracer = tracing._tracer
        self.exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        tracing._tracer = provider.get_tracer("docshound.tests")

    def tearDown(self) -> None:
        tracing._tracer = self.original_tracer

    def test_run_and_tool_are_openinference_spans_in_one_trace(self) -> None:
        async def operation() -> list[str]:
            return ["one", "two"]

        with (
            patch("app.tracing.events.publish"),
            tracing.traced_run("run-123", "acme/docs") as run_span,
        ):
            result = asyncio.run(
                tracing.run_traced(
                    "research_repo",
                    "run-123",
                    "acme/docs",
                    operation,
                )
            )
            tracing.set_run_output(
                run_span,
                {"issues": result, "pull_requests": [], "errors": []},
            )

        self.assertEqual(result, ["one", "two"])
        spans = {span.name: span for span in self.exporter.get_finished_spans()}
        agent = spans["docshound.agent"]
        tool = spans["tool.research_repo"]
        self.assertEqual(
            agent.attributes[SpanAttributes.OPENINFERENCE_SPAN_KIND], "AGENT"
        )
        self.assertEqual(
            tool.attributes[SpanAttributes.OPENINFERENCE_SPAN_KIND], "TOOL"
        )
        self.assertEqual(tool.attributes[SpanAttributes.SESSION_ID], "run-123")
        self.assertEqual(tool.attributes[SpanAttributes.TOOL_NAME], "research_repo")
        self.assertEqual(tool.context.trace_id, agent.context.trace_id)
        self.assertEqual(tool.parent.span_id, agent.context.span_id)
        self.assertEqual(
            json.loads(tool.attributes[SpanAttributes.OUTPUT_VALUE]),
            {"type": "list", "count": 2},
        )
        self.assertEqual(
            json.loads(agent.attributes[SpanAttributes.OUTPUT_VALUE]),
            {
                "issues_count": 2,
                "pull_requests_count": 0,
                "clusters_count": 0,
                "docs_sources_count": 0,
                "errors_count": 0,
            },
        )

    def test_custom_spans_do_not_capture_repository_bodies(self) -> None:
        sensitive_body = "private issue body"

        async def operation() -> list[dict[str, str]]:
            return [{"body": sensitive_body}]

        with (
            patch("app.tracing.events.publish"),
            tracing.traced_run("run-privacy", "acme/docs"),
        ):
            asyncio.run(
                tracing.run_traced(
                    "research_repo",
                    "run-privacy",
                    "acme/docs",
                    operation,
                )
            )

        serialized = " ".join(
            str(span.attributes) for span in self.exporter.get_finished_spans()
        )
        self.assertNotIn(sensitive_body, serialized)

    def test_tool_errors_set_otel_error_status(self) -> None:
        with (
            patch("app.tracing.events.publish"),
            self.assertRaisesRegex(RuntimeError, "boom"),
            tracing.traced_tool("explode", "run-456", "acme/docs"),
        ):
            raise RuntimeError("boom")

        span = self.exporter.get_finished_spans()[0]
        self.assertEqual(span.status.status_code, StatusCode.ERROR)
        self.assertTrue(any(event.name == "exception" for event in span.events))

    def test_run_with_errors_sets_otel_error_status(self) -> None:
        with tracing.traced_run("run-error", "acme/docs") as run_span:
            tracing.set_run_output(run_span, {"errors": ["analysis failed"]})

        span = self.exporter.get_finished_spans()[0]
        self.assertEqual(span.status.status_code, StatusCode.ERROR)

    def test_setup_is_opt_in_and_honors_sdk_disable(self) -> None:
        original_initialized = tracing._tracing_initialized
        tracing._tracing_initialized = False
        try:
            with (
                patch("app.tracing.load_dotenv"),
                patch.dict(os.environ, {}, clear=True),
            ):
                self.assertFalse(tracing.setup_tracing())

            with (
                patch("app.tracing.load_dotenv"),
                patch.dict(
                    os.environ,
                    {
                        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318",
                        "OTEL_SDK_DISABLED": "true",
                    },
                    clear=True,
                ),
            ):
                self.assertFalse(tracing.setup_tracing())
        finally:
            tracing._tracing_initialized = original_initialized

    def test_instrumentation_dependencies_are_compatible(self) -> None:
        for instrumentor in (LangChainInstrumentor(), OpenAIInstrumentor()):
            dependencies = instrumentor.instrumentation_dependencies()
            self.assertIsNone(
                get_dependency_conflicts(dependencies),
                f"Incompatible instrumentation dependencies: {dependencies}",
            )


if __name__ == "__main__":
    unittest.main()
