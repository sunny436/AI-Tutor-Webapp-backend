"""The chat/RAG workflow as a LangGraph graph.

    START → receive_query → retrieve_context → assemble_context → generate_answer → END

Deliberately linear and small. Later steps (query rewriting before retrieval,
reranking after it) are new nodes on these edges; nothing else changes.

Streaming: nodes emit custom events through LangGraph's stream writer. The chat
layer consumes `graph.astream(state, stream_mode="custom")`:
  {"event": "retrieval", "summary": {...}}                 once, before generation
  {"event": "llm_started", "provider": ..., "model": ...}
  {"event": "token", "text": ...}                          repeated
  {"event": "llm_finished", "usage": ..., "finish_reason": ...}

Failure policy: retrieval never fails a turn (it degrades to "no context" with a
reason code); LLM errors propagate unchanged (typed LLMError) to the chat layer.
Cancelling the consumer cancels the running node, which closes the LLM stream.

Ahead of the graph: `graph.prefetch(state)` runs receive_query and retrieve_context alone, so the chat
layer can search while it waits for something else (the intent router); a state given their result
with `prefetched` skips both steps. The search is the one the graph would make with the same state.

This module depends on abstractions only: an LLMProvider, a retriever factory that
returns a LangChain BaseRetriever, and a knowledge-presence check.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypedDict

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from app.llm.base import ChatMessage, GenerationOptions, LLMProvider
from app.logging import get_logger
from app.rag.context import FILES_MAX_CONTEXT_CHARS, build_llm_messages
from app.rag.errors import RagError
from app.rag.types import AccessScope, RetrievalOptions
from app.settings import Settings

log = get_logger("app.rag")

__all__ = ["RagDependencies", "TurnState", "RetrievalOptions", "build_rag_graph"]

NODES = ("receive_query", "retrieve_context", "assemble_context", "generate_answer")


class TurnState(TypedDict, total=False):
    # inputs
    user_id: uuid.UUID | None
    conversation: list[ChatMessage]  # oldest first; the last item is the new user message
    system_prompt: str
    retrieval: RetrievalOptions | None
    generation: GenerationOptions
    # files attached to this conversation that the turn may read (app/files): dicts with
    # id, filename, char_count, chunk_count; most recently attached first
    files: list[dict]
    # receive_query and retrieve_context already ran (graph.prefetch): their result is in the state
    prefetched: bool
    # produced by nodes
    question: str
    search_query: str  # what the knowledge base is searched with (search_query_for)
    documents: list[Document]
    file_documents: list[Document]
    retrieval_summary: dict
    llm_messages: list[ChatMessage]
    answer: str


@dataclass
class RagDependencies:
    llm: LLMProvider
    retriever_factory: Callable[[AccessScope, RetrievalOptions], BaseRetriever]
    has_knowledge: Callable[[AccessScope], Awaitable[bool]]
    embeddings_configured: bool
    settings: Settings
    # (user_id, files, question) -> (documents, summary): passages of the attached files.
    attached_files: Callable[[uuid.UUID | None, list[dict], str], Awaitable[tuple[list[Document], dict]]] | None = None


FOLLOW_UP_MAX_WORDS = 6
SEARCH_QUERY_MAX_CHARS = 1_000


def search_query_for(conversation: list[ChatMessage]) -> str:
    """The latest question, plus the one before it when the latest is a short follow-up ("explain
    step 2", "why?"): those few words alone would search for nothing. A rule, not a model call."""
    users = [message.content.strip() for message in conversation if message.role == "user" and message.content.strip()]
    if not users:
        return ""
    latest = users[-1]
    if len(users) > 1 and len(latest.split()) <= FOLLOW_UP_MAX_WORDS:
        latest = f"{users[-2][: SEARCH_QUERY_MAX_CHARS // 2]}\n{latest}"
    return latest[:SEARCH_QUERY_MAX_CHARS]


def build_rag_graph(deps: RagDependencies):
    settings = deps.settings

    async def receive_query(state: TurnState) -> dict:
        if state.get("prefetched"):
            return {}
        conversation = state.get("conversation") or []
        question = conversation[-1].content if conversation and conversation[-1].role == "user" else ""
        reason = None
        if not settings.rag_enabled:
            reason = "disabled"
        elif state.get("retrieval") is None:
            reason = "not_requested"
        elif not question.strip():
            reason = "empty_query"
        elif not deps.embeddings_configured:
            reason = "embeddings_unconfigured"
        summary = {"status": "skipped", "reason": reason} if reason else {"status": "pending"}
        search_query = search_query_for(conversation) if question else ""
        return {"question": question, "search_query": search_query, "retrieval_summary": summary, "documents": []}

    async def retrieve_context(state: TurnState) -> dict:
        if state.get("prefetched"):
            return {}
        # Attached files are read whether or not the knowledge base is searched: RAG_ENABLED and
        # the knowledge base's own skip reasons concern the knowledge base only.
        result = await retrieve_knowledge(state)
        files = state.get("files") or []
        if files and deps.attached_files is not None:
            result["file_documents"], result["retrieval_summary"]["files"] = await retrieve_files(state, files)
        return result

    async def retrieve_files(state: TurnState, files: list[dict]) -> tuple[list[Document], dict]:
        started = time.perf_counter()
        documents: list[Document] = []
        try:
            async with asyncio.timeout(settings.rag_retrieval_timeout_s):
                documents, info = await deps.attached_files(state.get("user_id"), files, state.get("question") or "")
            info = {"status": "ok" if documents else "empty", **info}
        except TimeoutError:
            info = {"status": "failed", "reason": "timeout"}
        except RagError as error:
            info = {"status": "failed", "reason": error.code}
        except Exception as error:  # noqa: BLE001 - retrieval must never fail the turn
            info = {"status": "failed", "reason": "internal_error"}
            log.warning("file retrieval crashed", extra={"error_type": type(error).__name__})
        info["latencyMs"] = int((time.perf_counter() - started) * 1000)
        log.info(
            "rag.files",
            extra={
                "status": info["status"],
                "reason": info.get("reason"),
                "files": len(files),
                "chunks": len(documents),
                "mode": info.get("mode"),
                "total_ms": info["latencyMs"],
            },
        )
        return documents, info

    async def retrieve_knowledge(state: TurnState) -> dict:
        summary = dict(state["retrieval_summary"])
        if summary["status"] == "skipped":
            return {"retrieval_summary": summary}
        options = state["retrieval"]
        scope = AccessScope(state.get("user_id"))
        started = time.perf_counter()
        documents: list[Document] = []
        timings: dict = {}
        try:
            async with asyncio.timeout(settings.rag_retrieval_timeout_s):
                if not await deps.has_knowledge(scope):
                    summary = {"status": "skipped", "reason": "empty_knowledge_base"}
                else:
                    retriever = deps.retriever_factory(scope, options)
                    documents = await retriever.ainvoke(state.get("search_query") or state["question"])
                    timings = dict(getattr(retriever, "last_timings", {}) or {})
                    summary = {"status": "ok" if documents else "empty", "reason": None}
        except TimeoutError:
            summary = {"status": "failed", "reason": "timeout"}
        except RagError as error:
            summary = {"status": "failed", "reason": error.code}
        except Exception as error:  # noqa: BLE001 - retrieval must never fail the turn
            summary = {"status": "failed", "reason": "internal_error"}
            log.warning("retrieval crashed", extra={"error_type": type(error).__name__})
        summary.update(
            chunkCount=len(documents),
            topScore=documents[0].metadata.get("score") if documents else None,
            latencyMs=int((time.perf_counter() - started) * 1000),
            embeddingMs=timings.get("embedding_ms"),
            searchMs=timings.get("search_ms"),
        )
        log.info(
            "rag.retrieval",
            extra={
                "status": summary["status"],
                "reason": summary.get("reason"),
                "chunks": summary["chunkCount"],
                "top_score": summary["topScore"],
                "embedding_ms": summary["embeddingMs"],
                "search_ms": summary["searchMs"],
                "total_ms": summary["latencyMs"],
            },
        )
        return {"documents": documents, "retrieval_summary": summary}

    async def assemble_context(state: TurnState) -> dict:
        prompt = build_llm_messages(
            state["system_prompt"],
            state.get("conversation") or [],
            state.get("documents") or [],
            max_input_chars=settings.llm_max_input_chars,
            max_context_chars=settings.rag_max_context_chars,
            attached_files=state.get("files") or [],
            file_documents=state.get("file_documents") or [],
            max_file_chars=FILES_MAX_CONTEXT_CHARS,
        )
        summary = {
            **state["retrieval_summary"],
            "sources": prompt.sources,
            "fileSources": prompt.file_sources,
            "contextChars": prompt.context_chars,
            "fileChars": prompt.file_chars,
            "promptChars": prompt.prompt_chars,
            "historyKept": prompt.history_kept,
            "historyDropped": prompt.history_dropped,
        }
        get_stream_writer()({"event": "retrieval", "summary": summary})
        log.info(
            "rag.graph",
            extra={
                "retrieval_status": summary["status"],
                "context_sources": len(prompt.sources),
                "context_chars": prompt.context_chars,
                "prompt_chars": prompt.prompt_chars,
                "history_kept": prompt.history_kept,
                "history_dropped": prompt.history_dropped,
            },
        )
        return {"llm_messages": prompt.messages, "retrieval_summary": summary}

    async def generate_answer(state: TurnState) -> dict:
        writer = get_stream_writer()
        stream = await deps.llm.stream(state["llm_messages"], state["generation"])
        writer({"event": "llm_started", "provider": stream.info.name, "model": stream.info.model})
        pieces: list[str] = []
        usage = None
        finish_reason = None
        parts = stream.parts.__aiter__()
        try:
            async for part in parts:
                if part.text:
                    pieces.append(part.text)
                    writer({"event": "token", "text": part.text})
                usage = part.usage or usage
                finish_reason = part.finish_reason or finish_reason
        finally:
            await parts.aclose()  # closes the provider's HTTP stream on success, error or cancel
        writer({"event": "llm_finished", "usage": usage, "finish_reason": finish_reason})
        return {"answer": "".join(pieces)}

    async def prefetch(state: TurnState) -> dict:
        """receive_query then retrieve_context, outside the graph: their result, for a state marked prefetched."""
        found = await receive_query(state)
        return {**found, **await retrieve_context({**state, **found}), "prefetched": True}

    graph = StateGraph(TurnState)
    for name, node in zip(NODES, (receive_query, retrieve_context, assemble_context, generate_answer), strict=True):
        graph.add_node(name, node)
    graph.add_edge(START, NODES[0])
    for current, following in zip(NODES, NODES[1:], strict=False):
        graph.add_edge(current, following)
    graph.add_edge(NODES[-1], END)
    compiled = graph.compile()
    compiled.prefetch = prefetch
    return compiled
