"""Knowledge-base persistence and vector search (PostgreSQL + pgvector).

This is the only module that queries the knowledge-base tables. It knows nothing
about LangChain, LangGraph or HTTP.

Access boundary: every search takes an `AccessScope`. Allowed sources are resolved
first (global sources, plus the caller's own private sources) and the vector search
runs only inside that set. Name and metadata filters can narrow it, never widen it.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, func, literal_column, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentChunk, KnowledgeSource
from app.db.session import Database
from app.rag.errors import IngestionError, RetrievalError

_FILTER_KEY = re.compile(r"^[a-z0-9_]{1,64}$")
_SCALARS = (str, int, float, bool)


@dataclass(frozen=True)
class AccessScope:
    """Whose knowledge may be searched. user_id None = global sources only."""

    user_id: uuid.UUID | None


@dataclass(frozen=True)
class SearchHit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    source_id: uuid.UUID
    source_name: str
    title: str
    uri: str
    ordinal: int
    content: str
    metadata: dict[str, Any]
    score: float  # cosine similarity, 1 - cosine distance


@dataclass(frozen=True)
class ChunkInput:
    ordinal: int
    content: str
    embedding: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


def validate_metadata_filter(metadata_filter: dict[str, Any] | None) -> dict[str, Any] | None:
    """Flat {key: scalar} only. Bound as a JSON parameter; never interpolated into SQL."""
    if not metadata_filter:
        return None
    for key, value in metadata_filter.items():
        if not isinstance(key, str) or not _FILTER_KEY.match(key) or not isinstance(value, _SCALARS):
            raise RetrievalError("invalid_filter", "metadata filters must be flat {lowercase_key: scalar}")
    return dict(metadata_filter)


class KnowledgeStore:
    def __init__(self, db: Database, hnsw_ef_search: int = 100) -> None:
        self.db = db
        self.hnsw_ef_search = int(hnsw_ef_search)

    # ------------------------------------------------------------------ search
    @staticmethod
    def _allowed_sources_query(scope: AccessScope, source_names: list[str] | None):
        visible = KnowledgeSource.owner_user_id.is_(None)
        if scope.user_id is not None:
            visible = or_(visible, KnowledgeSource.owner_user_id == scope.user_id)
        query = select(KnowledgeSource.id).where(visible)
        if source_names:
            query = query.where(KnowledgeSource.name.in_(source_names))
        return query

    async def allowed_source_ids(
        self, session: AsyncSession, scope: AccessScope, source_names: list[str] | None = None
    ) -> list[uuid.UUID]:
        return list(await session.scalars(self._allowed_sources_query(scope, source_names)))

    async def has_chunks(self, scope: AccessScope, embedding_model: str) -> bool:
        """Cheap check (indexed EXISTS) so an empty knowledge base never costs an embedding call."""
        try:
            async with self.db.sessionmaker() as session:
                allowed = self._allowed_sources_query(scope, None).scalar_subquery()
                return bool(
                    await session.scalar(
                        select(
                            select(DocumentChunk.id)
                            .where(
                                DocumentChunk.embedding_model == embedding_model, DocumentChunk.source_id.in_(allowed)
                            )
                            .exists()
                        )
                    )
                )
        except Exception as error:  # noqa: BLE001 - classified by the caller
            raise RetrievalError("database_unavailable", type(error).__name__) from error

    async def search(
        self,
        scope: AccessScope,
        vector: list[float],
        *,
        embedding_model: str,
        k: int,
        source_names: list[str] | None = None,
        metadata_filter: dict[str, Any] | None = None,
        min_score: float = 0.0,
    ) -> list[SearchHit]:
        metadata_filter = validate_metadata_filter(metadata_filter)
        try:
            async with self.db.sessionmaker() as session, session.begin():
                allowed = await self.allowed_source_ids(session, scope, source_names)
                if not allowed:
                    return []
                # Keep filtered searches on the HNSW index (pgvector >= 0.8 iterative scans).
                await session.execute(text(f"SET LOCAL hnsw.ef_search = {self.hnsw_ef_search}"))
                await session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
                distance = DocumentChunk.embedding.cosine_distance(vector)
                hits = (
                    select(
                        DocumentChunk.id,
                        DocumentChunk.document_id,
                        DocumentChunk.source_id,
                        DocumentChunk.ordinal,
                        DocumentChunk.content,
                        DocumentChunk.metadata_.label("metadata"),
                        distance.label("distance"),
                    )
                    .where(DocumentChunk.embedding_model == embedding_model, DocumentChunk.source_id.in_(allowed))
                    .order_by(DocumentChunk.embedding.cosine_distance(vector))
                    .limit(k)
                )
                if metadata_filter:
                    hits = hits.where(DocumentChunk.metadata_.contains(metadata_filter))
                hits = hits.cte("hits")
                rows = (
                    await session.execute(
                        select(hits, Document.title, Document.uri, KnowledgeSource.name.label("source_name"))
                        .join(Document, Document.id == hits.c.document_id)
                        .join(KnowledgeSource, KnowledgeSource.id == hits.c.source_id)
                        .order_by(hits.c.distance)
                    )
                ).all()
        except RetrievalError:
            raise
        except Exception as error:  # noqa: BLE001
            raise RetrievalError("database_unavailable", type(error).__name__) from error

        results = []
        for row in rows:
            score = 1.0 - float(row.distance)
            if score < min_score:
                continue
            results.append(
                SearchHit(
                    chunk_id=row.id,
                    document_id=row.document_id,
                    source_id=row.source_id,
                    source_name=row.source_name,
                    title=row.title,
                    uri=row.uri,
                    ordinal=row.ordinal,
                    content=row.content,
                    metadata=dict(row.metadata or {}),
                    score=round(score, 6),
                )
            )
        return results

    async def count_other_model_chunks(self, embedding_model: str) -> int:
        async with self.db.sessionmaker() as session:
            return int(
                await session.scalar(
                    select(func.count())
                    .select_from(DocumentChunk)
                    .where(DocumentChunk.embedding_model != embedding_model)
                )
                or 0
            )

    # --------------------------------------------------------------- ingestion
    async def get_or_create_source(
        self, name: str, *, owner_user_id: uuid.UUID | None, description: str | None = None
    ) -> KnowledgeSource:
        async with self.db.sessionmaker() as session, session.begin():
            await session.execute(
                pg_insert(KnowledgeSource)
                .values(name=name, owner_user_id=owner_user_id, description=description)
                .on_conflict_do_nothing(index_elements=["name"])
            )
            source = await session.scalar(select(KnowledgeSource).where(KnowledgeSource.name == name))
        if source.owner_user_id != owner_user_id:
            # Never silently change who can see a source.
            raise IngestionError("source_owner_mismatch", "the source exists with a different owner")
        return source

    async def document_signature(self, source_id: uuid.UUID, uri: str) -> str | None:
        async with self.db.sessionmaker() as session:
            return await session.scalar(
                select(Document.ingest_signature).where(Document.source_id == source_id, Document.uri == uri)
            )

    async def upsert_document(
        self,
        *,
        source_id: uuid.UUID,
        uri: str,
        title: str,
        content_hash: str,
        ingest_signature: str,
        metadata: dict[str, Any],
        chunks: list[ChunkInput],
        embedding_model: str,
    ) -> str:
        """Create or replace a document and ALL its chunks in one transaction.

        INSERT ... ON CONFLICT DO UPDATE takes a row lock on an existing document, so
        concurrent ingestions of the same (source, uri) serialise: the last commit wins
        and no mix of versions or stale chunks can remain. Any failure rolls back and
        leaves the previous version intact.
        """
        async with self.db.sessionmaker() as session, session.begin():
            statement = pg_insert(Document).values(
                source_id=source_id,
                uri=uri,
                title=title,
                content_hash=content_hash,
                ingest_signature=ingest_signature,
                metadata_=metadata,
            )
            statement = statement.on_conflict_do_update(
                index_elements=["source_id", "uri"],
                set_={
                    "title": statement.excluded.title,
                    "content_hash": statement.excluded.content_hash,
                    "ingest_signature": statement.excluded.ingest_signature,
                    "metadata": statement.excluded.metadata,
                    "updated_at": func.clock_timestamp(),
                },
            ).returning(Document.id, literal_column("(xmax = 0)").label("inserted"))
            row = (await session.execute(statement)).one()
            await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == row.id))
            if chunks:
                await session.execute(
                    DocumentChunk.__table__.insert(),
                    [
                        {
                            "document_id": row.id,
                            "source_id": source_id,
                            "ordinal": chunk.ordinal,
                            "content": chunk.content,
                            "metadata": chunk.metadata,
                            "embedding": chunk.embedding,
                            "embedding_model": embedding_model,
                        }
                        for chunk in chunks
                    ],
                )
        return "created" if row.inserted else "replaced"

    async def delete_document(self, source_name: str, uri: str) -> bool:
        async with self.db.sessionmaker() as session, session.begin():
            source_id = await session.scalar(select(KnowledgeSource.id).where(KnowledgeSource.name == source_name))
            if source_id is None:
                return False
            result = await session.execute(delete(Document).where(Document.source_id == source_id, Document.uri == uri))
            return result.rowcount > 0
