"""A deterministic provider for tests, CI and offline development. Never used in production."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

from app.llm.base import ChatMessage, GenerationOptions, LLMError, LLMStream, ProviderInfo, StreamPart, Usage

# Asked this, the fake answers with what the student's settings and progress added to its system
# prompt, so an end-to-end test can see on screen what the model was really told.
PROBE = "[[e2e: what were you told?]]"


def default_reply(messages: list[ChatMessage]) -> str:
    last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
    if last_user == PROBE:
        system = next((m.content for m in messages if m.role == "system"), "")
        _, found, student = system.partition("\n\n## ")
        return f"## {student}" if found else "No student instructions."
    return f"You said: {last_user}"


class FakeProvider:
    """Streams a scripted reply word by word.

    `reply` builds the text from the prompt; `fail_before_first` / `fail_after`
    raise an LLMError at that point, to exercise error and fallback paths.
    """

    def __init__(
        self,
        name: str = "fake",
        *,
        reply: Callable[[list[ChatMessage]], str] = default_reply,
        token_delay_s: float = 0.0,
        fail_before_first: LLMError | None = None,
        fail_after: tuple[int, LLMError] | None = None,
    ) -> None:
        self.name = name
        self.reply = reply
        self.token_delay_s = token_delay_s
        self.fail_before_first = fail_before_first
        self.fail_after = fail_after
        self.calls: list[list[ChatMessage]] = []
        # Observability for tests: pieces produced so far, and streams that were closed.
        self.emitted = 0
        self.closed_streams = 0

    async def stream(self, messages: list[ChatMessage], options: GenerationOptions) -> LLMStream:
        self.calls.append(list(messages))
        if self.fail_before_first is not None:
            raise self.fail_before_first
        text = self.reply(messages)
        return LLMStream(info=ProviderInfo(self.name, options.model or "fake-model"), parts=self._parts(text, messages))

    async def _parts(self, text: str, messages: list[ChatMessage]) -> AsyncIterator[StreamPart]:
        # Split into word-plus-whitespace pieces so joining them restores the text exactly.
        pieces, current = [], ""
        for char in text:
            current += char
            if char in " \n":
                pieces.append(current)
                current = ""
        if current:
            pieces.append(current)
        try:
            for index, piece in enumerate(pieces):
                if self.fail_after is not None and index == self.fail_after[0]:
                    raise self.fail_after[1]
                if self.token_delay_s:
                    await asyncio.sleep(self.token_delay_s)
                self.emitted += 1
                yield StreamPart(text=piece)
            prompt_chars = sum(len(m.content) for m in messages)
            yield StreamPart(
                usage=Usage(input_tokens=prompt_chars // 4, output_tokens=len(pieces)), finish_reason="stop"
            )
        finally:
            self.closed_streams += 1
