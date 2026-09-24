"""LangChain retriever over pgvector: ranking, thresholds, filters, access boundary, failures, index use."""

import pytest
from sqlalchemy import select, text

from app.db.models import User
from app.db.session import Database
from app.rag.embeddings import KeywordHashEmbeddings
from app.rag.errors import RetrievalError
from app.rag.retriever import PgVectorRetriever
from app.rag.store import KnowledgeStore
from app.rag.types import AccessScope
from tests.conftest import SpyEmbeddings, ingest_docs, make_settings, register

DOCS = {
    "solar.md": "# Solar power\n\nSolar panels convert sunlight into electricity with photovoltaic cells.",
    "bread.md": "# Baking bread\n\nBread needs flour, water, yeast and salt; knead the dough and let it rise.",
    "rivers.md": "# Rivers\n\nRivers carry water from mountains to the sea and shape valleys over time.",
}
GLOBAL = AccessScope(None)


def retriever(app, scope=GLOBAL, **kwargs):
    kwargs.setdefault("k", 5)
    kwargs.setdefault("min_score", 0.0)
    return PgVectorRetriever(store=app.state.knowledge, embeddings=app.state.embeddings, scope=scope, **kwargs)


async def user_id(app, email):
    async with app.state.db.sessionmaker() as s:
        return await s.scalar(select(User.id).where(User.email == email))


async def test_ranking_and_citation_metadata(app):
    await ingest_docs(app, DOCS)
    docs = await retriever(app).ainvoke("how do solar panels turn sunlight into electricity")
    top = docs[0]
    assert top.metadata["uri"] == "solar.md" and "photovoltaic" in top.page_content
    assert set(top.metadata) >= {
        "chunk_id",
        "document_id",
        "source_id",
        "source",
        "title",
        "uri",
        "ordinal",
        "score",
        "embedding_model",
        "attributes",
    }
    assert top.metadata["title"] == "Solar power" and top.metadata["source"] == "kb"
    assert top.metadata["score"] > docs[-1].metadata["score"]


async def test_min_score_drops_irrelevant_chunks(app):
    await ingest_docs(app, DOCS)
    assert await retriever(app, min_score=0.3).ainvoke("quantum chromodynamics lattice gauge") == []
    hits = await retriever(app, min_score=0.3).ainvoke("solar panels sunlight electricity")
    assert [d.metadata["uri"] for d in hits] == ["solar.md"]


async def test_source_and_metadata_filters_only_narrow(app):
    await ingest_docs(app, {"en.md": "# Water\n\nwater cycle evaporation rain"}, source="a", metadata={"lang": "en"})
    await ingest_docs(app, {"fr.md": "# Eau\n\nwater cycle evaporation rain"}, source="b", metadata={"lang": "fr"})
    query = "water cycle evaporation rain"
    assert {d.metadata["source"] for d in await retriever(app).ainvoke(query)} == {"a", "b"}
    assert {d.metadata["source"] for d in await retriever(app, source_names=["a"]).ainvoke(query)} == {"a"}
    only_fr = await retriever(app, metadata_filter={"lang": "fr"}).ainvoke(query)
    assert [d.metadata["uri"] for d in only_fr] == ["fr.md"] and only_fr[0].metadata["attributes"] == {"lang": "fr"}
    assert await retriever(app, source_names=["does-not-exist"]).ainvoke(query) == []


@pytest.mark.parametrize("bad", [{"Lang": "x"}, {"lang": {"nested": 1}}, {"a; drop table": "x"}])
async def test_invalid_metadata_filter_is_rejected(app, bad):
    await ingest_docs(app, DOCS)
    with pytest.raises(RetrievalError) as error:
        await retriever(app, metadata_filter=bad).ainvoke("solar")
    assert error.value.code == "invalid_filter"


