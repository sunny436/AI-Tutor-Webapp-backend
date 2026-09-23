from tests.conftest import register, stream_chat


async def test_create_get_rename_delete(client, app):
    account = await register(client, app)
    h = account["headers"]
    r = await client.post("/v1/conversations", json={}, headers=h)
    assert r.status_code == 201 and r.json()["title"] == "New chat"
    cid = r.json()["id"]
    assert (await client.get(f"/v1/conversations/{cid}", headers=h)).json()["id"] == cid
    r = await client.patch(f"/v1/conversations/{cid}", json={"title": "  Trip   plans "}, headers=h)
    assert r.status_code == 200 and r.json()["title"] == "Trip plans"
    assert (await client.patch(f"/v1/conversations/{cid}", json={"title": "   "}, headers=h)).status_code == 422
    assert (await client.patch(f"/v1/conversations/{cid}", json={"title": "x" * 121}, headers=h)).status_code == 422
    assert (await client.delete(f"/v1/conversations/{cid}", headers=h)).status_code == 204
    assert (await client.get(f"/v1/conversations/{cid}", headers=h)).status_code == 404
    assert (await client.delete(f"/v1/conversations/{cid}", headers=h)).status_code == 404


async def test_list_is_ordered_by_activity_and_paginates(client, app):
    account = await register(client, app)
    h = account["headers"]
    ids = [(await client.post("/v1/conversations", json={"title": f"c{i}"}, headers=h)).json()["id"] for i in range(5)]
    # activity on the oldest moves it to the top
    await stream_chat(client, h, "bump", conversation_id=ids[0])
    page1 = (await client.get("/v1/conversations?limit=2", headers=h)).json()
    assert [c["id"] for c in page1["items"]] == [ids[0], ids[4]]
    page2 = (await client.get(f"/v1/conversations?limit=2&cursor={page1['nextCursor']}", headers=h)).json()
    assert [c["id"] for c in page2["items"]] == [ids[3], ids[2]]
    page3 = (await client.get(f"/v1/conversations?limit=2&cursor={page2['nextCursor']}", headers=h)).json()
    assert [c["id"] for c in page3["items"]] == [ids[1]] and page3["nextCursor"] is None
    assert (await client.get("/v1/conversations?cursor=garbage", headers=h)).status_code == 422


async def test_messages_pagination_oldest_first(client, app):
    account = await register(client, app)
    h = account["headers"]
    _, events = await stream_chat(client, h, "one")
    cid = events[0][1]["conversationId"]
    for text in ("two", "three"):
        await stream_chat(client, h, text, conversation_id=cid)
    full = (await client.get(f"/v1/conversations/{cid}/messages", headers=h)).json()
    assert [m["role"] for m in full["items"]] == ["user", "assistant"] * 3
    assert [m["content"] for m in full["items"] if m["role"] == "user"] == ["one", "two", "three"]
    latest = (await client.get(f"/v1/conversations/{cid}/messages?limit=2", headers=h)).json()
    assert [m["content"] for m in latest["items"]] == ["three", "You said: three"]
    older = (
        await client.get(f"/v1/conversations/{cid}/messages?limit=2&before={latest['nextCursor']}", headers=h)
    ).json()
    assert [m["content"] for m in older["items"]] == ["two", "You said: two"]
    # internal diagnostics are not exposed
    assert set(full["items"][1]["metadata"]) <= {"model", "errorCode", "finishReason"}
