"""Try providers in order until one starts streaming.

A provider is abandoned only if it fails BEFORE producing the first token.
Once text has reached the user, switching providers would rewrite what they
already read, so a mid-stream failure is surfaced as an error instead.
"""

from __future__ import annotations

from app.llm.base import ChatMessage, GenerationOptions, LLMError, LLMProvider, LLMStream, LLMUnavailable
from app.logging import get_logger

log = get_logger("app.llm")


class FallbackProvider:
    def __init__(self, providers: list[LLMProvider]) -> None:
        if not providers:
            raise ValueError("at least one provider is required")
        self.providers = providers
        self.name = "+".join(p.name for p in providers)

    async def stream(self, messages: list[ChatMessage], options: GenerationOptions) -> LLMStream:
        last: LLMError | None = None
        for index, provider in enumerate(self.providers):
            try:
                result = await provider.stream(messages, options)
                if index:
                    log.warning("llm fallback used", extra={"provider": provider.name, "position": index})
                return result
            except LLMError as error:
                last = error
                log.warning(
                    "llm provider failed before first token",
                    extra={"provider": provider.name, "error_code": error.code, "error_type": type(error).__name__},
                )
                if not error.fallback_allowed:
                    raise
        raise last or LLMUnavailable("no provider available")
