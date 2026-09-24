"""LangChain retriever over the PostgreSQL/pgvector knowledge base."""

from __future__ import annotations

import time
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForRetrieverRun, CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from app.rag.embeddings import embedding_model_id
from app.rag.errors import EmbeddingError
from app.rag.store import KnowledgeStore
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
