"""The extension points the AI-Tutor phase builds on: context seam, pgvector, schema, contract."""

import asyncio
import json
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.context.base import ContextBlock, ContextRequest
from app.context.pipeline import ContextPipeline, render_context
from app.db import models  # noqa: F401
from app.db.base import Base
from tests.conftest import register, stream_chat

ROOT = Path(__file__).resolve().parents[1]


class StaticProvider:
    def __init__(self, name, blocks=(), delay=0.0, error=None):
        self.name, self.blocks, self.delay, self.error = name, list(blocks), delay, error

    async def provide(self, request):
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.blocks


async def test_context_pipeline_is_concurrent_and_fail_soft():
    import uuid

    request = ContextRequest(user_id=uuid.uuid4(), conversation_id=uuid.uuid4(), query="q")
    pipeline = ContextPipeline(
        [
            StaticProvider("a", [ContextBlock("alpha", "src:a")], delay=0.2),
            StaticProvider("b", [ContextBlock("beta", "src:b")], delay=0.2),
            StaticProvider("slow", [ContextBlock("never", "src:slow")], delay=5),
            StaticProvider("broken", error=RuntimeError("boom")),
        ],
        timeout_s=0.5,
    )
    started = asyncio.get_running_loop().time()
    blocks = await pipeline.gather(request)
    assert [b.text for b in blocks] == ["alpha", "beta"]
    assert asyncio.get_running_loop().time() - started < 1.5
    assert "source: src:a" in render_context(blocks) and render_context([]) == ""
    assert await ContextPipeline([], 1).gather(request) == []


async def test_context_seam_reaches_the_prompt(client, app, fake_llm, monkeypatch):
    from app.chat import assistant, service

    def config(user, conversation):
        return assistant.AssistantConfig(
            system_prompt=assistant.SYSTEM_PROMPT,
            context_providers=[StaticProvider("docs", [ContextBlock("The sky is blue.", "docs:sky")])],
        )

    monkeypatch.setattr(service, "resolve_assistant_config", config)
    account = await register(client, app)
    await stream_chat(client, account["headers"], "What colour is the sky?")
    prompt = fake_llm.calls[-1]
    assert prompt[1].role == "system" and "The sky is blue." in prompt[1].content
    assert prompt[-1].content == "What colour is the sky?"


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