async def test_private_sources_never_leak_across_users(client, app):
    alice = await register(client, app)
    bob = await register(client, app)
    alice_id, bob_id = await user_id(app, alice["email"]), await user_id(app, bob["email"])
    await ingest_docs(
        app, {"secret.md": "# Alice notes\n\nzebra quartz violet"}, source="alice-notes", owner_user_id=alice_id
    )
    await ingest_docs(app, {"public.md": "# Public\n\nzebra quartz violet"}, source="public")
    query = "zebra quartz violet"
    as_alice = {d.metadata["uri"] for d in await retriever(app, AccessScope(alice_id)).ainvoke(query)}
    as_bob = {d.metadata["uri"] for d in await retriever(app, AccessScope(bob_id)).ainvoke(query)}
    as_global = {d.metadata["uri"] for d in await retriever(app, GLOBAL).ainvoke(query)}
    assert as_alice == {"secret.md", "public.md"}
    assert as_bob == {"public.md"} and as_global == {"public.md"}
    # naming the private source explicitly cannot widen Bob's access
    assert await retriever(app, AccessScope(bob_id), source_names=["alice-notes"]).ainvoke(query) == []


async def test_other_embedding_model_is_invisible(app):
    await ingest_docs(app, DOCS)
    other = PgVectorRetriever(
        store=app.state.knowledge, embeddings=KeywordHashEmbeddings(1536, model="other-model"), scope=GLOBAL, k=5
    )
    assert await other.ainvoke("solar panels") == []


async def test_empty_knowledge_base_and_blank_query(app):
    spy = SpyEmbeddings(app.state.embeddings)
    r = PgVectorRetriever(store=app.state.knowledge, embeddings=spy, scope=GLOBAL)
    assert await r.ainvoke("anything") == []
    assert await r.ainvoke("   ") == [] and spy.calls == 1  # blank query: no embedding call
    assert await app.state.knowledge.has_chunks(GLOBAL, "fake:text-embedding-3-small") is False


async def test_sync_use_is_refused(app):
    with pytest.raises(NotImplementedError):
        retriever(app).invoke("solar")


async def test_database_unavailable_is_a_typed_error():
    settings = make_settings(
        database_url="postgresql+asyncpg://aichat:aichat@127.0.0.1:1/aichat_test", db_connect_timeout_s=1.0
    )
    db = Database(settings)
    store = KnowledgeStore(db)
    try:
        r = PgVectorRetriever(store=store, embeddings=KeywordHashEmbeddings(1536), scope=GLOBAL)
        with pytest.raises(RetrievalError) as error:
            await r.ainvoke("solar")
        assert error.value.code == "database_unavailable"
        with pytest.raises(RetrievalError):
            await store.has_chunks(GLOBAL, "m")
    finally:
        await db.dispose()


async def test_search_query_can_use_the_hnsw_index(app):
    """Proves the production query shape is HNSW-compatible (operator, opclass, no casts).

    On small or highly selective sources the planner legitimately prefers the
    (source_id, embedding_model) btree plus an exact sort; that path is disabled here
    so the only way to satisfy ORDER BY distance LIMIT k is the HNSW index. If the
    query shape were incompatible, the plan would still contain a Sort.
    """
    await ingest_docs(app, DOCS)
    store: KnowledgeStore = app.state.knowledge
    vector = await app.state.embeddings.aembed_query("solar")
    async with app.state.db.sessionmaker() as session, session.begin():
        allowed = await store.allowed_source_ids(session, GLOBAL)
        await store.apply_search_settings(session)
        assert (await session.execute(text("SHOW hnsw.iterative_scan"))).scalar() == "strict_order"
        assert (await session.execute(text("SHOW hnsw.ef_search"))).scalar() == str(store.hnsw_ef_search)
        for setting in ("enable_seqscan", "enable_sort", "enable_bitmapscan"):
            await session.execute(text(f"SET LOCAL {setting} = off"))
        # (Rendered with literal values, so without the optional JSONB filter, which has no literal form.)
        statement = store.search_statement(vector, "fake:text-embedding-3-small", allowed, 5)
        sql = statement.compile(
            dialect=session.bind.dialect, compile_kwargs={"literal_binds": True, "render_postcompile": True}
        )
        plan = (await session.execute(text("EXPLAIN " + str(sql)))).scalars().all()
    assert any("ix_document_chunks_embedding_hnsw" in line for line in plan), "\n".join(plan)
