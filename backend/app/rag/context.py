"""Assemble the LLM input under one deterministic character budget.

Priority (highest first), all measured in characters (a token proxy):
  1. the system prompt                       always
  2. the latest user message                 always
  3. retrieved context, whole chunks in rank order, until RAG_MAX_CONTEXT_CHARS
     (a chunk that does not fit ends the context; chunks are never cut)
  4. earlier conversation, newest to oldest, whole messages, until LLM_MAX_INPUT_CHARS

Context blocks are numbered [1]..[n] in the same order as the returned `sources`,
so a later citation feature can map markers to stored sources without redesign.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.documents import Document

from app.llm.base import ChatMessage

CONTEXT_HEADER = (
    "Reference material retrieved for this conversation. It may be incomplete or unrelated to the "
    "question. Use it only where it directly answers the user; otherwise answer from general knowledge "
    "and do not mention it. When you rely on it you may cite it by number, like [1]. Never invent "
    "sources, and never quote anything that is not in this material."
)


@dataclass
class AssembledPrompt:
    messages: list[ChatMessage]
    sources: list[dict] = field(default_factory=list)
    context_chars: int = 0
    prompt_chars: int = 0
    history_kept: int = 0
    history_dropped: int = 0


def source_entry(document: Document) -> dict:
    meta = document.metadata
    return {
        "chunkId": meta.get("chunk_id"),
        "documentId": meta.get("document_id"),
        "sourceId": meta.get("source_id"),
        "source": meta.get("source"),
        "title": meta.get("title"),
        "uri": meta.get("uri"),
        "ordinal": meta.get("ordinal"),
        "score": meta.get("score"),
    }


def _block(number: int, document: Document) -> str:
    meta = document.metadata
    label = meta.get("title") or meta.get("uri") or "document"
    return f"[{number}] {label} (source: {meta.get('source', 'unknown')})\n{document.page_content}"


def build_llm_messages(
    system_prompt: str,
    conversation: list[ChatMessage],
    documents: list[Document],
    *,
    max_input_chars: int,
    max_context_chars: int,
) -> AssembledPrompt:
    latest = conversation[-1] if conversation and conversation[-1].role == "user" else None
    earlier = conversation[:-1] if latest else list(conversation)
    used = len(system_prompt) + (len(latest.content) if latest else 0)

    blocks: list[str] = []
    sources: list[dict] = []
    context_chars = len(CONTEXT_HEADER)
    for document in documents:
        block = _block(len(blocks) + 1, document)
        if context_chars + len(block) > max_context_chars or used + context_chars + len(block) > max_input_chars:
            break
        blocks.append(block)
        sources.append(source_entry(document))
        context_chars += len(block)
    context_message = "\n\n".join([CONTEXT_HEADER, *blocks]) if blocks else ""
    used += len(context_message)

    kept: list[ChatMessage] = []
    for message in reversed(earlier):
        if used + len(message.content) > max_input_chars:
            break
        kept.append(message)
        used += len(message.content)
    kept.reverse()
    while kept and kept[0].role != "user":  # a transcript must start with the user
        used -= len(kept.pop(0).content)

    messages = [ChatMessage("system", system_prompt)]
    if context_message:
        messages.append(ChatMessage("system", context_message))
    messages.extend(kept)
    if latest:
        messages.append(latest)
    return AssembledPrompt(
        messages=messages,
        sources=sources,
        context_chars=len(context_message),
        prompt_chars=used,
        history_kept=len(kept),
        history_dropped=len(earlier) - len(kept),
    )
