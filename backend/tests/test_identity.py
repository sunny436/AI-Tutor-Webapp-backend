"""Identity: the versioned profile, the profile photo, signed-in devices and email change."""

import asyncio
import io
import uuid

from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.auth.security import hash_token
from tests.conftest import PASSWORD, image_bytes, last_code, register, sign_in

RED, BLUE = (220, 30, 30), (30, 30, 220)


def _outbox(app, to: str) -> list[dict]:
    return [mail for mail in app.state.email_sender.outbox if mail["to"].lower() == to.lower()]


def _new_address() -> str:
    return f"new-{uuid.uuid4().hex[:10]}@example.com"


async def _sql(database: str, statement: str, **params) -> None:
    engine = create_async_engine(database)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(statement), params)
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------- profile
async def test_the_profile_starts_empty_at_version_zero(client, app):
    me = (await client.get("/v1/me", headers=(await register(client, app))["headers"])).json()
    assert me["profileVersion"] == 0
    assert me["timezone"] is None and me["avatar"] is None and me["passwordChangedAt"] is None


async def test_a_versioned_edit_sets_resets_and_refuses_a_stale_version(client, app):
    headers = (await register(client, app))["headers"]
    first = await client.patch(
        "/v1/me/profile",
        json={"version": 0, "set": {"displayName": "  Asha  ", "timezone": "Asia/Kolkata"}},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert (first.json()["displayName"], first.json()["timezone"], first.json()["profileVersion"]) == (
        "Asha",
        "Asia/Kolkata",
        1,
    )

    stale = await client.patch("/v1/me/profile", json={"version": 0, "set": {"displayName": "Other"}}, headers=headers)
    assert stale.status_code == 409
    error = stale.json()["error"]
    assert error["code"] == "version_conflict"
    assert error["current"]["displayName"] == "Asha" and error["current"]["profileVersion"] == 1

    reset = await client.patch("/v1/me/profile", json={"version": 1, "reset": ["timezone"]}, headers=headers)
    assert reset.status_code == 200
    assert reset.json()["timezone"] is None and reset.json()["displayName"] == "Asha"
    assert reset.json()["profileVersion"] == 2


async def test_an_empty_edit_changes_nothing(client, app):
    headers = (await register(client, app))["headers"]
    response = await client.patch("/v1/me/profile", json={"version": 0}, headers=headers)
    assert response.status_code == 200
    assert response.json()["profileVersion"] == 0


async def test_malformed_profile_edits_are_refused(client, app):
    headers = (await register(client, app))["headers"]
    for body in (
        {"set": {"displayName": "A"}},  # no version
        {"version": 0, "set": {"displayName": None}},  # null is not a value
        {"version": 0, "set": {"displayName": "   "}},
        {"version": 0, "set": {"displayName": "x" * 81}},
        {"version": 0, "set": {"timezone": "Mars/Olympus"}},
        {"version": 0, "set": {"displayName": "A"}, "reset": ["displayName"]},
        {"version": 0, "reset": ["timezone", "timezone"]},
        {"version": 0, "reset": ["email"]},
        {"version": 0, "set": {"email": "a@example.com"}},
        {"version": 0, "set": {"displayName": "A"}, "userId": str(uuid.uuid4())},
        {"version": -1},
    ):
        response = await client.patch("/v1/me/profile", json=body, headers=headers)
        assert response.status_code == 422, body
        assert response.json()["error"]["code"] == "validation_error"
    me = (await client.get("/v1/me", headers=headers)).json()
    assert me["profileVersion"] == 0 and me["displayName"] is None


async def test_two_edits_from_the_same_version_cannot_both_win(client, app):
    headers = (await register(client, app))["headers"]
    responses = await asyncio.gather(
        *(
            client.patch("/v1/me/profile", json={"version": 0, "set": {"displayName": name}}, headers=headers)
            for name in ("Tab one", "Tab two")
        )
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    me = (await client.get("/v1/me", headers=headers)).json()
    winner = next(r for r in responses if r.status_code == 200).json()
    assert me["profileVersion"] == 1 and me["displayName"] == winner["displayName"]


async def test_the_old_profile_route_moves_the_version_on(client, app):
    headers = (await register(client, app))["headers"]
    legacy = await client.patch("/v1/me", json={"displayName": "Old client"}, headers=headers)
    assert legacy.status_code == 200 and legacy.json()["profileVersion"] == 1
    stale = await client.patch("/v1/me/profile", json={"version": 0, "set": {"displayName": "New"}}, headers=headers)
    assert stale.status_code == 409


async def test_a_password_change_records_when(client, app, database):
    account = await register(client, app)
    assert (await client.get("/v1/me", headers=account["headers"])).json()["passwordChangedAt"] is None
    # Better Auth changes the credential's hash; the 0012 trigger mirrors it and records when.
    await _sql(
        database,
        "UPDATE auth_accounts SET password = 'new-hash' WHERE provider_id = 'credential' AND user_id = :id",
        id=uuid.UUID(account["user"]["id"]),
    )
    assert (await client.get("/v1/me", headers=account["headers"])).json()["passwordChangedAt"] is not None


# ------------------------------------------------------------------ profile photo
async def _upload(client, headers, data: bytes, content_type: str = "image/png"):
    return await client.put("/v1/me/avatar", content=data, headers={**headers, "Content-Type": content_type})


async def test_a_photo_is_stored_as_a_small_webp_and_served_cacheable(client, app):
    headers = (await register(client, app))["headers"]
    response = await _upload(client, headers, image_bytes("JPEG", (1200, 900)), "image/jpeg")
    assert response.status_code == 200, response.text
    url = response.json()["avatar"]["url"]
    assert url.startswith("/v1/me/avatar?v=") and len(url.rsplit("=", 1)[1]) == 32
    assert (await client.get("/v1/me", headers=headers)).json()["avatar"]["url"] == url
    assert response.json()["profileVersion"] == 0  # a photo is not a profile edit

    photo = await client.get(url, headers=headers)
    assert photo.status_code == 200
    assert photo.headers["content-type"] == "image/webp"
    assert photo.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert photo.headers["x-content-type-options"] == "nosniff"
    assert len(photo.content) <= 65_536
    with Image.open(io.BytesIO(photo.content)) as stored:
        assert (stored.format, stored.size) == ("WEBP", (256, 256))


async def test_a_photo_loses_its_metadata_and_is_turned_upright(client, app):
    headers = (await register(client, app))["headers"]
    source = Image.new("RGB", (128, 64), RED)
    source.paste(BLUE, (64, 0, 128, 64))  # red left half, blue right half
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: rotate 90 degrees clockwise to display
    exif[0x010F] = "Camera maker"
    exif.get_ifd(0x8825)[2] = (12.0, 58.0, 30.0)  # GPS latitude
    buffer = io.BytesIO()
    source.save(buffer, "JPEG", exif=exif, quality=95)

    response = await _upload(client, headers, buffer.getvalue(), "image/jpeg")
    assert response.status_code == 200, response.text
    photo = await client.get(response.json()["avatar"]["url"], headers=headers)
    with Image.open(io.BytesIO(photo.content)) as stored:
        assert not stored.getexif()
        assert "exif" not in stored.info and "xmp" not in stored.info
        pixels = stored.convert("RGB")
        top, bottom = pixels.getpixel((128, 20)), pixels.getpixel((128, 235))
    assert top[0] > 150 and top[2] < 100, top  # upright: the left edge is now the top
    assert bottom[2] > 150 and bottom[0] < 100, bottom


async def test_a_replaced_or_removed_photo_is_never_served_from_its_old_address(client, app):
    headers = (await register(client, app))["headers"]
    first = (await _upload(client, headers, image_bytes(color=RED))).json()["avatar"]["url"]
    second = (await _upload(client, headers, image_bytes(color=BLUE))).json()["avatar"]["url"]
    assert first != second

    old = await client.get(first, headers=headers)
    assert old.status_code == 404 and old.headers["cache-control"] == "no-store"
    assert old.json()["error"]["code"] == "not_found"
    assert (await client.get(second, headers=headers)).status_code == 200

    removed = await client.delete("/v1/me/avatar", headers=headers)
    assert removed.status_code == 200 and removed.json()["avatar"] is None
    gone = await client.get(second, headers=headers)
    assert gone.status_code == 404 and gone.headers["cache-control"] == "no-store"
    assert (await client.delete("/v1/me/avatar", headers=headers)).status_code == 200  # idempotent


async def test_unacceptable_photos_are_refused(client, app):
    headers = (await register(client, app))["headers"]
    png = image_bytes()
    cases = [
        (png, "text/plain", 415, "unsupported_media_type"),
        (png, "image/gif", 415, "unsupported_media_type"),
        (png, "image/jpeg", 422, "type_mismatch"),  # the bytes are not what the header says
        (b"", "image/png", 422, "empty"),
        (b"\x89PNG\r\n\x1a\nnot really a png", "image/png", 422, "unreadable"),
        (image_bytes(size=(16, 16)), "image/png", 422, "too_small"),
    ]
    for data, content_type, status, reason in cases:
        response = await _upload(client, headers, data, content_type)
        assert response.status_code == status, (content_type, reason, response.text)
        if status == 422:
            assert response.json()["error"]["fields"] == [{"field": "image", "reason": reason}]
    assert (await client.get("/v1/me", headers=headers)).json()["avatar"] is None


async def test_a_decompression_bomb_is_refused_before_it_is_decoded(client, app):
    headers = (await register(client, app))["headers"]
    buffer = io.BytesIO()
    Image.new("1", (10_000, 5_000)).save(buffer, "PNG")  # 50 megapixels in a few kilobytes
    assert len(buffer.getvalue()) < 100_000
    response = await _upload(client, headers, buffer.getvalue())
    assert response.status_code == 422
    assert response.json()["error"]["fields"] == [{"field": "image", "reason": "too_many_pixels"}]


async def test_only_the_photo_route_accepts_a_large_body(client, app, settings):
    headers = (await register(client, app))["headers"]
    too_big = await _upload(client, headers, b"\0" * (settings.avatar_max_bytes + 1))
    assert too_big.status_code == 413
    assert too_big.json()["error"]["code"] == "payload_too_large"
    json_route = await client.patch(
        "/v1/me/profile",
        content=b'{"version": 0, "set": {"displayName": "' + b"a" * 70_000 + b'"}}',
        headers={**headers, "Content-Type": "application/json"},
    )
    assert json_route.status_code == 413


async def test_photo_uploads_are_rate_limited(client, app, settings):
    headers = (await register(client, app))["headers"]
    for _ in range(settings.avatar_uploads_per_user):
        assert (await _upload(client, headers, image_bytes(size=(32, 32)))).status_code == 200
    refused = await _upload(client, headers, image_bytes(size=(32, 32)))
    assert refused.status_code == 429


# ----------------------------------------------------------------------- devices
async def test_devices_are_listed_with_masked_details_only(client, app):
    account = await register(client, app)
    chrome = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
    )
    await sign_in(app, account["email"], user_agent=chrome)

    response = await client.get("/v1/auth/sessions", headers=account["headers"])
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2
    assert [item["current"] for item in items].count(True) == 1
    assert {item["device"] for item in items} >= {"Chrome on Windows"}
    for item in items:
        assert set(item) == {"id", "current", "device", "ipMasked", "createdAt", "lastSeenAt", "expiresAt"}
        assert item["ipMasked"] in (None, "127.0.0.x")
    assert chrome not in response.text


async def test_one_other_device_can_be_signed_out(client, app):
    account = await register(client, app)
    other_headers = (await sign_in(app, account["email"]))["headers"]
    items = (await client.get("/v1/auth/sessions", headers=account["headers"])).json()["items"]
    other = next(item for item in items if not item["current"])
    current = next(item for item in items if item["current"])

    assert (await client.delete(f"/v1/auth/sessions/{other['id']}", headers=account["headers"])).status_code == 204
    assert (await client.get("/v1/me", headers=other_headers)).status_code == 401
    assert (await client.get("/v1/me", headers=account["headers"])).status_code == 200

    own = await client.delete(f"/v1/auth/sessions/{current['id']}", headers=account["headers"])
    assert own.status_code == 409 and own.json()["error"]["code"] == "current_session"
    again = await client.delete(f"/v1/auth/sessions/{other['id']}", headers=account["headers"])
    assert again.status_code == 404


async def test_expired_sessions_are_not_listed(client, app, database):
    account = await register(client, app)
    await sign_in(app, account["email"])
    await _sql(
        database,
        "UPDATE auth_sessions SET expires_at = now() - interval '1 minute' WHERE user_id = :id AND token_hash <> :own",
        id=uuid.UUID(account["user"]["id"]),
        own=hash_token(account["token"]),
    )
    items = (await client.get("/v1/auth/sessions", headers=account["headers"])).json()["items"]
    assert [item["current"] for item in items] == [True]


# ------------------------------------------------------------------ email change
async def _request_change(client, headers, new_email: str, password: str = PASSWORD):
    return await client.post("/v1/me/email/change", json={"newEmail": new_email, "password": password}, headers=headers)


async def _confirm(client, headers, new_email: str, code: str):
    return await client.post("/v1/me/email/confirm", json={"newEmail": new_email, "code": code}, headers=headers)


async def test_the_email_moves_after_the_new_address_is_proven(client, app):
    account = await register(client, app)
    other_headers = (await sign_in(app, account["email"]))["headers"]
    new_email = _new_address()

    requested = await _request_change(client, account["headers"], new_email)
    assert requested.status_code == 202
    [code_mail] = _outbox(app, new_email)
    assert "email change code" in code_mail["subject"]

    confirmed = await _confirm(client, account["headers"], new_email, last_code(app, new_email))
    assert confirmed.status_code == 200, confirmed.text
    me = confirmed.json()
    assert me["email"] == new_email and me["emailVerified"] and me["profileVersion"] == 1

    assert (await client.get("/v1/me", headers=other_headers)).status_code == 401  # other devices signed out
    assert (await client.get("/v1/me", headers=account["headers"])).status_code == 200
    notice = _outbox(app, account["email"])[-1]
    assert "was changed" in notice["subject"]
    assert new_email not in notice["body"] and new_email[:2] + "***@example.com" in notice["body"]


async def test_an_email_change_needs_the_password(client, app):
    account = await register(client, app)
    new_email = _new_address()
    response = await _request_change(client, account["headers"], new_email, "not the password")
    assert response.status_code == 401 and response.json()["error"]["code"] == "invalid_credentials"
    assert not _outbox(app, new_email)


async def test_the_current_address_is_not_a_change(client, app):
    account = await register(client, app)
    response = await _request_change(client, account["headers"], account["email"].upper())
    assert response.status_code == 422
    assert response.json()["error"]["fields"] == [{"field": "newEmail", "reason": "unchanged"}]


async def test_a_taken_address_gets_a_notice_and_no_code(client, app):
    account = await register(client, app)
    owner = await register(client, app)
    sent_before = len(_outbox(app, owner["email"]))

    response = await _request_change(client, account["headers"], owner["email"])
    assert response.status_code == 202  # the same answer as for a free address
    mails = _outbox(app, owner["email"])[sent_before:]
    assert len(mails) == 1 and "tried to use your email" in mails[0]["subject"]
    assert not any(char.isdigit() for char in mails[0]["body"])  # no code in it
    refused = await _confirm(client, account["headers"], owner["email"], "123456")
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "invalid_code"


async def test_only_the_latest_change_request_can_be_confirmed(client, app):
    account = await register(client, app)
    first, second = _new_address(), _new_address()
    await _request_change(client, account["headers"], first)
    first_code = last_code(app, first)
    await _request_change(client, account["headers"], second)
    assert (await _confirm(client, account["headers"], first, first_code)).status_code == 400
    assert (await _confirm(client, account["headers"], second, last_code(app, second))).status_code == 200


async def test_a_change_code_allows_a_few_attempts_then_dies(client, app, settings):
    account = await register(client, app)
    new_email = _new_address()
    await _request_change(client, account["headers"], new_email)
    code = last_code(app, new_email)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(settings.email_code_max_attempts):
        assert (await _confirm(client, account["headers"], new_email, wrong)).status_code == 400
    assert (await _confirm(client, account["headers"], new_email, code)).status_code == 400


async def test_an_expired_change_code_is_refused(client, app, database):
    account = await register(client, app)
    new_email = _new_address()
    await _request_change(client, account["headers"], new_email)
    await _sql(
        database, "UPDATE email_codes SET expires_at = now() - interval '1 second' WHERE email = :e", e=new_email
    )
    assert (await _confirm(client, account["headers"], new_email, last_code(app, new_email))).status_code == 400


async def test_email_change_requests_are_rate_limited(client, app, settings):
    account = await register(client, app)
    for _ in range(settings.email_change_requests_per_user):
        assert (await _request_change(client, account["headers"], _new_address())).status_code == 202
    assert (await _request_change(client, account["headers"], _new_address())).status_code == 429


async def test_an_address_taken_after_the_code_was_sent_is_a_conflict(client, app):
    account = await register(client, app)
    new_email = _new_address()
    await _request_change(client, account["headers"], new_email)
    code = last_code(app, new_email)
    await register(client, app, email=new_email)  # someone else signs up with it first

    response = await _confirm(client, account["headers"], new_email, code)
    assert response.status_code == 409 and response.json()["error"]["code"] == "email_unavailable"
    assert (await client.get("/v1/me", headers=account["headers"])).json()["email"] == account["email"]


async def test_codes_for_either_address_die_with_the_change(client, app, database):
    """A reset or sign-in code Better Auth sent to the old address must not reach the account
    again, and nobody's pending code for the new address survives the move."""
    account = await register(client, app)
    new_email = _new_address()
    for identifier in (f"forget-password-otp-{account['email']}", f"sign-in-otp-{new_email}"):
        await _sql(
            database,
            "INSERT INTO auth_verifications (identifier, value, expires_at) "
            "VALUES (:i, 'hash:0', now() + interval '15 minutes')",
            i=identifier,
        )
    await _request_change(client, account["headers"], new_email)
    assert (await _confirm(client, account["headers"], new_email, last_code(app, new_email))).status_code == 200
    engine = create_async_engine(database)
    try:
        async with engine.connect() as conn:
            left = (await conn.execute(text("SELECT count(*) FROM auth_verifications"))).scalar_one()
    finally:
        await engine.dispose()
    assert left == 0
