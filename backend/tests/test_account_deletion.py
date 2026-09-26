"""Deleting an account removes everything that belongs to it — proven, not assumed.

The tables are discovered from the database itself (every foreign key that points at
users.id), so a table added later is covered without anyone remembering to extend this
test. Rows keyed by the email address rather than the user id are checked by address.
"""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import PASSWORD, image_bytes, ingest_docs, last_code, register, stream_chat

USER_REFERENCES = text(
    """
    SELECT kcu.table_name, kcu.column_name
    FROM information_schema.referential_constraints rc
    JOIN information_schema.key_column_usage kcu
      ON kcu.constraint_name = rc.constraint_name AND kcu.constraint_schema = rc.constraint_schema
    JOIN information_schema.key_column_usage ref
      ON ref.constraint_name = rc.unique_constraint_name AND ref.constraint_schema = rc.unique_constraint_schema
    WHERE ref.table_name = 'users' AND ref.column_name = 'id' AND kcu.table_schema = 'public'
    ORDER BY 1, 2
    """
)


async def _rows_referencing(database: str, user_id: str, email: str) -> dict[str, int]:
    engine = create_async_engine(database)
    try:
        async with engine.connect() as conn:
            references = (await conn.execute(USER_REFERENCES)).all()
            counts = {}
            for table, column in references:
                counts[f"{table}.{column}"] = await conn.scalar(
                    text(f'SELECT count(*) FROM "{table}" WHERE "{column}" = :id'), {"id": uuid.UUID(user_id)}
                )
            counts["users"] = await conn.scalar(text("SELECT count(*) FROM users WHERE id = :id"), {"id": user_id})
            counts["email_codes (by address)"] = await conn.scalar(
                text("SELECT count(*) FROM email_codes WHERE email = :email"), {"email": email}
            )
            counts["email_outbox (by address)"] = await conn.scalar(
                text("SELECT count(*) FROM email_outbox WHERE to_address = :email"), {"email": email}
            )
            return counts
    finally:
        await engine.dispose()


async def test_deleting_an_account_leaves_no_row_that_belongs_to_it(client, app, database):
    account = await register(client, app)
    headers = account["headers"]
    user_id = account["user"]["id"]

    # Something in every place a user can own data today.
    _, events = await stream_chat(client, headers, "Something to remember")  # conversation, messages, usage
    message_id = events[-1][1]["message"]["id"]
    feedback = await client.put(f"/v1/messages/{message_id}/feedback", json={"rating": "up"}, headers=headers)
    assert feedback.status_code == 200
    assert (await client.patch("/v1/me/settings", json={"preferences": {"k": "v"}}, headers=headers)).status_code == 200
    login = await client.post("/v1/auth/login", json={"email": account["email"], "password": PASSWORD})
    other_headers = {"Authorization": f"Bearer {login.json()['session']['token']}"}  # a second session
    await ingest_docs(
        app,
        {"private.md": "# Private notes\n\nMine only."},
        source=f"private-{uuid.uuid4().hex[:8]}",
        owner_user_id=uuid.UUID(user_id),
    )
    await client.post("/v1/auth/password/forgot", json={"email": account["email"]})  # a pending code by address
    photo = await client.put("/v1/me/avatar", content=image_bytes(), headers={**headers, "Content-Type": "image/png"})
    assert photo.status_code == 200, photo.text
    change = await client.post(  # a pending change-email code, bound to the user
        "/v1/me/email/change",
        json={"newEmail": f"moved-{uuid.uuid4().hex[:8]}@example.com", "password": PASSWORD},
        headers=headers,
    )
    assert change.status_code == 202, change.text
    learning = [  # learner profile, subjects, preferences
        ("PATCH", "/v1/learning/profile", {"version": 0, "set": {"grade": "class_10", "targetExam": "Boards"}}),
        ("PUT", "/v1/learning/subjects", {"version": 0, "items": [{"code": "mathematics", "isPriority": True}]}),
        ("PATCH", "/v1/learning/preferences", {"version": 0, "set": {"pace": "slow"}}),
    ]
    for method, url, body in learning:
        response = await client.request(method, url, json=body, headers=headers)
        assert response.status_code == 200, (url, response.text)
    preferences = await client.patch(
        "/v1/notifications/preferences", json={"version": 0, "set": {"weeklySummary": True}}, headers=headers
    )
    assert preferences.status_code == 200, preferences.text
    appearance = await client.patch("/v1/me/appearance", json={"version": 0, "set": {"theme": "dark"}}, headers=headers)
    assert appearance.status_code == 200, appearance.text
    support = await client.post(
        "/v1/support/requests",
        json={"requestId": str(uuid.uuid4()), "kind": "question", "subject": "Help", "message": "How does this work?"},
        headers=headers,
    )
    assert support.status_code == 201, support.text
    phone = await client.post(  # a sign-in from a new kind of device queues an alert email
        "/v1/auth/login",
        json={"email": account["email"], "password": PASSWORD},
        headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Version/18.0 Safari/604.1"},
    )
    assert phone.status_code == 200
    assert last_code(app, account["email"])

    before = await _rows_referencing(database, user_id, account["email"])
    missing = [name for name, count in before.items() if name != "users" and count == 0]
    assert not missing, f"the test created no data in {missing}; extend it so deletion is really exercised"

    deleted = await client.request("DELETE", "/v1/me", json={"password": PASSWORD}, headers=headers)
    assert deleted.status_code == 204, deleted.text

    after = await _rows_referencing(database, user_id, account["email"])
    assert {name: count for name, count in after.items() if count} == {}, after

    # Every session of the account is gone: neither token opens anything any more.
    for token_headers in (headers, other_headers):
        for url in ("/v1/me", "/v1/conversations", "/v1/me/settings"):
            assert (await client.get(url, headers=token_headers)).status_code == 401, url


async def test_a_reset_code_of_a_deleted_account_cannot_reset_a_new_account_with_the_same_address(client, app):
    account = await register(client, app)
    await client.post("/v1/auth/password/forgot", json={"email": account["email"]})
    old_code = last_code(app, account["email"])
    deleted = await client.request("DELETE", "/v1/me", json={"password": PASSWORD}, headers=account["headers"])
    assert deleted.status_code == 204

    await register(client, app, email=account["email"])  # someone else registers the address
    reset = await client.post(
        "/v1/auth/password/reset",
        json={"email": account["email"], "code": old_code, "newPassword": "someone-elses-password"},
    )
    assert reset.status_code == 400, reset.text
    assert reset.json()["error"]["code"] == "invalid_code"
