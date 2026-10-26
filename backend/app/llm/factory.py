from __future__ import annotations

import httpx
from openai import DefaultAsyncHttpxClient

from app.llm.base import LLMProvider
from app.llm.fake import FakeProvider
from app.llm.fallback import FallbackProvider
from app.llm.openai_compatible import OpenAICompatibleProvider
from app.settings import Settings

# Connections to the model's API are kept a minute (the SDK's default is 5 s): a chat's next turn usually comes
# 10-60 s after the last, and a new TLS connection to Ollima cost ~90 ms more per first token (measured 2026-10-26).
KEEPALIVE_S = 60.0


def _http_client() -> httpx.AsyncClient:
    return DefaultAsyncHttpxClient(
        limits=httpx.Limits(max_connections=1000, max_keepalive_connections=100, keepalive_expiry=KEEPALIVE_S)
    )


def build_llm(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "fake":
        return FakeProvider(token_delay_s=settings.llm_fake_token_delay_s)

    common = {
        "connect_timeout_s": settings.llm_connect_timeout_s,
        "first_token_timeout_s": settings.llm_first_token_timeout_s,
        "total_timeout_s": settings.llm_total_timeout_s,
    }
    providers: list[LLMProvider] = [
        OpenAICompatibleProvider(
            name=settings.llm_primary_name,
            base_url=settings.llm_primary_base_url,
            api_key=settings.llm_primary_api_key.get_secret_value(),
            model=settings.llm_primary_model,
            stream_usage=settings.llm_primary_stream_usage,
            http_client=_http_client(),
            **common,
        )
    ]
    if settings.llm_fallback_model:
        providers.append(
            OpenAICompatibleProvider(
                name=settings.llm_fallback_name,
                base_url=settings.llm_fallback_base_url,
                api_key=settings.llm_fallback_api_key.get_secret_value(),
                model=settings.llm_fallback_model,
                stream_usage=settings.llm_fallback_stream_usage,
                default_headers={"X-Title": settings.app_name},
                http_client=_http_client(),
                **common,
            )
        )
    return FallbackProvider(providers)
