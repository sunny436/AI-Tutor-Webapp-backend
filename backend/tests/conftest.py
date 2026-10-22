"""Test fixtures: a real PostgreSQL + pgvector database, a fake LLM, an in-memory mailbox.

The test database (`aichat_test` by default, override with TEST_DATABASE_URL) is
dropped, recreated and migrated with Alembic once per session, and every table
is truncated before each test. It never points at a production database.
"""

from __future__ import annotations

import io
import os
import re
import secrets
import subprocess
import sys
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import asyncpg
import httpx
import pytest
from langchain_core.embeddings import Embeddings
from PIL import Image
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.auth.emails import MemoryEmailSender
from app.db.models import AuthAccount, AuthSession, User
from app.llm.fake import FakeProvider
from app.main import create_app
from app.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://aichat:aichat@127.0.0.1:5432/aichat_test")
# Every application table is emptied before each test: found from the schema, not listed by
# hand, so a table added by a later migration cannot leak rows from one test into the next.
ALL_TABLES = text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'")
PASSWORD = "correct horse battery"


def _asyncpg_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def make_settings(**overrides) -> Settings:
    values = dict(
        app_env="test",
        database_url=TEST_DATABASE_URL,
        email_backend="memory",
        llm_provider="fake",
        embedding_provider="fake",
        secret_key="test-secret-key-that-is-long-enough-123456",
        auth_internal_token="test-internal-token-that-is-long-enough-1234",
        argon2_time_cost=1,
        argon2_memory_kib=1024,
        argon2_parallelism=1,
        stream_keepalive_s=0.5,
        stream_cancel_poll_s=0.1,
        log_level="WARNING",
        question_bank_tests=False,  # tests/test_assessments.py: tests the fake model writes
        intent_router="off",  # tests/test_intents.py turns it on with a fake classifier
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture(scope="session", autouse=True)
def database() -> str:
    dsn = _asyncpg_dsn(TEST_DATABASE_URL)
    name = dsn.rsplit("/", 1)[1]
    assert re.fullmatch(r"[a-z0-9_]+_test", name), "tests only run against a *_test database"
    admin = dsn.rsplit("/", 1)[0] + "/postgres"

    import asyncio

    async def recreate() -> None:
        conn = await asyncpg.connect(admin)
        try:
            await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            await conn.execute(f'CREATE DATABASE "{name}"')
        finally:
            await conn.close()

    # In a separate thread, so this event loop never touches pytest-asyncio's.
    worker = threading.Thread(target=lambda: asyncio.run(recreate()))
    worker.start()
    worker.join()
    subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"url={TEST_DATABASE_URL}", "upgrade", "head"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return TEST_DATABASE_URL


@pytest.fixture(autouse=True)
async def clean_tables(database):
    engine = create_async_engine(database)
    async with engine.begin() as conn:
        names = (await conn.execute(ALL_TABLES)).scalars().all()
        await conn.execute(text("TRUNCATE " + ", ".join(f'"{name}"' for name in names) + " CASCADE"))
    await engine.dispose()


@pytest.fixture
def fake_llm() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
async def app(settings, fake_llm):
    application = create_app(settings, llm=fake_llm, email_sender=MemoryEmailSender())
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


# ------------------------------------------------------------------ helpers
def image_bytes(fmt: str = "PNG", size: tuple[int, int] = (64, 64), color=(200, 80, 40), **save) -> bytes:
    """A real image file, made in memory."""
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, fmt, **save)
    return buffer.getvalue()


def last_code(app, email: str) -> str:
    for mail in reversed(app.state.email_sender.outbox):
        if mail["to"].lower() == email.lower():
            match = re.search(r"\b(\d{6})\b", mail["body"])
            if match:
                return match.group(1)
    raise AssertionError(f"no code emailed to {email}")


