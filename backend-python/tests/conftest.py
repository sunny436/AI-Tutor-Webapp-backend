"""Test fixtures: a real PostgreSQL + pgvector database, a fake LLM, an in-memory mailbox.

The test database (`aichat_test` by default, override with TEST_DATABASE_URL) is
dropped, recreated and migrated with Alembic once per session, and every table
is truncated before each test. It never points at a production database.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import asyncpg
import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.auth.emails import MemoryEmailSender
from app.llm.fake import FakeProvider
from app.main import create_app
from app.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://aichat:aichat@127.0.0.1:5432/aichat_test")
TABLES = (
    "document_chunks, documents, knowledge_sources, "
    "usage_events, message_feedback, messages, conversations, auth_attempts, "
    "email_codes, auth_sessions, user_settings, users"
)
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
        argon2_time_cost=1,
        argon2_memory_kib=1024,
        argon2_parallelism=1,
        stream_keepalive_s=0.5,
        stream_cancel_poll_s=0.1,
        log_level="WARNING",
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
        await conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))
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
def last_code(app, email: str) -> str:
    for mail in reversed(app.state.email_sender.outbox):
        if mail["to"].lower() == email.lower():
            match = re.search(r"\b(\d{6})\b", mail["body"])
            if match:
                return match.group(1)
    raise AssertionError(f"no code emailed to {email}")


async def register(client, app, email: str | None = None, password: str = PASSWORD) -> dict:
    """Sign up + verify. Returns {"email", "token", "headers", "user"}."""
    email = email or f"user-{uuid.uuid4().hex[:10]}@example.com"
    response = await client.post("/v1/auth/signup", json={"email": email, "password": password})
    assert response.status_code == 202, response.text
    response = await client.post("/v1/auth/verify-email", json={"email": email, "code": last_code(app, email)})
    assert response.status_code == 200, response.text
    body = response.json()
    token = body["session"]["token"]
    return {"email": email, "token": token, "headers": {"Authorization": f"Bearer {token}"}, "user": body["user"]}


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
