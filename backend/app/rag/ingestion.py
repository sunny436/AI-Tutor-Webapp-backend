"""Ingestion: Document → parse → chunk → embed → PostgreSQL/pgvector.

Every chunk is embedded BEFORE anything is written, then the document and all its
chunks are written in one transaction (KnowledgeStore.upsert_document). A failure at
any step leaves the previous version of the document untouched.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.logging import get_logger
from app.rag.embeddings import embedding_model_id
from app.rag.errors import EmbeddingError, IngestionError, RagError
from app.rag.store import ChunkInput, KnowledgeStore, validate_metadata_filter
from app.settings import Settings

log = get_logger("app.rag.ingest")

SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt"}
_HEADING = re.compile(r"^\s{0,3}#\s+(.+?)\s*#*\s*$", re.M)


@dataclass(frozen=True)
class RawDocument:
    uri: str
    title: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestResult:
    uri: str
    status: str  # created | replaced | unchanged | skipped | failed
    reason: str | None = None
    chunks: int = 0


@dataclass
class IngestReport:
    results: list[IngestResult] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(1 for r in self.results if r.status == status)

    @property
    def ok(self) -> bool:
        return self.count("failed") == 0


def parse_document(uri: str, data: bytes, *, max_bytes: int, metadata: dict[str, Any] | None = None) -> RawDocument:
    """Validate and decode one file. Raises IngestionError with a reason code."""
    suffix = Path(uri).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise IngestionError("unsupported_type", suffix or "(none)")
    if len(data) > max_bytes:
        raise IngestionError("too_large", str(len(data)))
    if b"\x00" in data:
        raise IngestionError("binary_content")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise IngestionError("invalid_encoding") from error
    text = text.replace("\r\n", "\n").strip()
    if not text:
        raise IngestionError("empty")
    heading = _HEADING.search(text) if suffix != ".txt" else None
    title = (heading.group(1).strip() if heading else Path(uri).stem)[:300]
    return RawDocument(uri=uri, title=title, text=text, metadata=dict(metadata or {}))


class IngestionService:
    def __init__(self, store: KnowledgeStore, embeddings: Embeddings, settings: Settings) -> None:
        self.store = store
        self.embeddings = embeddings
        self.settings = settings
        self.model = embedding_model_id(embeddings)
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.rag_chunk_size, chunk_overlap=settings.rag_chunk_overlap
        )

    def signature(self, document: RawDocument, content_hash: str) -> str:
        """Changes whenever re-embedding is needed: content, title, metadata, model, dimension or chunking."""
        parts = [
            content_hash,
            document.title,
            json.dumps(document.metadata, sort_keys=True),
            self.model,
            str(self.settings.embedding_dimensions),
            str(self.settings.rag_chunk_size),
            str(self.settings.rag_chunk_overlap),
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()

    async def ingest(self, source_id: uuid.UUID, document: RawDocument) -> IngestResult:
        started = time.perf_counter()
        try:
            validate_metadata_filter(document.metadata)  # same flat {key: scalar} rules as filters
        except RagError as error:
            return IngestResult(document.uri, "failed", error.code)
        content_hash = hashlib.sha256(document.text.encode()).hexdigest()
        signature = self.signature(document, content_hash)
        try:
            if await self.store.document_signature(source_id, document.uri) == signature:
                return IngestResult(document.uri, "unchanged")
            pieces = [p for p in self.splitter.split_text(document.text) if p.strip()]
            vectors = await self.embeddings.aembed_documents(pieces)  # all of them, before any write
            if len(vectors) != len(pieces):
                raise EmbeddingError("embedding_count_mismatch")
            status = await self.store.upsert_document(
                source_id=source_id,
                uri=document.uri,
                title=document.title,
                content_hash=content_hash,
                ingest_signature=signature,
                metadata=document.metadata,
                chunks=[
                    ChunkInput(ordinal=i, content=piece, embedding=vector, metadata=document.metadata)
                    for i, (piece, vector) in enumerate(zip(pieces, vectors, strict=True))
                ],
                embedding_model=self.model,
            )
        except RagError as error:
            log.warning("ingest failed", extra={"reason": error.code})
            return IngestResult(document.uri, "failed", error.code)
        except Exception as error:  # noqa: BLE001 - database or unexpected failure; the transaction rolled back
            log.warning("ingest failed", extra={"reason": "database_error", "error_type": type(error).__name__})
            return IngestResult(document.uri, "failed", "database_error")
        log.info(
            "ingest document",
            extra={"status": status, "chunks": len(pieces), "duration_ms": int((time.perf_counter() - started) * 1000)},
        )
        return IngestResult(document.uri, status, chunks=len(pieces))


def collect_files(paths: list[Path]) -> list[tuple[str, Path]]:
    """(uri, path) pairs. A directory's files get URIs relative to that directory; a file's URI is its name."""
    found: list[tuple[str, Path]] = []
    for path in paths:
        if path.is_dir():
            for file in sorted(p for p in path.rglob("*") if p.is_file()):
                found.append((file.relative_to(path).as_posix(), file))
        else:
            found.append((path.name, path))
    return found
