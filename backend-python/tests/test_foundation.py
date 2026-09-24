"""Foundation checks: pgvector, schema/migration parity and the committed API contract.

(Retrieval, the LangGraph graph and the context budget have their own test_rag_* suites.)
"""

import json
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db import models  # noqa: F401
from app.db.base import Base

ROOT = Path(__file__).resolve().parents[1]


async def test_pgvector_is_enabled_and_usable(database):
    engine = create_async_engine(database)
    async with engine.begin() as conn:
        version = await conn.scalar(text("select extversion from pg_extension where extname = 'vector'"))
        assert version
        await conn.execute(text("create temporary table vec_probe (id int primary key, embedding vector(3))"))
        await conn.execute(text("create index on vec_probe using hnsw (embedding vector_cosine_ops)"))
        await conn.execute(text("insert into vec_probe values (1, '[1,0,0]'), (2, '[0,1,0]'), (3, '[0.9,0.1,0]')"))
        rows = (
            (await conn.execute(text("select id from vec_probe order by embedding <=> '[1,0,0]' limit 2")))
            .scalars()
            .all()
        )
        assert rows == [1, 3]
    await engine.dispose()


async def test_migrations_match_models(database):
    engine = create_async_engine(database)
    async with engine.connect() as conn:
        diff = await conn.run_sync(
            lambda sync: compare_metadata(MigrationContext.configure(sync, opts={"compare_type": True}), Base.metadata)
        )
    await engine.dispose()
    assert diff == []


def test_openapi_contract_is_committed_and_current():
    from scripts.export_openapi import build_openapi

    committed = json.loads((ROOT.parent / "docs" / "openapi.json").read_text(encoding="utf-8"))
    assert committed == build_openapi(), "docs/openapi.json is stale: run `python scripts/export_openapi.py`"
