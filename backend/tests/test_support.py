"""Support requests: plain text, idempotent, limited, forwarded through the outbox."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.jobs.runner import run_once
from tests.conftest import make_settings, register

SUPPORT = "support@padhai.example"


@pytest.fixture
def settings():
    return make_settings(support_email=SUPPORT)


def request(**overrides) -> dict:
    return {
        "requestId": str(uuid.uuid4()),
        "kind": "bug",
        "subject": "The chat stops",
        "message": "When I send a long question the reply stops halfway.",
    } | overrides


async def sql(database: str, statement: str, **params) -> list[dict]:
    engine = create_async_engine(database)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(statement), params)
            return [dict(row) for row in result.mappings().all()] if result.returns_rows else []
    finally:
        await engine.dispose()


async def test_a_request_is_stored_and_forwarded_to_support(client, app, database):
    account = await register(client, app)
    response = await client.post(
        "/v1/support/requests",
        json=request(page="/settings/help"),
        headers={**account["headers"], "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/140.0"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["kind"], body["subject"], body["status"]) == ("bug", "The chat stops", "open")

    [stored] = await sql(database, "SELECT message, context FROM support_requests")
    assert stored["context"]["page"] == "/settings/help" and stored["context"]["device"] == "Firefox on Linux"
    [queued] = await sql(database, "SELECT kind, to_address, subject, body, status FROM email_outbox")
    assert (queued["kind"], queued["to_address"], queued["status"]) == ("support_forward", SUPPORT, "pending")
    assert account["email"] in queued["body"] and stored["message"] in queued["body"]

    # Forwarding does not wait for the notifications rollout: it is mail to the team.
    worker = make_settings(jobs_enabled=True, support_email=SUPPORT, notifications_mode="off")
    await run_once(worker, app.state.db, app.state.email_sender)
    mail = app.state.email_sender.outbox[-1]
    assert mail["to"] == SUPPORT and mail["subject"] == "[Assistant support] bug: The chat stops"


async def test_sending_the_same_request_again_returns_it(client, app, database):
    headers = (await register(client, app))["headers"]
    body = request()
    first = await client.post("/v1/support/requests", json=body, headers=headers)
    again = await client.post("/v1/support/requests", json=body, headers=headers)
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json() == again.json()
    assert len(await sql(database, "SELECT id FROM support_requests")) == 1
    assert len(await sql(database, "SELECT id FROM email_outbox")) == 1  # forwarded once


async def test_text_is_cleaned_and_headers_cannot_be_injected(client, app, database):
    headers = (await register(client, app))["headers"]
    response = await client.post(
        "/v1/support/requests",
        json=request(
            subject="Help\r\nBcc: everyone@example.com‮",
            message="Line one\r\nLine two\x00\x07 and a tab\there",
        ),
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["subject"] == "Help Bcc: everyone@example.com"
    [stored] = await sql(database, "SELECT subject, message FROM support_requests")
    assert "\r" not in stored["subject"] and "\n" not in stored["subject"]
    assert stored["message"] == "Line one\nLine two and a tab\there"
    [queued] = await sql(database, "SELECT subject FROM email_outbox")
    assert "\n" not in queued["subject"] and "\r" not in queued["subject"]


async def test_malformed_requests_are_refused(client, app):
    headers = (await register(client, app))["headers"]
    links = " ".join(f"https://example.com/{n}" for n in range(6))
    for body in (
        request(kind="complaint"),
        request(subject=""),
        request(subject="x" * 121),
        request(message="too short"),
        request(message="x" * 4001),
        request(message=f"See {links}"),
        request(page="https://evil.example/"),
        request(requestId="not-a-uuid"),
        request(userId=str(uuid.uuid4())),
    ):
        assert (await client.post("/v1/support/requests", json=body, headers=headers)).status_code == 422, body


async def test_requests_are_limited_per_hour_and_by_open_count(client, app, database):
    account = await register(client, app)
    headers = account["headers"]
    for _ in range(5):
        assert (await client.post("/v1/support/requests", json=request(), headers=headers)).status_code == 201
    limited = await client.post("/v1/support/requests", json=request(), headers=headers)
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "rate_limited"

    # 30 open requests from earlier days: a new one waits for replies first.
    await sql(database, "UPDATE support_requests SET created_at = now() - interval '3 days'")
    await sql(
        database,
        "INSERT INTO support_requests (user_id, client_request_id, kind, subject, message, created_at) "
        "SELECT :id, gen_random_uuid(), 'question', 'Old', 'An older question.', now() - interval '3 days' "
        "FROM generate_series(1, 25)",
        id=uuid.UUID(account["user"]["id"]),
    )
    crowded = await client.post("/v1/support/requests", json=request(), headers=headers)
    assert crowded.status_code == 429 and crowded.json()["error"]["code"] == "too_many_open_requests"


async def test_another_accounts_request_id_is_its_own(client, app, database):
    alice = await register(client, app)
    bob = await register(client, app)
    body = request()
    assert (await client.post("/v1/support/requests", json=body, headers=alice["headers"])).status_code == 201
    bobs = await client.post("/v1/support/requests", json=body | {"subject": "Bob's"}, headers=bob["headers"])
    assert bobs.status_code == 201 and bobs.json()["subject"] == "Bob's"  # not Alice's request back
    assert len(await sql(database, "SELECT id FROM support_requests")) == 2
