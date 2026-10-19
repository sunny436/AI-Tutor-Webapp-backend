"""Cross-cutting behaviour: limits, errors, health, database failures, production safety."""

import httpx
import pytest

from app.auth.emails import MemoryEmailSender
from app.llm.fake import FakeProvider
from app.main import create_app
from tests.conftest import make_settings, register


async def test_health_ready_and_request_id(client):
    r = await client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "release": "development", "files": "available"}
    assert len(r.headers["x-request-id"]) == 32
    r = await client.get("/ready", headers={"X-Request-ID": "trace-123"})
    assert r.status_code == 200 and r.json()["database"] is True
    assert r.headers["x-request-id"] == "trace-123"
    # a malformed incoming id is replaced, never reflected
    r = await client.get("/health", headers={"X-Request-ID": "bad id\r\nx"})
    assert r.headers["x-request-id"] != "bad id\r\nx"


async def test_oversized_body_is_413(client, app):
    account = await register(client, app)
    big = {"message": "x" * 70_000}
    r = await client.post("/v1/chat/stream", json=big, headers=account["headers"])
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"


async def test_unknown_route_uses_error_envelope(client):
    r = await client.get("/v1/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


async def test_database_unavailable_is_503_without_details():
    settings = make_settings(
        database_url="postgresql+asyncpg://aichat:aichat@127.0.0.1:1/aichat_test", db_connect_timeout_s=1.0
    )
    application = create_app(settings, llm=FakeProvider(), email_sender=MemoryEmailSender())
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://t") as client:
            r = await client.get("/v1/me", headers={"Authorization": "Bearer any-token"})
            assert r.status_code == 503
            assert r.json()["error"]["code"] == "service_unavailable"
            assert "127.0.0.1" not in r.text and "asyncpg" not in r.text.lower()
            ready = await client.get("/ready")
            assert ready.status_code == 503 and ready.json()["database"] is False


PRODUCTION_LIKE = dict(
    app_env="production",
    app_name="PadhAI",
    secret_key="s" * 40,
    llm_provider="openai_compatible",
    embedding_provider="openai_compatible",
    email_backend="smtp",
    database_url="postgresql+asyncpg://u:p@db/x",
)


def test_production_refuses_unsafe_configuration():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(make_settings(**{**PRODUCTION_LIKE, "secret_key": "short"}))
    with pytest.raises(RuntimeError, match="AUTH_INTERNAL_TOKEN"):
        create_app(make_settings(**{**PRODUCTION_LIKE, "auth_internal_token": ""}))
    with pytest.raises(RuntimeError, match="LLM_PROVIDER=fake"):
        create_app(make_settings(**{**PRODUCTION_LIKE, "llm_provider": "fake"}))
    with pytest.raises(RuntimeError, match="EMBEDDING_PROVIDER=fake"):
        create_app(make_settings(**{**PRODUCTION_LIKE, "embedding_provider": "fake"}))
    with pytest.raises(RuntimeError, match="APP_NAME must be PadhAI"):
        create_app(make_settings(**{**PRODUCTION_LIKE, "app_name": "Assistant"}))
    with pytest.raises(RuntimeError, match="PUBLIC_APP_URL must be a bare HTTPS origin"):
        create_app(make_settings(**{**PRODUCTION_LIKE, "public_app_url": "https://padhai.example/path"}))


def test_production_hides_api_docs():
    app = create_app(make_settings(**PRODUCTION_LIKE))
    assert app.docs_url is None and app.openapi_url is None and app.redoc_url is None


def test_release_is_read_from_the_release_root(tmp_path):
    from app.health import RELEASE_FILE, read_release

    # the file sits at the root of the release: backend/app/health.py -> ../../RELEASE
    assert RELEASE_FILE.parent.name != "backend" and (RELEASE_FILE.parent / "backend").is_dir()
    release = tmp_path / "RELEASE"
    release.write_text("commit=0123456789abcdef0123456789abcdef01234567\nprepared=2026-09-24T00:00:00Z\n")
    assert read_release(release) == "0123456789abcdef0123456789abcdef01234567"
    assert read_release(tmp_path / "missing") == "development"
    release.write_text("prepared=2026-09-24T00:00:00Z\n")
    assert read_release(release) == "development"
