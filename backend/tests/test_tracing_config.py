import unittest

from app.tracing_config import resolve_trace_export_config


class TracingConfigTests(unittest.TestCase):
    def test_langsmith_is_the_default_destination_when_its_key_is_set(self) -> None:
        config = resolve_trace_export_config(
            {
                "LANGSMITH_API_KEY": "test-key",
                "LANGSMITH_PROJECT": "docshound-demo",
            }
        )

        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual(config.destination, "langsmith")
        self.assertEqual(
            config.endpoint,
            "https://api.smith.langchain.com/otel/v1/traces",
        )
        self.assertEqual(config.headers["x-api-key"], "test-key")
        self.assertEqual(config.headers["Langsmith-Project"], "docshound-demo")
        self.assertFalse(config.use_standard_environment)

    def test_explicit_otlp_endpoint_overrides_langsmith(self) -> None:
        config = resolve_trace_export_config(
            {
                "LANGSMITH_API_KEY": "test-key",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318",
            }
        )

        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual(config.destination, "otlp")
        self.assertEqual(config.endpoint, "http://collector:4318")
        self.assertTrue(config.use_standard_environment)
        self.assertEqual(config.headers, {})

    def test_region_workspace_and_additional_headers_are_preserved(self) -> None:
        config = resolve_trace_export_config(
            {
                "LANGSMITH_API_KEY": "test-key",
                "LANGSMITH_ENDPOINT": "https://eu.api.smith.langchain.com",
                "LANGSMITH_WORKSPACE_ID": "workspace-id",
                "OTEL_EXPORTER_OTLP_HEADERS": "custom=value%20with%20spaces",
            }
        )

        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual(
            config.endpoint,
            "https://eu.api.smith.langchain.com/otel/v1/traces",
        )
        self.assertEqual(config.headers["x-tenant-id"], "workspace-id")
        self.assertEqual(config.headers["custom"], "value with spaces")

    def test_tracing_is_off_without_a_destination_or_when_sdk_is_disabled(self) -> None:
        self.assertIsNone(resolve_trace_export_config({}))
        self.assertIsNone(
            resolve_trace_export_config(
                {
                    "LANGSMITH_API_KEY": "test-key",
                    "OTEL_SDK_DISABLED": "true",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
