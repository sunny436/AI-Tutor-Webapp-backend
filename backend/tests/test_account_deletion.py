"""Deleting an account removes everything that belongs to it — proven, not assumed.

The tables are discovered from the database itself (every foreign key that points at
users.id), so a table added later is covered without anyone remembering to extend this
test. Rows keyed by the email address rather than the user id are checked by address.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.notifications.outbox import WEEKLY_SUMMARY, queue_email
from tests.conftest import PASSWORD, image_bytes, ingest_docs, register, sign_in, stream_chat

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
            counts["auth_verifications (by address)"] = await conn.scalar(
                text("SELECT count(*) FROM auth_verifications WHERE identifier LIKE '%-otp-' || :email"),
                {"email": email.lower()},
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
    other_headers = (await sign_in(app, account["email"]))["headers"]  # a second session
    await ingest_docs(
        app,
        {"private.md": "# Private notes\n\nMine only."},
        source=f"private-{uuid.uuid4().hex[:8]}",
        owner_user_id=uuid.UUID(user_id),
    )
    async with app.state.db.sessionmaker() as db:  # a pending Better Auth code, by address
        await db.execute(
            text(
                "INSERT INTO auth_verifications (identifier, value, expires_at) "
                "VALUES (:i, 'hash:0', now() + interval '15 minutes')"
            ),
            {"i": f"forget-password-otp-{account['email']}"},
        )
        await db.execute(  # an authenticator secret and recovery codes (two-step sign-in, set up)
            text("INSERT INTO auth_two_factors (user_id, secret, backup_codes) VALUES (:u, 'enc', 'enc')"),
            {"u": uuid.UUID(user_id)},
        )
        await db.execute(  # a practice set from the question bank (its served questions go with it)
            text(
                "INSERT INTO qb_sets (user_id, request_id, mode, filters, requested) "
                "VALUES (:u, gen_random_uuid(), 'test', '{}', 1)"
            ),
            {"u": uuid.UUID(user_id)},
        )
        await queue_email(  # an email waiting in the outbox for this student
            db,
            kind=WEEKLY_SUMMARY,
            to=account["email"],
            subject="Your week",
            body="...",
            send_before=datetime.now(UTC) + timedelta(days=1),
            user_id=uuid.UUID(user_id),
        )
        await db.commit()
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
    notice = await client.post(  # a security notice in the bell (Better Auth reports a password change)
        "/internal/auth/events",
        json={"kind": "password_changed", "userId": user_id},
        headers={"X-Internal-Token": app.state.settings.auth_internal_token.get_secret_value()},
    )
    assert notice.status_code == 202
    uploaded = await client.post(  # a library file, read into chunks and attached to a message
        "/v1/files",
        params={"filename": "notes.txt"},
        content=b"Notes about the water cycle: evaporation, condensation and precipitation.",
        headers={**headers, "Content-Type": "application/octet-stream"},
    )
    assert uploaded.status_code == 201, uploaded.text
    assert await app.state.file_worker.run_once()
    attached = await client.post(
        "/v1/chat/stream", json={"message": "Explain this", "attachmentIds": [uploaded.json()["id"]]}, headers=headers
    )
    assert attached.status_code == 200, attached.text
    tab = str(uuid.uuid4())  # a study session, and a beat (app time too)
    studying = await client.post("/v1/study/session", json={"clientId": tab}, headers=headers)
    assert studying.status_code == 200, studying.text
    beat = {"beatId": str(uuid.uuid4()), "clientId": tab, "wasActive": False, "nowActive": True}
    beat = await client.post("/v1/study/beat", json={**beat, "studyView": True, "visible": True}, headers=headers)
    assert beat.status_code == 200, beat.text

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


async def test_a_code_of_a_deleted_account_dies_with_it(client, app, database):
    """Better Auth's codes are keyed by address: one left behind would still work on a new account
    registered with the same address."""
    account = await register(client, app)
    engine = create_async_engine(database)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO auth_verifications (identifier, value, expires_at) "
                    "VALUES (:i, 'hash:0', now() + interval '15 minutes')"
                ),
                {"i": f"forget-password-otp-{account['email']}"},
            )
        deleted = await client.request("DELETE", "/v1/me", json={"password": PASSWORD}, headers=account["headers"])
        assert deleted.status_code == 204
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT count(*) FROM auth_verifications"))).scalar_one() == 0
    finally:
        await engine.dispose()
