"""The API's side of identity, now that the web app's Better Auth signs people in: the session
lookup, re-authentication and its throttle, deletion, the internal routes Better Auth calls, and
retention. (Sign-up, codes and password flows are Better Auth's: e2e/auth.e2e.ts.)"""

import asyncio
import base64
import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update

from app.auth.retention import purge_expired
from app.auth.service import SIGNIN_LIMIT, SIGNIN_SCOPE
from app.db.models import (
    AuthAccount,
    AuthAttempt,
    AuthSession,
    AuthTwoFactor,
    AuthVerification,
    User,
    UserNotification,
)
from tests.conftest import PASSWORD, register, sign_in

INTERNAL = {"X-Internal-Token": "test-internal-token-that-is-long-enough-1234"}


def _code_hash(code: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(code.encode()).digest()).rstrip(b"=").decode()


async def test_sessions_are_found_by_token_hash_old_and_new(client, app):
    account = await register(client, app)
    async with app.state.db.sessionmaker() as s:
        row = await s.scalar(select(AuthSession).where(AuthSession.token == account["token"]))
        # Better Auth writes only the token; the 0012 trigger stores its SHA-256 beside it.
        assert row.token_hash == hashlib.sha256(account["token"].encode()).hexdigest()
        # A session from before 0012 has only the hash, and still works (deploy or rollback window).
        legacy = "legacy-token-made-by-older-code"
        s.add(
            AuthSession(
                user_id=row.user_id,
                token_hash=hashlib.sha256(legacy.encode()).hexdigest(),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        await s.commit()
    assert (await client.get("/v1/me", headers={"Authorization": f"Bearer {legacy}"})).status_code == 200
    assert (await client.get("/v1/me", headers={"Authorization": "Bearer not-a-session"})).status_code == 401


async def test_expired_and_unverified_sessions_are_refused(client, app):
    account = await register(client, app)
    async with app.state.db.sessionmaker() as s:
        await s.execute(update(User).where(User.email == account["email"]).values(email_verified=False))
        await s.commit()
    refused = await client.get("/v1/me", headers=account["headers"])
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "email_not_verified"
    async with app.state.db.sessionmaker() as s:
        await s.execute(update(User).where(User.email == account["email"]).values(email_verified=True))
        await s.execute(
            update(AuthSession)
            .where(AuthSession.token == account["token"])
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    assert (await client.get("/v1/me", headers=account["headers"])).status_code == 401


async def test_the_api_moves_last_seen_but_never_the_expiry(client, app):
    account = await register(client, app)
    hour_ago = datetime.now(UTC) - timedelta(hours=2)
    async with app.state.db.sessionmaker() as s:
        await s.execute(update(AuthSession).where(AuthSession.token == account["token"]).values(last_seen_at=hour_ago))
        await s.commit()
        before = await s.scalar(select(AuthSession.expires_at).where(AuthSession.token == account["token"]))
    assert (await client.get("/v1/me", headers=account["headers"])).status_code == 200
    async with app.state.db.sessionmaker() as s:
        row = await s.scalar(select(AuthSession).where(AuthSession.token == account["token"]))
    assert row.last_seen_at > hour_ago and row.expires_at == before


async def test_logout_ends_the_session(client, app):
    account = await register(client, app)
    assert (await client.post("/v1/auth/logout", headers=account["headers"])).status_code == 204
    assert (await client.get("/v1/me", headers=account["headers"])).status_code == 401


async def test_parallel_wrong_passwords_never_pass_the_limit(client, app):
    """The per-account limit holds under a burst: the attempt is counted under an advisory lock
    before argon2 runs, so parallel requests cannot all read the same count. The pool is not held
    while hashing: the student's other requests keep answering during the burst."""
    account = await register(client, app)
    burst = [
        client.request("DELETE", "/v1/me", json={"password": "wrong-password"}, headers=account["headers"])
        for _ in range(SIGNIN_LIMIT + 5)
    ]
    reads = [client.get("/v1/me", headers=account["headers"]) for _ in range(5)]
    results = await asyncio.gather(*burst, *reads)
    statuses = sorted(r.status_code for r in results[: len(burst)])
    assert statuses.count(401) == SIGNIN_LIMIT and statuses.count(429) == 5, statuses
    assert all(r.status_code == 200 for r in results[len(burst) :])
    async with app.state.db.sessionmaker() as s:
        counted = await s.scalar(select(func.count()).select_from(AuthAttempt).where(AuthAttempt.scope == SIGNIN_SCOPE))
    assert counted == SIGNIN_LIMIT
    # Even the right password waits for the window now.
    late = await client.request("DELETE", "/v1/me", json={"password": PASSWORD}, headers=account["headers"])
    assert late.status_code == 429


async def test_an_account_without_a_password_reauthenticates_by_a_recent_sign_in(client, app):
    fresh = await register(client, app, password=None)
    assert (await client.request("DELETE", "/v1/me", json={}, headers=fresh["headers"])).status_code == 204

    stale = await register(client, app, password=None)
    old = await sign_in(app, stale["email"], created_at=datetime.now(UTC) - timedelta(hours=1))
    refused = await client.request("DELETE", "/v1/me", json={}, headers=old["headers"])
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "reauth_required"

    with_password = await register(client, app)
    missing = await client.request("DELETE", "/v1/me", json={}, headers=with_password["headers"])
    assert missing.status_code == 422


async def test_deletion_removes_the_address_codes_and_says_so(client, app):
    account = await register(client, app)
    async with app.state.db.sessionmaker() as s:
        s.add(
            AuthVerification(
                identifier=f"forget-password-otp-{account['email']}",
                value=f"{_code_hash('123456')}:0",
                expires_at=datetime.now(UTC) + timedelta(minutes=15),
            )
        )
        await s.commit()
    deleted = await client.request("DELETE", "/v1/me", json={"password": PASSWORD}, headers=account["headers"])
    assert deleted.status_code == 204
    async with app.state.db.sessionmaker() as s:
        assert await s.scalar(select(func.count()).select_from(AuthVerification)) == 0
        assert await s.scalar(select(func.count()).select_from(AuthAccount)) == 0
    mail = app.state.email_sender.outbox[-1]
    assert mail["to"] == account["email"] and "deleted" in mail["subject"]


async def test_internal_routes_need_the_token(client, app):
    body = {"email": "x@example.com", "type": "sign-in", "otp": "123456"}
    assert (await client.post("/internal/auth/code", json=body)).status_code == 404
    wrong = {"X-Internal-Token": "test-internal-token-that-is-long-enough-XXXX"}
    assert (await client.post("/internal/auth/code", json=body, headers=wrong)).status_code == 404
    assert "/internal/auth/code" not in app.openapi()["paths"]


async def test_a_code_is_emailed_only_when_better_auth_just_stored_it(client, app):
    email = "kit@example.com"
    async with app.state.db.sessionmaker() as s:
        s.add(
            AuthVerification(
                identifier=f"sign-in-otp-{email}",
                value=f"{_code_hash('424242')}:0",
                expires_at=datetime.now(UTC) + timedelta(minutes=15),
            )
        )
        await s.commit()
    outbox = app.state.email_sender.outbox
    forged = await client.post(
        "/internal/auth/code", json={"email": email, "type": "sign-in", "otp": "111111"}, headers=INTERNAL
    )
    assert forged.status_code == 202 and outbox == []
    other = await client.post(
        "/internal/auth/code",
        json={"email": "victim@example.com", "type": "sign-in", "otp": "424242"},
        headers=INTERNAL,
    )
    assert other.status_code == 202 and outbox == []
    sent = await client.post(
        "/internal/auth/code", json={"email": email.upper(), "type": "sign-in", "otp": "424242"}, headers=INTERNAL
    )
    assert sent.status_code == 202
    assert len(outbox) == 1 and outbox[0]["to"] == email and "424242" in outbox[0]["body"]


async def test_sign_in_alert_only_for_a_new_device_and_only_for_real_sessions(client, app):
    phone = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Version/17.0 Mobile Safari/604.1"
    laptop = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36"
    account = await register(client, app, user_agent=laptop)
    async with app.state.db.sessionmaker() as s:
        user = await s.scalar(select(User).where(User.email == account["email"]))
        user_id = user.id

    async def event(session_token: str) -> None:
        async with app.state.db.sessionmaker() as s:
            session_id = await s.scalar(select(AuthSession.id).where(AuthSession.token == session_token))
        body = {"kind": "sign_in", "userId": str(user_id), "sessionId": str(session_id)}
        assert (await client.post("/internal/auth/events", json=body, headers=INTERNAL)).status_code == 202

    outbox = app.state.email_sender.outbox
    await event(account["token"])
    # The sign-up's own session gets the best-effort welcome, never a sign-in alert.
    assert [mail["subject"] for mail in outbox] == ["Welcome to Assistant: your personal AI tutor"]
    assert "because you just created" in outbox[0]["body"]
    assert "You get this email once." not in outbox[0]["body"]
    assert outbox[0]["html"] is not None
    outbox.clear()
    async with app.state.db.sessionmaker() as s:
        user = await s.get(User, user_id)
        user.created_at = datetime.now(UTC) - timedelta(days=3)  # not a brand-new account
        await s.commit()
    await event((await sign_in(app, account["email"], user_agent=laptop))["token"])
    assert outbox == []  # a device this account already uses
    await event((await sign_in(app, account["email"], user_agent=phone))["token"])
    assert len(outbox) == 1 and "New sign-in" in outbox[0]["subject"]
    # Forged: a session id that does not exist, or one that is not fresh, counts for nothing.
    old = await sign_in(app, account["email"], user_agent=phone, created_at=datetime.now(UTC) - timedelta(hours=1))
    await event(old["token"])
    forged = {"kind": "sign_in", "userId": str(user_id), "sessionId": "00000000-0000-0000-0000-000000000000"}
    assert (await client.post("/internal/auth/events", json=forged, headers=INTERNAL)).status_code == 202
    assert len(outbox) == 1
    async with app.state.db.sessionmaker() as s:
        kinds = list(await s.scalars(select(UserNotification.kind).where(UserNotification.user_id == user_id)))
    assert kinds == ["security_sign_in"]


async def test_password_and_google_notices_need_the_change_to_be_real(client, app):
    account = await register(client, app)
    async with app.state.db.sessionmaker() as s:
        user = await s.scalar(select(User).where(User.email == account["email"]))
        user.created_at = datetime.now(UTC) - timedelta(days=3)
        await s.commit()
        user_id = str(user.id)
    outbox = app.state.email_sender.outbox
    # The credential was written moments ago (register): a password event counts.
    body = {"kind": "password_reset", "userId": user_id}
    assert (await client.post("/internal/auth/events", json=body, headers=INTERNAL)).status_code == 202
    assert len(outbox) == 1 and "password was changed" in outbox[0]["subject"]
    # No Google account: a google_linked event is ignored.
    body = {"kind": "google_linked", "userId": user_id}
    await client.post("/internal/auth/events", json=body, headers=INTERNAL)
    assert len(outbox) == 1
    async with app.state.db.sessionmaker() as s:
        s.add(AuthAccount(user_id=user.id, account_id="google-sub-1", provider_id="google"))
        await s.commit()
    await client.post("/internal/auth/events", json=body, headers=INTERNAL)
    assert len(outbox) == 2 and "Google" in outbox[1]["subject"]


async def test_two_step_accounts_confirm_with_a_recent_full_sign_in_and_are_told_of_changes(client, app):
    account = await register(client, app)
    async with app.state.db.sessionmaker() as s:
        user = await s.scalar(select(User).where(User.email == account["email"]))
        user.two_factor_enabled = True
        s.add(AuthTwoFactor(user_id=user.id, secret="encrypted", backup_codes="encrypted", verified=True))
        await s.commit()
        user_id = str(user.id)
    # The password alone, on a session older than 15 minutes, does not delete a two-step account.
    old = await sign_in(app, account["email"], created_at=datetime.now(UTC) - timedelta(hours=1))
    refused = await client.request("DELETE", "/v1/me", json={"password": PASSWORD}, headers=old["headers"])
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "reauth_required"

    # Turned on moments ago (users.updated_at is fresh): told. A forged "off" is not.
    outbox = app.state.email_sender.outbox
    on = {"kind": "two_factor_on", "userId": user_id}
    assert (await client.post("/internal/auth/events", json=on, headers=INTERNAL)).status_code == 202
    assert len(outbox) == 1 and "turned on" in outbox[0]["subject"]
    await client.post("/internal/auth/events", json={"kind": "two_factor_off", "userId": user_id}, headers=INTERNAL)
    assert len(outbox) == 1

    # A fresh sign-in (both steps) with the password does.
    deleted = await client.request("DELETE", "/v1/me", json={"password": PASSWORD}, headers=account["headers"])
    assert deleted.status_code == 204


async def test_retention_purges_auth_leftovers_and_never_a_verified_user(client, app):
    keep = await register(client, app)
    now = datetime.now(UTC)
    async with app.state.db.sessionmaker() as s:
        s.add(User(email="never-verified@example.com", created_at=now - timedelta(days=8)))
        s.add(User(email="recent-unverified@example.com"))
        s.add(AuthVerification(identifier="sign-in-otp-a@example.com", value="x:0", expires_at=now - timedelta(days=2)))
        s.add(
            AuthVerification(identifier="sign-in-otp-b@example.com", value="x:0", expires_at=now + timedelta(minutes=5))
        )
        s.add(AuthAttempt(scope=SIGNIN_SCOPE, key_hash="k", created_at=now - timedelta(days=2)))
        await s.commit()
        purged = await purge_expired(s, now)
        await s.commit()
        emails = set(await s.scalars(select(User.email)))
    assert purged["unverified_users"] == 1 and purged["auth_verifications"] == 1 and purged["auth_attempts"] == 1
    assert emails == {keep["email"], "recent-unverified@example.com"}
