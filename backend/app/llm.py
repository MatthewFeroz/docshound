import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from openai import AsyncOpenAI
from opentelemetry import trace

from app.config import Settings, get_settings
from app.runtime_credentials import get_merge_gateway_api_key

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class LLMRoute:
    api_key: str
    models: tuple[str, ...]
    base_url: str | None = None
    gateway: str = "openai"


@dataclass(frozen=True)
class JSONCompletion(Generic[T]):
    value: T
    requested_model: str
    served_model: str
    provider: str


def get_llm_route(settings: Settings | Any | None = None) -> LLMRoute | None:
    """Resolve the configured model route, preferring Merge Gateway.

    OPENAI_API_KEY remains a backwards-compatible direct-provider fallback for
    existing installations. When Gateway is configured, both models are called
    through its OpenAI-compatible endpoint with Gemini first.
    """
    settings = settings or get_settings()
    gateway_key = get_merge_gateway_api_key() or getattr(
        settings, "merge_gateway_api_key", None
    )
    if gateway_key:
        models = tuple(
            model
            for model in (
                getattr(
                    settings,
                    "merge_gateway_primary_model",
                    "google/gemini-3.7-flash",
                ),
                getattr(
                    settings,
                    "merge_gateway_fallback_model",
                    "openai/gpt-5.6-luna",
                ),
            )
            if model
        )
        return LLMRoute(
            api_key=gateway_key,
            base_url=getattr(
                settings,
                "merge_gateway_base_url",
                "https://api-gateway.merge.dev/v1/openai",
            ),
            models=models,
            gateway="merge",
        )

    openai_key = getattr(settings, "openai_api_key", None)
    if openai_key:
        return LLMRoute(
            api_key=openai_key,
            models=(getattr(settings, "openai_model", "gpt-4o-mini"),),
        )
    return None


def llm_is_configured(settings: Settings | Any | None = None) -> bool:
    return get_llm_route(settings) is not None


def require_json_array(
    field: str,
    *,
    item_validator: Callable[[Any], Any] | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Build a validator for the JSON envelopes used by DocsHound prompts."""

    def validate(data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data.get(field), list):
            raise ValueError(f"LLM response must contain a '{field}' array")
        for item in data[field]:
            if not isinstance(item, dict):
                raise ValueError(f"Every item in '{field}' must be an object")
            if item_validator is not None:
                item_validator(item)
        return data

    return validate


async def complete_json(
    messages: Sequence[dict[str, str]],
    *,
    validator: Callable[[dict[str, Any]], T] | None = None,
    settings: Settings | Any | None = None,
) -> JSONCompletion[T | dict[str, Any]]:
    """Return validated JSON, retrying the configured models in priority order."""
    route = get_llm_route(settings)
    if route is None:
        raise RuntimeError("No LLM credential is configured")

    client = AsyncOpenAI(api_key=route.api_key, base_url=route.base_url)
    last_error: Exception | None = None
    for index, model in enumerate(route.models):
        try:
            request: dict[str, Any] = {
                "model": model,
                "response_format": {"type": "json_object"},
                "messages": list(messages),
            }
            # Preserve the legacy direct-OpenAI behavior. Gateway requests omit
            # sampling controls because Gemini 3.7 rejects temperature.
            if route.gateway == "openai":
                request["temperature"] = 0
            response = await client.chat.completions.create(
                **request,
            )
            data = json.loads(response.choices[0].message.content or "{}")
            value = validator(data) if validator else data
            served_model = response.model or model.rsplit("/", 1)[-1]
            provider = model.partition("/")[0] if "/" in model else route.gateway
            _record_completion_metadata(
                route=route,
                requested_model=model,
                served_model=served_model,
                provider=provider,
                fallback_used=index > 0,
            )
            return JSONCompletion(
                value=value,
                requested_model=model,
                served_model=served_model,
                provider=provider,
            )
        except Exception as exc:
            last_error = exc
            if index + 1 < len(route.models):
                logger.warning(
                    "LLM request failed for %s; retrying with %s: %s",
                    model,
                    route.models[index + 1],
                    exc,
                )

    raise RuntimeError(
        f"All configured {route.gateway} model routes failed"
    ) from last_error


def _record_completion_metadata(
    *,
    route: LLMRoute,
    requested_model: str,
    served_model: str,
    provider: str,
    fallback_used: bool,
) -> None:
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute("docshound.llm.gateway", route.gateway)
        span.set_attribute("docshound.llm.provider", provider)
        span.set_attribute("docshound.llm.requested_model", requested_model)
        span.set_attribute("docshound.llm.served_model", served_model)
        span.set_attribute("docshound.llm.fallback_used", fallback_used)
