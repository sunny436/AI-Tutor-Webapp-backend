from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.models import AuthAttempt, AuthSession, EmailCode, User
from tests.conftest import PASSWORD, last_code, register


async def _db(app):
    return create_async_engine(app.state.settings.database_url)


async def test_signup_verify_creates_session_and_user(client, app):
    account = await register(client, app, email="Alice@Example.com")
    assert account["user"]["email"].lower() == "alice@example.com"
    assert account["user"]["emailVerified"] is True
    me = await client.get("/v1/me", headers=account["headers"])
    assert me.status_code == 200 and me.json()["id"] == account["user"]["id"]
    # the password is stored as argon2id, never in clear
    async with app.state.db.sessionmaker() as s:
        user = await s.scalar(select(User))
        assert user.password_hash.startswith("$argon2id$") and PASSWORD not in user.password_hash


async def test_signup_always_202_and_does_not_reveal_existing_account(client, app):
    await register(client, app, email="bob@example.com")
    again = await client.post("/v1/auth/signup", json={"email": "bob@example.com", "password": "another-password"})
    assert again.status_code == 202
    assert "Sign-up attempt" in app.state.email_sender.outbox[-1]["subject"]
    # the existing password still works; the attempt changed nothing
    login = await client.post("/v1/auth/login", json={"email": "bob@example.com", "password": PASSWORD})
    assert login.status_code == 200


async def test_wrong_code_is_rejected_and_attempts_are_limited(client, app):
    await client.post("/v1/auth/signup", json={"email": "carol@example.com", "password": PASSWORD})
    code = last_code(app, "carol@example.com")
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        r = await client.post("/v1/auth/verify-email", json={"email": "carol@example.com", "code": wrong})
        assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_code"
    # after max attempts even the right code no longer works
    r = await client.post("/v1/auth/verify-email", json={"email": "carol@example.com", "code": code})
    assert r.status_code == 400


async def test_expired_code_is_rejected(client, app):
    await client.post("/v1/auth/signup", json={"email": "dan@example.com", "password": PASSWORD})
    code = last_code(app, "dan@example.com")
    async with app.state.db.sessionmaker() as s:
        await s.execute(update(EmailCode).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        await s.commit()
    r = await client.post("/v1/auth/verify-email", json={"email": "dan@example.com", "code": code})
    assert r.status_code == 400


async def test_login_unverified_and_wrong_password(client, app):
    await client.post("/v1/auth/signup", json={"email": "erin@example.com", "password": PASSWORD})
    r = await client.post("/v1/auth/login", json={"email": "erin@example.com", "password": PASSWORD})
    assert r.status_code == 403 and r.json()["error"]["code"] == "email_not_verified"
    r = await client.post("/v1/auth/login", json={"email": "erin@example.com", "password": "wrong-password"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"
    r = await client.post("/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong-password"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"


async def test_login_logout(client, app):
    account = await register(client, app)
    login = await client.post("/v1/auth/login", json={"email": account["email"], "password": PASSWORD})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['session']['token']}"}
    assert (await client.post("/v1/auth/logout", headers=headers)).status_code == 204
    assert (await client.get("/v1/me", headers=headers)).status_code == 401
    # the other session is unaffected
    assert (await client.get("/v1/me", headers=account["headers"])).status_code == 200


async def test_failed_logins_are_throttled_in_postgres(client, app, settings):
    account = await register(client, app)
    for _ in range(settings.login_failures_per_email):
        await client.post("/v1/auth/login", json={"email": account["email"], "password": "wrong-password"})
    blocked = await client.post("/v1/auth/login", json={"email": account["email"], "password": PASSWORD})
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "rate_limited"
    async with app.state.db.sessionmaker() as s:
        rows = list(await s.scalars(select(AuthAttempt).where(AuthAttempt.scope == "login_fail")))
        assert len(rows) == settings.login_failures_per_email
        assert all(account["email"] not in r.key_hash for r in rows)  # hashed, not raw


async def test_forgot_and_reset_password_revokes_all_sessions(client, app):
    account = await register(client, app)
    r = await client.post("/v1/auth/password/forgot", json={"email": account["email"]})
    assert r.status_code == 202
    r = await client.post("/v1/auth/password/forgot", json={"email": "unknown@example.com"})
    assert r.status_code == 202  # no enumeration
    code = last_code(app, account["email"])
    r = await client.post(
        "/v1/auth/password/reset",
        json={"email": account["email"], "code": code, "newPassword": "a brand new password"},
    )
    assert r.status_code == 200
    assert (await client.get("/v1/me", headers=account["headers"])).status_code == 401
    new = {"Authorization": f"Bearer {r.json()['session']['token']}"}
    assert (await client.get("/v1/me", headers=new)).status_code == 200
    ok = await client.post("/v1/auth/login", json={"email": account["email"], "password": "a brand new password"})
    assert ok.status_code == 200


async def test_change_password_keeps_current_session_only(client, app):
    account = await register(client, app)
    other = await client.post("/v1/auth/login", json={"email": account["email"], "password": PASSWORD})
    other_headers = {"Authorization": f"Bearer {other.json()['session']['token']}"}
    bad = await client.post(
        "/v1/auth/password/change",
        json={"currentPassword": "wrong", "newPassword": "another long password"},
        headers=account["headers"],
    )
    assert bad.status_code == 401
    ok = await client.post(
        "/v1/auth/password/change",
        json={"currentPassword": PASSWORD, "newPassword": "another long password"},
        headers=account["headers"],
    )
    assert ok.status_code == 204
    assert (await client.get("/v1/me", headers=account["headers"])).status_code == 200
    assert (await client.get("/v1/me", headers=other_headers)).status_code == 401


async def test_resend_code_for_unverified_account(client, app):
    await client.post("/v1/auth/signup", json={"email": "fay@example.com", "password": PASSWORD})
    first = last_code(app, "fay@example.com")
    r = await client.post("/v1/auth/resend-code", json={"email": "fay@example.com"})
    assert r.status_code == 202
    second = last_code(app, "fay@example.com")
    # the old code is invalidated; the new one works
    if first != second:
        bad = await client.post("/v1/auth/verify-email", json={"email": "fay@example.com", "code": first})
        assert bad.status_code == 400
    good = await client.post("/v1/auth/verify-email", json={"email": "fay@example.com", "code": second})
    assert good.status_code == 200


async def test_session_token_is_stored_hashed(client, app):
    account = await register(client, app)
    async with app.state.db.sessionmaker() as s:
        rows = list(await s.scalars(select(AuthSession)))
    assert rows and all(account["token"] != r.token_hash for r in rows)
