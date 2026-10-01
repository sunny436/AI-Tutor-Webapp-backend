from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update

from app.db.models import AuthSession, Conversation, Message, User, UserSettings
from tests.conftest import PASSWORD, register, sign_in, stream_chat


async def test_missing_malformed_and_unknown_tokens_are_401(client, app):
    for headers in ({}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer "}, {"Authorization": "Bearer nope"}):
        r = await client.get("/v1/me", headers=headers)
        assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"


async def test_expired_session_is_401(client, app):
    account = await register(client, app)
    async with app.state.db.sessionmaker() as s:
        await s.execute(update(AuthSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        await s.commit()
    assert (await client.get("/v1/me", headers=account["headers"])).status_code == 401


async def test_revoke_other_sessions(client, app):
    account = await register(client, app)
    other_headers = (await sign_in(app, account["email"]))["headers"]
    assert (await client.post("/v1/auth/sessions/revoke-others", headers=account["headers"])).status_code == 204
    assert (await client.get("/v1/me", headers=other_headers)).status_code == 401
    assert (await client.get("/v1/me", headers=account["headers"])).status_code == 200


async def test_update_profile(client, app):
    account = await register(client, app)
    r = await client.patch("/v1/me", json={"displayName": "  Sam  "}, headers=account["headers"])
    assert r.status_code == 200 and r.json()["displayName"] == "Sam"
    r = await client.patch("/v1/me", json={"displayName": "x" * 81}, headers=account["headers"])
    assert r.status_code == 422


async def test_settings_merge_remove_and_size_limit(client, app):
    account = await register(client, app)
    r = await client.get("/v1/me/settings", headers=account["headers"])
    assert r.status_code == 200 and r.json()["preferences"] == {}
    r = await client.patch(
        "/v1/me/settings", json={"preferences": {"theme": "dark", "lang": "en"}}, headers=account["headers"]
    )
    assert r.json()["preferences"] == {"theme": "dark", "lang": "en"}
    r = await client.patch("/v1/me/settings", json={"preferences": {"lang": None}}, headers=account["headers"])
    assert r.json()["preferences"] == {"theme": "dark"}
    r = await client.patch("/v1/me/settings", json={"preferences": {"blob": "x" * 5000}}, headers=account["headers"])
    assert r.status_code == 422
    async with app.state.db.sessionmaker() as s:
        row = await s.scalar(select(UserSettings))
    assert row.preferences == {"theme": "dark"}


async def test_delete_account_requires_password_and_cascades(client, app):
    account = await register(client, app)
    await stream_chat(client, account["headers"], "hello")
    await client.patch("/v1/me/settings", json={"preferences": {"theme": "dark"}}, headers=account["headers"])
    bad = await client.request("DELETE", "/v1/me", json={"password": "wrong"}, headers=account["headers"])
    assert bad.status_code == 401
    ok = await client.request("DELETE", "/v1/me", json={"password": PASSWORD}, headers=account["headers"])
    assert ok.status_code == 204
    async with app.state.db.sessionmaker() as s:
        for model in (User, AuthSession, Conversation, Message, UserSettings):
            assert await s.scalar(select(func.count()).select_from(model)) == 0
    assert (await client.get("/v1/me", headers=account["headers"])).status_code == 401
