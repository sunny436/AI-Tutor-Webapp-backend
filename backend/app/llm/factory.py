from __future__ import annotations

from app.llm.base import LLMProvider
from app.llm.fake import FakeProvider
from app.llm.fallback import FallbackProvider
from app.llm.openai_compatible import OpenAICompatibleProvider
from app.settings import Settings


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
                **common,
            )
        )
    return FallbackProvider(providers)
