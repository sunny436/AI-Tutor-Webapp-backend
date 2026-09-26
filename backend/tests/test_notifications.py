"""Notification preferences, security alerts (queued, not sent by the API) and unsubscribe links."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.notifications.tokens import make_token, read_token
from app.ratelimit import SlidingWindowLimiter
from tests.conftest import PASSWORD, last_code, make_settings, register

IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Safari/604.1"
WINDOWS = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"


async def outbox(database: str, user_id: str | None = None) -> list[dict]:
    engine = create_async_engine(database)
    try:
        async with engine.connect() as conn:
            query = "SELECT kind, to_address, subject, body, status, user_id FROM email_outbox"
            params = {}
            if user_id:
                query += " WHERE user_id = :id"
                params["id"] = uuid.UUID(user_id)
            rows = (await conn.execute(text(query + " ORDER BY created_at"), params)).mappings().all()
            return [dict(row) for row in rows]
    finally:
        await engine.dispose()


async def _login(client, email: str, agent: str):
    response = await client.post(
        "/v1/auth/login", json={"email": email, "password": PASSWORD}, headers={"User-Agent": agent}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['session']['token']}"}


# ------------------------------------------------------------------- preferences
async def test_preferences_default_to_alerts_on_and_reminders_off(client, app):
    headers = (await register(client, app))["headers"]
    prefs = (await client.get("/v1/notifications/preferences", headers=headers)).json()
    assert prefs == {
        "version": 0,
        "dailyReminder": False,
        "streakWarning": False,
        "weeklySummary": False,
        "securityAlerts": True,
        "remindersNeedTimezone": True,
        "updatedAt": None,
    }


async def test_preferences_are_versioned(client, app):
    headers = (await register(client, app))["headers"]
    first = await client.patch(
        "/v1/notifications/preferences",
        json={"version": 0, "set": {"dailyReminder": True, "securityAlerts": False}},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert (first.json()["dailyReminder"], first.json()["securityAlerts"], first.json()["version"]) == (True, False, 1)
    reset = await client.patch(
        "/v1/notifications/preferences", json={"version": 1, "reset": ["securityAlerts"]}, headers=headers
    )
    assert reset.json()["securityAlerts"] is True and reset.json()["version"] == 2
    stale = await client.patch(
        "/v1/notifications/preferences", json={"version": 1, "set": {"weeklySummary": True}}, headers=headers
    )
    assert stale.status_code == 409 and stale.json()["error"]["current"]["version"] == 2
    empty = await client.patch("/v1/notifications/preferences", json={"version": 2}, headers=headers)
    assert empty.status_code == 200 and empty.json()["version"] == 2
    for bad in ({"dailyReminder": None}, {"dailyReminder": "yes please"}, {"sms": True}):
        response = await client.patch("/v1/notifications/preferences", json={"version": 2, "set": bad}, headers=headers)
        assert response.status_code == 422, bad


async def test_reminders_need_a_time_zone(client, app):
    headers = (await register(client, app))["headers"]
    me = (await client.get("/v1/me", headers=headers)).json()
    await client.patch(
        "/v1/me/profile", json={"version": me["profileVersion"], "set": {"timezone": "Asia/Kolkata"}}, headers=headers
    )
    assert (await client.get("/v1/notifications/preferences", headers=headers)).json()["remindersNeedTimezone"] is False


# ---------------------------------------------------------------- security alerts
async def test_a_sign_in_from_a_new_kind_of_device_queues_an_alert(client, app, database):
    account = await register(client, app)
    sent_before = len(app.state.email_sender.outbox)
    await _login(client, account["email"], IPHONE)
    await _login(client, account["email"], IPHONE)  # the same kind of device again: no second alert
    alerts = await outbox(database, account["user"]["id"])
    assert [row["kind"] for row in alerts] == ["security_sign_in"]
    alert = alerts[0]
    assert alert["status"] == "pending" and alert["to_address"] == account["email"]
    assert "Safari on iPhone" in alert["body"]
    assert "127.0.0" not in alert["body"]  # a device, never an address
    assert len(app.state.email_sender.outbox) == sent_before  # the API queues; only the worker sends


async def test_no_sign_in_alert_when_alerts_are_off(client, app, database):
    account = await register(client, app)
    await client.patch(
        "/v1/notifications/preferences",
        json={"version": 0, "set": {"securityAlerts": False}},
        headers=account["headers"],
    )
    await _login(client, account["email"], WINDOWS)
    assert await outbox(database, account["user"]["id"]) == []


async def test_a_password_change_or_reset_is_always_reported(client, app, database):
    account = await register(client, app)
    await client.patch(
        "/v1/notifications/preferences",
        json={"version": 0, "set": {"securityAlerts": False}},
        headers=account["headers"],
    )
    changed = await client.post(
        "/v1/auth/password/change",
        json={"currentPassword": PASSWORD, "newPassword": "a brand new password"},
        headers=account["headers"],
    )
    assert changed.status_code == 204
    await client.post("/v1/auth/password/forgot", json={"email": account["email"]})
    reset = await client.post(
        "/v1/auth/password/reset",
        json={"email": account["email"], "code": last_code(app, account["email"]), "newPassword": "and another one!"},
    )
    assert reset.status_code == 200
    kinds = [row["kind"] for row in await outbox(database, account["user"]["id"])]
    assert kinds == ["security_password_changed", "security_password_changed"]


# ------------------------------------------------------------------- unsubscribe
async def test_an_unsubscribe_link_turns_off_exactly_that_email(client, app):
    account = await register(client, app)
    headers = account["headers"]
    await client.patch(
        "/v1/notifications/preferences",
        json={"version": 0, "set": {"dailyReminder": True, "weeklySummary": True}},
        headers=headers,
    )
    token = make_token(app.state.settings, uuid.UUID(account["user"]["id"]), "weekly_summary")
    response = await client.post("/v1/notifications/unsubscribe", json={"token": token})  # no session
    assert response.status_code == 200 and response.json() == {"kind": "weekly_summary", "unsubscribed": True}
    prefs = (await client.get("/v1/notifications/preferences", headers=headers)).json()
    assert (prefs["weeklySummary"], prefs["dailyReminder"], prefs["version"]) == (False, True, 2)

    again = await client.post("/v1/notifications/unsubscribe", json={"token": token})
    assert again.status_code == 200
    assert (await client.get("/v1/notifications/preferences", headers=headers)).json()["version"] == 2

    sign_in = make_token(app.state.settings, uuid.UUID(account["user"]["id"]), "security_sign_in")
    assert (await client.post("/v1/notifications/unsubscribe", json={"token": sign_in})).status_code == 200
    assert (await client.get("/v1/notifications/preferences", headers=headers)).json()["securityAlerts"] is False


async def test_forged_or_foreign_tokens_are_refused(client, app):
    account = await register(client, app)
    settings = app.state.settings
    user_id = uuid.UUID(account["user"]["id"])
    good = make_token(settings, user_id, "daily_reminder")
    encoded, signature = good.split(".")
    other_payload = make_token(settings, uuid.uuid4(), "daily_reminder").split(".")[0]
    forged = [
        f"{encoded}.{'0' * 32}",  # the signature does not match
        f"{other_payload}.{signature}",  # a signature moved to another user
        make_token(make_settings(secret_key="another-secret-key-that-is-long-enough-99"), user_id, "daily_reminder"),
        "not-a-token-at-all",
        f"{encoded}",
    ]
    for token in forged:
        response = await client.post("/v1/notifications/unsubscribe", json={"token": token})
        assert response.status_code in (400, 422), token
        if response.status_code == 400:
            assert response.json()["error"]["code"] == "invalid_token"
    assert read_token(settings, good) == (user_id, "daily_reminder")
    assert read_token(settings, f"{encoded[:-2]}xx.{signature}") is None
    # A password-changed notice has no unsubscribe link: nobody can switch it off.
    with pytest.raises(ValueError):
        make_token(settings, user_id, "security_password_changed")


async def test_a_token_for_a_deleted_account_changes_nothing(client, app):
    account = await register(client, app)
    token = make_token(app.state.settings, uuid.UUID(account["user"]["id"]), "daily_reminder")
    assert (
        await client.request("DELETE", "/v1/me", json={"password": PASSWORD}, headers=account["headers"])
    ).status_code == 204
    response = await client.post("/v1/notifications/unsubscribe", json={"token": token})
    assert response.status_code == 200


async def test_unsubscribing_is_rate_limited_per_address(client, app):
    app.state.unsubscribe_limiter = SlidingWindowLimiter(limit=2, window_s=60)
    for _ in range(2):
        assert (await client.post("/v1/notifications/unsubscribe", json={"token": "x" * 20})).status_code == 400
    assert (await client.post("/v1/notifications/unsubscribe", json={"token": "x" * 20})).status_code == 429
