"""LangChain retrievers over PostgreSQL/pgvector: the knowledge base, and files attached to a chat."""

from __future__ import annotations

import math
import time
import uuid
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForRetrieverRun, CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from app.rag.embeddings import embedding_model_id, is_configured
from app.rag.errors import EmbeddingError
from app.rag.store import FileHit, KnowledgeStore
from app.rag.types import AccessScope


class PgVectorRetriever(BaseRetriever):
    """Embeds the query, searches pgvector inside the caller's AccessScope, returns Documents.

    Every Document carries the metadata a citation needs later: chunk_id, document_id,
    source_id, source, title, uri, ordinal, score, embedding_model and the chunk's own
    attributes. Async only: the application never blocks the event loop on retrieval.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    store: KnowledgeStore
    embeddings: Embeddings
    scope: AccessScope
    k: int = 5
    min_score: float = 0.0
    source_names: list[str] | None = None
    metadata_filter: dict[str, Any] | None = None
    max_query_chars: int = 8_000
    # Filled by each call, for observability (milliseconds).
    last_timings: dict[str, int] = Field(default_factory=dict)

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        raise NotImplementedError("PgVectorRetriever is async-only; use `await retriever.ainvoke(query)`")

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun
    ) -> list[Document]:
        self.last_timings = {}
        query = (query or "").strip()[: self.max_query_chars] if isinstance(query, str) else ""
        if not query:
            return []

        started = time.perf_counter()
        try:
            vector = await self.embeddings.aembed_query(query)
        except EmbeddingError:
            raise
        except Exception as error:  # noqa: BLE001 - any provider failure is an embedding failure
            raise EmbeddingError("embedding_failed", type(error).__name__) from error
        embedded = time.perf_counter()

        model = embedding_model_id(self.embeddings)
        hits = await self.store.search(
            self.scope,
            vector,
            embedding_model=model,
            k=self.k,
            source_names=self.source_names,
            metadata_filter=self.metadata_filter,
            min_score=self.min_score,
        )
        self.last_timings = {
            "embedding_ms": int((embedded - started) * 1000),
            "search_ms": int((time.perf_counter() - embedded) * 1000),
        }
        return [
            Document(
                page_content=hit.content,
                metadata={
                    "chunk_id": str(hit.chunk_id),
                    "document_id": str(hit.document_id),
                    "source_id": str(hit.source_id),
                    "source": hit.source_name,
                    "title": hit.title,
                    "uri": hit.uri,
                    "ordinal": hit.ordinal,
                    "score": hit.score,
                    "embedding_model": model,
                    "attributes": hit.metadata,
                },
            )
            for hit in hits
        ]


# Files at or under this size are given to the tutor whole, in reading order; larger ones are
# searched, a few chunks from each (FILES_TOP_K spread over the large files, at least 2 each).
FILES_WHOLE_CHARS = 12_000
FILES_TOP_K = 8


class AttachedFiles:
    """The passages of a conversation's attached files that one turn may use.

    `files` come from the chat layer (app/files/service.conversation_files): this student's,
    ready, most recently attached first. The store checks ownership and readiness again. If the
    question cannot be embedded, large files fall back to reading order, so an attached file is
    never silently ignored."""

    def __init__(self, store: KnowledgeStore, embeddings: Embeddings) -> None:
        self.store = store
        self.embeddings = embeddings

    async def load(self, user_id: uuid.UUID | None, files: list[dict], question: str) -> tuple[list[Document], dict]:
        if user_id is None or not files:
            return [], {"files": 0, "chunks": 0, "mode": "none"}
        model = embedding_model_id(self.embeddings)
        whole = [f["id"] for f in files if (f.get("char_count") or 0) <= FILES_WHOLE_CHARS]
        large = [f["id"] for f in files if (f.get("char_count") or 0) > FILES_WHOLE_CHARS]
        hits: list[FileHit] = await self.store.file_chunks_in_order(
            user_id, whole, embedding_model=model, per_file_limit=10_000
        )
        mode = "whole"
        if large:
            per_file = max(2, math.ceil(FILES_TOP_K / len(large)))
            vector = None
            if is_configured(self.embeddings) and question.strip():
                try:
                    vector = await self.embeddings.aembed_query(question.strip()[:8_000])
                except Exception:  # noqa: BLE001 - reading order below: the file is still used
                    vector = None
            if vector is not None:
                mode = "search"
                hits += await self.store.search_files(
                    user_id, large, vector, embedding_model=model, per_file_k=per_file
                )
            else:
                mode = "reading_order"
                hits += await self.store.file_chunks_in_order(
                    user_id, large, embedding_model=model, per_file_limit=per_file
                )
        order = {f["id"]: index for index, f in enumerate(files)}
        hits.sort(key=lambda hit: (order.get(hit.file_id, len(order)), hit.ordinal))
        documents = [
            Document(
                page_content=hit.content,
                metadata={
                    "kind": "file",
                    "file_id": str(hit.file_id),
                    "title": hit.filename,
                    "ordinal": hit.ordinal,
                    "chunk_count": hit.chunk_count,
                    "score": hit.score,
                    **{key: value for key, value in hit.metadata.items() if key in ("page", "slide", "sheet")},
                },
            )
            for hit in hits
        ]
        return documents, {"files": len(files), "chunks": len(documents), "mode": mode}
