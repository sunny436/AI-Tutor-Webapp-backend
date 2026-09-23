"""The optional context/retrieval seam between the chat service and the LLM.

Chat ─► ContextPipeline (0..n ContextProviders, concurrent, fail-soft) ─► LLM

No provider is registered in the generic chatbot. A future feature (for example
curriculum GraphRAG, or document search over pgvector) implements
`ContextProvider` and is returned from `resolve_assistant_config`; nothing else in
the chat path changes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ContextRequest:
    """Everything a provider may know about the turn. Identity is server-verified."""

    user_id: uuid.UUID
    conversation_id: uuid.UUID
    query: str


@dataclass(frozen=True)
class ContextBlock:
    text: str
    source: str  # e.g. "docs:chapter-3" - becomes a citation later
    score: float | None = None
    metadata: dict = field(default_factory=dict)


class ContextProvider(Protocol):
    name: str

    async def provide(self, request: ContextRequest) -> list[ContextBlock]: ...
