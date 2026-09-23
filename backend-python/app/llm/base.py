"""The LLM abstraction: one protocol, typed errors, provider-neutral data types.

The chat service depends only on this module. Adding a provider means writing
one `LLMProvider`; adding routing (e.g. per-feature models for the AI Tutor)
means composing providers, as `FallbackProvider` already does.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class GenerationOptions:
    model: str | None = None  # None = the provider's configured default
    temperature: float = 0.7
    max_output_tokens: int = 4096


@dataclass
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass
class StreamPart:
    """One increment of a streamed reply: text, or (last) usage + finish reason."""

    text: str = ""
    usage: Usage | None = None
    finish_reason: str | None = None


@dataclass
class ProviderInfo:
    name: str
    model: str


@dataclass
class LLMStream:
    """A reply being generated. `info` names the provider/model actually serving it."""

    info: ProviderInfo
    parts: AsyncIterator[StreamPart]
    extra: dict = field(default_factory=dict)


class LLMProvider(Protocol):
    name: str

    async def stream(self, messages: list[ChatMessage], options: GenerationOptions) -> LLMStream:
        """Start a streamed completion.

        Must raise an `LLMError` (never a vendor exception) both when starting and
        while iterating `parts`.
        """
        ...


# ---------------------------------------------------------------------- errors
class LLMError(Exception):
    """Base for every provider failure. Messages here are internal, never shown to users."""

    code = "llm_unavailable"
    retryable = True
    # May a different provider be tried when this happens before the first token?
    fallback_allowed = True


class LLMUnavailable(LLMError):
    code = "llm_unavailable"


class LLMRateLimited(LLMError):
    code = "llm_rate_limited"


class LLMTimeout(LLMError):
    code = "llm_timeout"


class LLMAuthError(LLMError):
    """Bad or missing credentials for THIS provider; another provider may still work."""

    code = "llm_unavailable"
    retryable = False


class LLMBadRequest(LLMError):
    """The request itself was rejected (e.g. too long). Another provider would reject it too."""

    code = "llm_bad_request"
    retryable = False
    fallback_allowed = False
