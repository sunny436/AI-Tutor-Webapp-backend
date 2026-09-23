"""User isolation: another user's resources behave exactly like missing ones (404)."""

from tests.conftest import register, stream_chat


async def test_other_users_resources_are_404(client, app):
    alice = await register(client, app)
    bob = await register(client, app)
    _, events = await stream_chat(client, alice["headers"], "private question")
    cid = events[0][1]["conversationId"]
    mid = events[-1][1]["message"]["id"]
    b = bob["headers"]

    checks = [
        ("GET", f"/v1/conversations/{cid}", None),
        ("PATCH", f"/v1/conversations/{cid}", {"title": "stolen"}),
        ("DELETE", f"/v1/conversations/{cid}", None),
        ("GET", f"/v1/conversations/{cid}/messages", None),
        ("POST", f"/v1/conversations/{cid}/regenerate/stream", None),
        ("POST", "/v1/chat/stream", {"conversationId": cid, "message": "hi"}),
        ("POST", "/v1/chat", {"conversationId": cid, "message": "hi"}),
        ("POST", f"/v1/messages/{mid}/cancel", None),
        ("PUT", f"/v1/messages/{mid}/feedback", {"rating": "down"}),
        ("GET", f"/v1/messages/{mid}/feedback", None),
        ("DELETE", f"/v1/messages/{mid}/feedback", None),
    ]
    for method, url, body in checks:
        r = await client.request(method, url, json=body, headers=b)
        assert r.status_code == 404, (method, url, r.status_code, r.text)
        assert r.json()["error"]["code"] == "not_found"

    # Bob's list does not include it, and Alice's data is untouched.
    assert (await client.get("/v1/conversations", headers=b)).json()["items"] == []
    mine = await client.get(f"/v1/conversations/{cid}/messages", headers=alice["headers"])
    assert mine.status_code == 200 and len(mine.json()["items"]) == 2


async def test_client_supplied_identity_fields_are_rejected(client, app):
    account = await register(client, app)
    r = await client.post(
        "/v1/chat/stream", json={"message": "hi", "userId": "someone-else"}, headers=account["headers"]
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


async def test_every_data_endpoint_requires_auth(client, app):
    for method, url in [
        ("GET", "/v1/conversations"),
        ("POST", "/v1/conversations"),
        ("POST", "/v1/chat/stream"),
        ("POST", "/v1/chat"),
        ("GET", "/v1/me"),
        ("GET", "/v1/me/settings"),
        ("POST", "/v1/auth/logout"),
    ]:
        for body in ({"message": "x"}, {}):
            r = await client.request(method, url, json=body if method == "POST" else None)
            assert r.status_code == 401, (method, url, body, r.status_code)
