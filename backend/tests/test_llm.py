import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.llm import complete_json, get_llm_route, require_json_array


def _response(model: str, content: dict, total_tokens: int = 10) -> SimpleNamespace:
    return SimpleNamespace(
        model=model,
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(content))
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=total_tokens - 2,
            completion_tokens=2,
            total_tokens=total_tokens,
        ),
    )


class LLMRouteTests(unittest.TestCase):
    def test_merge_gateway_is_preferred_over_direct_openai(self) -> None:
        route = get_llm_route(
            SimpleNamespace(
                merge_gateway_api_key="gateway-key",
                merge_gateway_base_url="https://gateway.example/v1/openai",
                merge_gateway_primary_model="google/gemini-3.7-flash",
                merge_gateway_fallback_model="openai/gpt-5.6-luna",
                openai_api_key="openai-key",
                openai_model="gpt-4o-mini",
            )
        )

        self.assertIsNotNone(route)
        self.assertEqual(route.gateway, "merge")
        self.assertEqual(
            route.models,
            ("google/gemini-3.7-flash", "openai/gpt-5.6-luna"),
        )

    def test_direct_openai_remains_backwards_compatible(self) -> None:
        route = get_llm_route(
            SimpleNamespace(
                merge_gateway_api_key=None,
                openai_api_key="openai-key",
                openai_model="gpt-4o-mini",
            )
        )

        self.assertIsNotNone(route)
        self.assertEqual(route.gateway, "openai")
        self.assertEqual(route.models, ("gpt-4o-mini",))


class JSONCompletionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.settings = SimpleNamespace(
            merge_gateway_api_key="gateway-key",
            merge_gateway_base_url="https://gateway.example/v1/openai",
            merge_gateway_primary_model="google/gemini-3.7-flash",
            merge_gateway_fallback_model="openai/gpt-5.6-luna",
        )

    async def test_primary_model_is_used_without_sampling_parameters(self) -> None:
        create = AsyncMock(return_value=_response("gemini-3.7-flash", {"items": []}))
        client = Mock()
        client.chat.completions.create = create

        with patch("app.llm.AsyncOpenAI", return_value=client):
            completion = await complete_json(
                [{"role": "user", "content": "Return JSON."}],
                validator=require_json_array("items"),
                settings=self.settings,
            )

        self.assertEqual(completion.provider, "google")
        self.assertEqual(completion.served_model, "gemini-3.7-flash")
        kwargs = create.await_args.kwargs
        self.assertEqual(kwargs["model"], "google/gemini-3.7-flash")
        self.assertNotIn("temperature", kwargs)
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})

    async def test_invalid_primary_response_falls_back_to_luna(self) -> None:
        create = AsyncMock(
            side_effect=[
                _response("gemini-3.7-flash", {"wrong": []}),
                _response("gpt-5.6-luna", {"items": []}),
            ]
        )
        client = Mock()
        client.chat.completions.create = create

        with patch("app.llm.AsyncOpenAI", return_value=client):
            completion = await complete_json(
                [{"role": "user", "content": "Return JSON."}],
                validator=require_json_array("items"),
                settings=self.settings,
            )

        self.assertEqual(completion.provider, "openai")
        self.assertEqual(completion.requested_model, "openai/gpt-5.6-luna")
        self.assertEqual(
            [call.kwargs["model"] for call in create.await_args_list],
            ["google/gemini-3.7-flash", "openai/gpt-5.6-luna"],
        )

    async def test_legacy_direct_openai_keeps_zero_temperature(self) -> None:
        create = AsyncMock(return_value=_response("gpt-4o-mini", {"items": []}))
        client = Mock()
        client.chat.completions.create = create

        with patch("app.llm.AsyncOpenAI", return_value=client):
            await complete_json(
                [{"role": "user", "content": "Return JSON."}],
                validator=require_json_array("items"),
                settings=SimpleNamespace(
                    merge_gateway_api_key=None,
                    openai_api_key="openai-key",
                    openai_model="gpt-4o-mini",
                ),
            )

        self.assertEqual(create.await_args.kwargs["temperature"], 0)


if __name__ == "__main__":
    unittest.main()