async def sign_in(app, email: str, user_agent: str = "pytest", created_at: datetime | None = None) -> dict:
    """A new session for an existing account, as the web app's Better Auth writes one: the raw
    token in `token`, its SHA-256 in `token_hash` by the 0012 trigger. Returns {"token", "headers"}."""
    token = secrets.token_urlsafe(24)
    async with app.state.db.sessionmaker() as db:
        user_id = await db.scalar(select(User.id).where(User.email == email))
        assert user_id is not None, f"no account for {email}"
        now = datetime.now(UTC)
        db.add(
            AuthSession(
                user_id=user_id,
                token=token,
                expires_at=now + timedelta(days=30),
                user_agent=user_agent,
                created_at=created_at or now,
            )
        )
        await db.commit()
    return {"token": token, "headers": {"Authorization": f"Bearer {token}"}}


async def register(
    client, app, email: str | None = None, password: str | None = PASSWORD, user_agent: str = "pytest"
) -> dict:
    """A verified account and a signed-in session, made the way Better Auth makes them (sign-up
    itself happens in the web app). password=None makes an account without one (Google only).
    Returns {"email", "token", "headers", "user"}."""
    email = email or f"user-{uuid.uuid4().hex[:10]}@example.com"
    async with app.state.db.sessionmaker() as db:
        user = User(email=email, email_verified=True)
        db.add(user)
        await db.flush()
        if password is not None:
            hashed = await app.state.passwords.hash(password)
            db.add(AuthAccount(user_id=user.id, account_id=str(user.id), provider_id="credential", password=hashed))
        await db.commit()
    session = await sign_in(app, email, user_agent=user_agent)
    response = await client.get("/v1/me", headers=session["headers"])
    assert response.status_code == 200, response.text
    return {"email": email, **session, "user": response.json()}


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    import json

    events = []
    for frame in raw.split("\n\n"):
        name = re.search(r"^event: (.+)$", frame, re.M)
        data = re.search(r"^data: (.+)$", frame, re.M)
        if name and data:
            events.append((name.group(1), json.loads(data.group(1))))
    return events


async def stream_chat(client, headers, message: str, conversation_id: str | None = None):
    body = {"message": message}
    if conversation_id:
        body["conversationId"] = conversation_id
    response = await client.post("/v1/chat/stream", json=body, headers=headers)
    return response, parse_sse(response.text) if response.status_code == 200 else []


# ------------------------------------------------------------------ RAG helpers
class SpyEmbeddings(Embeddings):
    """Wraps an Embeddings object; counts calls and can be switched to fail."""

    def __init__(self, inner, model: str | None = None):
        from app.rag.embeddings import embedding_model_id

        self.inner = inner
        self.model = model or embedding_model_id(inner)
        self.dimensions = getattr(inner, "dimensions", 1536)
        self.configured = True
        self.calls = 0
        self.fail_with = None

    async def aembed_documents(self, texts):
        self.calls += 1
        if self.fail_with:
            raise self.fail_with
        return await self.inner.aembed_documents(texts)

    async def aembed_query(self, text):
        self.calls += 1
        if self.fail_with:
            raise self.fail_with
        return await self.inner.aembed_query(text)

    def embed_documents(self, texts):  # pragma: no cover - async app
        return self.inner.embed_documents(texts)

    def embed_query(self, text):  # pragma: no cover - async app
        return self.inner.embed_query(text)


async def ingest_docs(
    app, docs: dict[str, str], *, source: str = "kb", owner_user_id=None, metadata=None, service=None
):
    """Ingest {uri: text} into a source through the real IngestionService."""
    from app.rag.ingestion import IngestionService, parse_document

    store = app.state.knowledge
    service = service or IngestionService(store, app.state.embeddings, app.state.settings)
    src = await store.get_or_create_source(source, owner_user_id=owner_user_id)
    results = []
    for uri, body in docs.items():
        document = parse_document(
            uri, body.encode("utf-8"), max_bytes=app.state.settings.rag_max_document_bytes, metadata=metadata
        )
        results.append(await service.ingest(src.id, document))
    return src, results
