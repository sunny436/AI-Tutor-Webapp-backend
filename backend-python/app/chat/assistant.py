"""What the assistant is for a given turn: prompt, retrieval options and model.

THE extension seam for future assistants (for example a tutor with its own
instructions and retrieval filters). The generic chatbot returns the same
configuration for everyone. Retrieval options are chosen here, server-side; a
client can never supply them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.db.models import Conversation, User
from app.rag.graph import RetrievalOptions

SYSTEM_PROMPT = """You are a helpful, knowledgeable general-purpose AI assistant.
- Answer the user's question directly and clearly; explain concepts step by step when that helps.
- Follow the user's instructions about format, length, tone and language.
- If you are not sure about something, say so. Never invent facts, sources, quotes or numbers.
- Ask a short clarifying question only when the request is genuinely ambiguous.
- Use Markdown when it improves readability: headings, lists, tables, fenced code blocks with a
  language tag, and LaTeX math ($...$ inline, $$...$$ for blocks)."""


@dataclass(frozen=True)
class AssistantConfig:
    system_prompt: str
    # None = no retrieval for this assistant. Defaults search every source the user may see.
    retrieval: RetrievalOptions | None = field(default_factory=RetrievalOptions)
    model: str | None = None  # None = the provider's configured default
    temperature: float | None = None  # None = settings.llm_temperature


def resolve_assistant_config(user: User | None, conversation: Conversation | None) -> AssistantConfig:
    return AssistantConfig(system_prompt=SYSTEM_PROMPT)
