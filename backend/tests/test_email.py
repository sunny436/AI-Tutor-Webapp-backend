"""Ollastack Agent Mail sender: request shape, failures, production settings, and the sign-up path."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser

import httpx
import pytest

from app.auth.emails import EmailDeliveryError, OllastackEmailSender, SmtpEmailSender, build_email_sender
from app.db.models import AuthVerification
from app.main import create_app
from tests.conftest import PASSWORD, make_settings, register
from tests.test_platform import PRODUCTION_LIKE

TOKEN = "olla-test-token-do-not-log"
OLLASTACK = dict(email_backend="ollastack", ollastack_token=TOKEN, ollastack_mailbox_id="mbx_123")


def sender_with(handler) -> tuple[OllastackEmailSender, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(record))
    return OllastackEmailSender(make_settings(**OLLASTACK), http_client=client), seen


def ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"success": True, "data": {"id": "msg_1", "deliveryStatus": "sent"}})


async def test_sends_plain_text_from_the_configured_mailbox():
    sender, seen = sender_with(ok)
    await sender.send("user@example.com", "Your code", "Use this code: 123456")
    (request,) = seen
    assert request.method == "POST"
    assert str(request.url) == "https://login.ollastack.com/api/mailboxes/mbx_123/send"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert json.loads(request.content) == {
        "to": "user@example.com",
        "subject": "Your code",
        "text": "Use this code: 123456",
    }


async def test_sends_the_optional_html_part_to_ollastack():
    sender, seen = sender_with(ok)
    await sender.send("user@example.com", "Your code", "Use this code: 123456", "<p>Use this code: 123456</p>")
    assert json.loads(seen[0].content) == {
        "to": "user@example.com",
        "subject": "Your code",
        "text": "Use this code: 123456",
        "html": "<p>Use this code: 123456</p>",
    }


async def test_smtp_sends_text_then_html_as_multipart_alternative():
    sender = SmtpEmailSender(make_settings(email_backend="smtp"))
    sent = []
    sender._send_sync = sent.append
    await sender.send("user@example.com", "Hello", "Plain ✓", "<p>HTML ✓</p>")
    parsed = BytesParser(policy=policy.default).parsebytes(sent[0].as_bytes(policy=policy.default))
    parts = list(parsed.iter_parts())
    assert parsed.get_content_type() == "multipart/alternative"
    assert [part.get_content_type() for part in parts] == ["text/plain", "text/html"]
    assert "Plain ✓" in parts[0].get_content() and "HTML ✓" in parts[1].get_content()


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(401, json={"error": {"code": "UNAUTHORIZED"}}), "HTTP 401, UNAUTHORIZED"),
        (httpx.Response(500, text="upstream down"), "HTTP 500, no code"),
        (httpx.Response(200, json={"success": False, "error": {"code": "QUOTA"}}), "HTTP 200, QUOTA"),
        (httpx.Response(200, json={"success": True, "data": {"deliveryStatus": "failed"}}), "delivery status failed"),
    ],
)
async def test_refused_or_failed_sends_raise_without_secrets(response, expected, caplog):
    sender, _ = sender_with(lambda request: response)
    with pytest.raises(EmailDeliveryError, match=expected) as info:
        await sender.send("user@example.com", "Your code", "123456")
    for text in [str(info.value), *(r.getMessage() + str(r.__dict__) for r in caplog.records)]:
        assert TOKEN not in text and "user@example.com" not in text and "123456" not in text


async def test_network_failure_raises_a_delivery_error():
    def boom(request):
        raise httpx.ConnectError("no route")

    sender, _ = sender_with(boom)
    with pytest.raises(EmailDeliveryError, match="unreachable"):
        await sender.send("user@example.com", "Your code", "123456")


def test_backend_selection():
    assert isinstance(build_email_sender(make_settings(**OLLASTACK)), OllastackEmailSender)
    assert isinstance(build_email_sender(make_settings(email_backend="smtp")), SmtpEmailSender)


def test_production_accepts_ollastack_only_when_configured():
    create_app(make_settings(**{**PRODUCTION_LIKE, **OLLASTACK}))
    with pytest.raises(RuntimeError, match="OLLASTACK_TOKEN and OLLASTACK_MAILBOX_ID"):
        create_app(make_settings(**{**PRODUCTION_LIKE, **OLLASTACK, "ollastack_mailbox_id": ""}))
    with pytest.raises(RuntimeError, match="EMAIL_BACKEND must be smtp or ollastack"):
        create_app(make_settings(**{**PRODUCTION_LIKE, "email_backend": "memory"}))


async def test_a_sign_in_code_goes_out_through_ollastack(app, client):
    """Better Auth stores the code (hashed); the API emails it through the configured sender."""
    sender, seen = sender_with(ok)
    app.state.email_sender = sender
    stored = base64.urlsafe_b64encode(hashlib.sha256(b"135790").digest()).rstrip(b"=").decode()
    async with app.state.db.sessionmaker() as db:
        db.add(
            AuthVerification(
                identifier="sign-in-otp-gil@example.com",
                value=f"{stored}:0",
                expires_at=datetime.now(UTC) + timedelta(minutes=15),
            )
        )
        await db.commit()
    internal = {"X-Internal-Token": app.state.settings.auth_internal_token.get_secret_value()}
    response = await client.post(
        "/internal/auth/code", json={"email": "gil@example.com", "type": "sign-in", "otp": "135790"}, headers=internal
    )
    assert response.status_code == 202
    (request,) = seen
    body = json.loads(request.content)
    assert body["to"] == "gil@example.com" and "sign-in code" in body["subject"]
    assert "135790" in body["text"]
    assert "135790" in body["html"] and "padhai-mark-email.png" not in body["html"]


async def test_an_email_change_reports_503_when_ollastack_refuses(app, client):
    account = await register(client, app)
    sender, _ = sender_with(lambda request: httpx.Response(401, json={"error": {"code": "UNAUTHORIZED"}}))
    app.state.email_sender = sender
    response = await client.post(
        "/v1/me/email/change",
        json={"newEmail": "hal@example.com", "password": PASSWORD},
        headers=account["headers"],
    )
    assert response.status_code == 503
