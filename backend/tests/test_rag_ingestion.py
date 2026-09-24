"""Ingestion: parse → chunk → embed → one atomic write. Versioning, rollback and concurrency."""

import asyncio

import pytest
from sqlalchemy import func, select

from app.db.models import Document, DocumentChunk
from app.rag.embeddings import KeywordHashEmbeddings
from app.rag.errors import EmbeddingError, IngestionError
from app.rag.ingestion import IngestionService, parse_document
from app.rag.store import ChunkInput
from tests.conftest import SpyEmbeddings, ingest_docs, make_settings

LONG = "\n\n".join(f"Paragraph {i}. " + "Solar panels convert sunlight into electricity. " * 6 for i in range(12))


async def chunk_rows(app, uri=None):
    async with app.state.db.sessionmaker() as s:
        query = select(DocumentChunk).order_by(DocumentChunk.ordinal)
        if uri:
            query = query.join(Document).where(Document.uri == uri)
        return list(await s.scalars(query))


# ------------------------------------------------------------------ parsing
@pytest.mark.parametrize(
    ("uri", "data", "reason"),
    [
        ("a.pdf", b"%PDF-1.4", "unsupported_type"),
        ("noext", b"hello", "unsupported_type"),
        ("a.md", b"x" * 101, "too_large"),
        ("a.md", b"text\x00with nul", "binary_content"),
        ("a.md", b"\xff\xfe\xfa not utf8", "invalid_encoding"),
        ("a.md", b"   \n\t ", "empty"),
    ],
)
def test_parse_rejects_unsafe_input(uri, data, reason):
    with pytest.raises(IngestionError) as error:
        parse_document(uri, data, max_bytes=100)
    assert error.value.code == reason


def test_parse_titles_and_bom():
    md = parse_document("guide/intro.md", "﻿# Getting started\n\nBody".encode(), max_bytes=10_000)
    assert md.title == "Getting started" and md.text.startswith("# Getting started")
    txt = parse_document("notes.txt", b"# not a heading in txt\nbody", max_bytes=10_000)
    assert txt.title == "notes"


# ------------------------------------------------------------------ chunking + versioning
async def test_chunking_ordinals_and_sizes(app):
    app.state.settings = make_settings(rag_chunk_size=300, rag_chunk_overlap=30)
    _, results = await ingest_docs(app, {"solar.md": LONG})
    rows = await chunk_rows(app)
    assert results[0].status == "created" and results[0].chunks == len(rows) > 3
    assert [r.ordinal for r in rows] == list(range(len(rows)))
    assert all(len(r.content) <= 300 for r in rows)
    assert all(len(r.embedding) == 1536 for r in rows)


async def test_unchanged_document_is_skipped_without_embedding(app):
    spy = SpyEmbeddings(app.state.embeddings)
    service = IngestionService(app.state.knowledge, spy, app.state.settings)
    await ingest_docs(app, {"a.md": "# A\n\nalpha beta gamma"}, service=service)
    calls = spy.calls
    _, results = await ingest_docs(app, {"a.md": "# A\n\nalpha beta gamma"}, service=service)
    assert results[0].status == "unchanged" and spy.calls == calls


async def test_model_or_chunking_change_forces_reembedding(app):
    await ingest_docs(app, {"a.md": LONG})
    other_model = IngestionService(
        app.state.knowledge, KeywordHashEmbeddings(1536, model="other-model"), app.state.settings
    )
    _, results = await ingest_docs(app, {"a.md": LONG}, service=other_model)
    assert results[0].status == "replaced"
    assert {r.embedding_model for r in await chunk_rows(app)} == {"other-model"}
    rechunked = IngestionService(
        app.state.knowledge, app.state.embeddings, make_settings(rag_chunk_size=400, rag_chunk_overlap=0)
    )
    _, results = await ingest_docs(app, {"a.md": LONG}, service=rechunked)
    assert results[0].status == "replaced"


async def test_replacement_leaves_no_stale_chunks(app):
    await ingest_docs(app, {"a.md": LONG})
    assert len(await chunk_rows(app)) > 3
    _, results = await ingest_docs(app, {"a.md": "# Short\n\nNow it is short."})
    rows = await chunk_rows(app)
    assert results[0].status == "replaced" and len(rows) == 1 and "short" in rows[0].content
    async with app.state.db.sessionmaker() as s:
        assert await s.scalar(select(func.count()).select_from(Document)) == 1


# ------------------------------------------------------------------ atomicity
async def test_embedding_failure_writes_nothing(app):
    spy = SpyEmbeddings(app.state.embeddings)
    service = IngestionService(app.state.knowledge, spy, app.state.settings)
    await ingest_docs(app, {"old.md": "# Old\n\nthe previous version"}, service=service)
    before = [(r.content, r.ordinal) for r in await chunk_rows(app)]
    spy.fail_with = EmbeddingError("embedding_timeout")
    _, results = await ingest_docs(
        app, {"old.md": "# Old\n\na completely new version", "new.md": "# New\n\nbrand new"}, service=service
    )
    assert [r.status for r in results] == ["failed", "failed"]
    assert {r.reason for r in results} == {"embedding_timeout"}
    assert [(r.content, r.ordinal) for r in await chunk_rows(app)] == before  # old version intact
    async with app.state.db.sessionmaker() as s:
        assert await s.scalar(select(func.count()).select_from(Document)) == 1  # new.md never created


async def test_database_failure_mid_write_rolls_back(app):
    src, _ = await ingest_docs(app, {"a.md": "# A\n\nkeep me"})
    before = [r.content for r in await chunk_rows(app)]
    with pytest.raises(Exception):  # noqa: B017 - the vector(1536) column rejects a 3-dim vector
        await app.state.knowledge.upsert_document(
            source_id=src.id,
            uri="a.md",
            title="A",
            content_hash="x",
            ingest_signature="y",
            metadata={},
            chunks=[ChunkInput(ordinal=0, content="broken", embedding=[0.1, 0.2, 0.3])],
            embedding_model="m",
        )
    assert [r.content for r in await chunk_rows(app)] == before


async def test_concurrent_ingestion_of_same_uri_is_consistent(app):
    app.state.settings = make_settings(rag_chunk_size=200, rag_chunk_overlap=0)
    version_a = "# V\n\n" + " ".join(f"alpha{i}" for i in range(300))
    version_b = "# V\n\n" + " ".join(f"beta{i}" for i in range(60))
    src = await app.state.knowledge.get_or_create_source("kb", owner_user_id=None)
    service = IngestionService(app.state.knowledge, app.state.embeddings, app.state.settings)
    docs = [parse_document("v.md", v.encode(), max_bytes=10**6) for v in (version_a, version_b)]
    results = await asyncio.gather(*(service.ingest(src.id, d) for d in docs))
    assert {r.status for r in results} <= {"created", "replaced"}
    rows = await chunk_rows(app)
    words = {w for r in rows for w in r.content.split()}
    only_a = all(w.startswith(("alpha", "#", "V")) for w in words)
    only_b = all(w.startswith(("beta", "#", "V")) for w in words)
    assert only_a != only_b  # exactly one version, never a mix
    assert [r.ordinal for r in rows] == list(range(len(rows)))  # no duplicates
    async with app.state.db.sessionmaker() as s:
        assert await s.scalar(select(func.count()).select_from(Document)) == 1


# ------------------------------------------------------------------ misc
async def test_delete_document_cascades_chunks(app):
    await ingest_docs(app, {"a.md": LONG, "b.md": "# B\n\nother"})
    assert await app.state.knowledge.delete_document("kb", "a.md") is True
    assert {r.content for r in await chunk_rows(app)} == {"# B\n\nother"}
    assert await app.state.knowledge.delete_document("kb", "a.md") is False


async def test_invalid_document_metadata_is_rejected(app):
    _, results = await ingest_docs(app, {"a.md": "# A\n\nx"}, metadata={"Bad Key": "v"})
    assert results[0].status == "failed" and results[0].reason == "invalid_filter"
    assert await chunk_rows(app) == []


async def test_source_owner_cannot_change_silently(app):
    await app.state.knowledge.get_or_create_source("shared", owner_user_id=None)
    import uuid

    with pytest.raises(IngestionError) as error:
        await app.state.knowledge.get_or_create_source("shared", owner_user_id=uuid.uuid4())
    assert error.value.code == "source_owner_mismatch"
