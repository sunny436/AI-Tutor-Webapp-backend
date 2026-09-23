import asyncio

import pytest
from sqlalchemy import func, select

from app.db.models import Message, MessageFeedback, UsageEvent
from app.llm.base import LLMTimeout, LLMUnavailable
from app.llm.fake import FakeProvider
from tests.conftest import make_settings, parse_sse, register, stream_chat

RICH = (
    "# Title\n\nSome **bold**, *italic* and `code`.\n\n```python\nprint('hi')\n```\n\n"
    "| a | b |\n|---|---|\n| 1 | 2 |\n\n> quote\n\nInline $e^{i\\pi}+1=0$ and block:\n\n$$\\int_0^1 x\\,dx$$\n"
)


async def test_stream_event_order_and_persistence(client, app):
    account = await register(client, app)
    response, events = await stream_chat(client, account["headers"], "Hello there")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    kinds = [kind for kind, _ in events]
    assert kinds[0] == "meta" and kinds[-1] == "done" and kinds.count("token") >= 2
    meta, done = events[0][1], events[-1][1]
    assert meta["userMessage"]["content"] == "Hello there"
    assert meta["conversation"]["title"] == "Hello there"
    streamed = "".join(data["text"] for kind, data in events if kind == "token")
    assert streamed == "You said: Hello there" == done["message"]["content"]
    assert done["message"]["id"] == meta["assistantMessageId"] and done["message"]["status"] == "complete"

    stored = (
        await client.get(f"/v1/conversations/{meta['conversationId']}/messages", headers=account["headers"])
    ).json()
    assert [(m["role"], m["content"], m["status"]) for m in stored["items"]] == [
        ("user", "Hello there", "complete"),
        ("assistant", "You said: Hello there", "complete"),
    ]
    async with app.state.db.sessionmaker() as s:
        usage = await s.scalar(select(UsageEvent))
    assert usage.outcome == "complete" and usage.provider == "fake" and usage.latency_ms is not None


async def test_history_is_loaded_server_side(client, app, fake_llm):
    account = await register(client, app)
    _, events = await stream_chat(client, account["headers"], "first")
    cid = events[0][1]["conversationId"]
    await stream_chat(client, account["headers"], "second", conversation_id=cid)
    prompt = fake_llm.calls[-1]
    assert prompt[0].role == "system" and "general-purpose AI assistant" in prompt[0].content
    assert [(m.role, m.content) for m in prompt[1:]] == [
        ("user", "first"),
        ("assistant", "You said: first"),
        ("user", "second"),
    ]


async def test_markdown_code_tables_and_math_are_stored_byte_for_byte(client, app, fake_llm):
    fake_llm.reply = lambda messages: RICH
    account = await register(client, app)
    _, events = await stream_chat(client, account["headers"], RICH)
    cid = events[0][1]["conversationId"]
    assert events[-1][1]["message"]["content"] == RICH
    stored = (await client.get(f"/v1/conversations/{cid}/messages", headers=account["headers"])).json()["items"]
    assert stored[0]["content"] == RICH and stored[1]["content"] == RICH


async def test_new_chat_is_titled_from_first_message(client, app):
    account = await register(client, app)
    created = (await client.post("/v1/conversations", json={}, headers=account["headers"])).json()
    long = "Explain how photosynthesis works in plants and why it matters for life on Earth today"
    _, events = await stream_chat(client, account["headers"], long, conversation_id=created["id"])
    title = events[0][1]["conversation"]["title"]
    assert title.startswith("Explain how photosynthesis") and len(title) <= 60 and title.endswith("…")


async def test_non_streaming_chat(client, app):
    account = await register(client, app)
    r = await client.post("/v1/chat", json={"message": "ping"}, headers=account["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["message"]["content"] == "You said: ping" and body["userMessage"]["content"] == "ping"


async def test_validation_of_chat_requests(client, app):
    account = await register(client, app)
    for body in ({"message": ""}, {"message": "   "}, {"message": "x" * 16001}, {}):
        r = await client.post("/v1/chat/stream", json=body, headers=account["headers"])
        assert r.status_code == 422, body
        assert "x" * 50 not in r.text  # submitted values are not echoed back
    r = await client.post(
        "/v1/chat/stream",
        json={"message": "hi", "conversationId": "00000000-0000-0000-0000-000000000000"},
        headers=account["headers"],
    )
    assert r.status_code == 404


async def test_llm_failure_before_first_token_is_a_safe_error_event(client, app, fake_llm):
    fake_llm.fail_before_first = LLMUnavailable("upstream 503 with secret internal details")
    account = await register(client, app)
    response, events = await stream_chat(client, account["headers"], "hi")
    assert response.status_code == 200
    kind, data = events[-1]
    assert kind == "error" and data["code"] == "llm_unavailable" and data["retryable"] is True
    assert "secret internal details" not in response.text and data["requestId"]
    async with app.state.db.sessionmaker() as s:
        msg = await s.get(Message, data["messageId"])
    assert msg.status == "error" and msg.metadata_["errorCode"] == "llm_unavailable"
    # the conversation is usable again right away
    fake_llm.fail_before_first = None
    _, events = await stream_chat(client, account["headers"], "again", conversation_id=events[0][1]["conversationId"])
    assert events[-1][0] == "done"


async def test_mid_stream_failure_keeps_partial_text(client, app, fake_llm):
    fake_llm.reply = lambda m: "one two three four five"
    fake_llm.fail_after = (2, LLMTimeout("stalled"))
    account = await register(client, app)
    _, events = await stream_chat(client, account["headers"], "hi")
    assert [k for k, _ in events].count("token") == 2 and events[-1][0] == "error"
    assert events[-1][1]["code"] == "llm_timeout"
    async with app.state.db.sessionmaker() as s:
        msg = await s.get(Message, events[-1][1]["messageId"])
    assert msg.status == "error" and msg.content == "one two "


@pytest.fixture
def slow_llm():
    return FakeProvider(reply=lambda m: " ".join(f"w{i}" for i in range(60)), token_delay_s=0.05)


@pytest.fixture
async def slow_app(slow_llm):
    from app.auth.emails import MemoryEmailSender
    from app.main import create_app

    application = create_app(make_settings(), llm=slow_llm, email_sender=MemoryEmailSender())
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def slow_client(slow_app):
    import httpx

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=slow_app), base_url="http://test") as http:
        yield http


async def _wait_for_streaming(app, seconds=5.0):
    async with app.state.db.sessionmaker() as s:
        for _ in range(int(seconds / 0.05)):
            row = await s.scalar(select(Message).where(Message.status == "streaming"))
            if row is not None:
                return row
            await asyncio.sleep(0.05)
    raise AssertionError("no streaming message appeared")


async def test_cancel_stops_generation_and_keeps_partial(slow_client, slow_app):
    account = await register(slow_client, slow_app)
    task = asyncio.create_task(stream_chat(slow_client, account["headers"], "long answer please"))
    streaming = await _wait_for_streaming(slow_app)
    await asyncio.sleep(0.3)
    r = await slow_client.post(f"/v1/messages/{streaming.id}/cancel", headers=account["headers"])
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    response, events = await asyncio.wait_for(task, 10)
    done = events[-1]
    assert done[0] == "done" and done[1]["message"]["status"] == "cancelled"
    partial = done[1]["message"]["content"]
    assert partial and partial.startswith("w0") and len(partial.split()) < 60
    async with slow_app.state.db.sessionmaker() as s:
        msg = await s.get(Message, streaming.id)
    assert msg.status == "cancelled" and msg.content == partial
    # cancelling again is idempotent
    again = await slow_client.post(f"/v1/messages/{streaming.id}/cancel", headers=account["headers"])
    assert again.json()["status"] == "cancelled"


async def test_concurrent_send_in_same_conversation_is_409(slow_client, slow_app):
    account = await register(slow_client, slow_app)
    conversation = (await slow_client.post("/v1/conversations", json={}, headers=account["headers"])).json()
    task = asyncio.create_task(stream_chat(slow_client, account["headers"], "first", conversation["id"]))
    streaming = await _wait_for_streaming(slow_app)
    r = await slow_client.post(
        "/v1/chat/stream", json={"conversationId": conversation["id"], "message": "second"}, headers=account["headers"]
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"
    await slow_client.post(f"/v1/messages/{streaming.id}/cancel", headers=account["headers"])
    await asyncio.wait_for(task, 10)


async def test_stale_streaming_rows_are_swept(client, app):
    account = await register(client, app)
    _, events = await stream_chat(client, account["headers"], "hi")
    cid = events[0][1]["conversationId"]
    async with app.state.db.sessionmaker() as s:
        from sqlalchemy import text, update

        await s.execute(
            update(Message)
            .where(Message.role == "assistant")
            .values(status="streaming", created_at=text("clock_timestamp() - interval '1 hour'"))
        )
        await s.commit()
    _, events = await stream_chat(client, account["headers"], "again", conversation_id=cid)
    assert events[-1][0] == "done"
    async with app.state.db.sessionmaker() as s:
        stale = await s.scalar(select(Message).where(Message.metadata_["errorCode"].astext == "interrupted"))
    assert stale is not None and stale.status == "error"


async def test_regenerate_supersedes_previous_reply(client, app, fake_llm):
    account = await register(client, app)
    _, events = await stream_chat(client, account["headers"], "question")
    cid, first_reply = events[0][1]["conversationId"], events[-1][1]["message"]["id"]
    fake_llm.reply = lambda m: "a better answer"
    r = await client.post(f"/v1/conversations/{cid}/regenerate/stream", headers=account["headers"])
    regen = parse_sse(r.text)
    assert regen[0][1]["replacesMessageId"] == first_reply and regen[0][1]["userMessage"] is None
    assert regen[-1][1]["message"]["content"] == "a better answer"
    visible = (await client.get(f"/v1/conversations/{cid}/messages", headers=account["headers"])).json()["items"]
    assert [m["content"] for m in visible] == ["question", "a better answer"]
    async with app.state.db.sessionmaker() as s:
        old = await s.get(Message, first_reply)
    assert old.status == "superseded"
    # the model saw the question once, not the superseded reply
    assert [m.content for m in fake_llm.calls[-1][1:]] == ["question"]


async def test_regenerate_without_reply_is_409(client, app):
    account = await register(client, app)
    cid = (await client.post("/v1/conversations", json={}, headers=account["headers"])).json()["id"]
    r = await client.post(f"/v1/conversations/{cid}/regenerate/stream", headers=account["headers"])
    assert r.status_code == 409


async def test_feedback_upsert_read_delete(client, app):
    account = await register(client, app)
    _, events = await stream_chat(client, account["headers"], "hi")
    mid = events[-1][1]["message"]["id"]
    user_mid = events[0][1]["userMessage"]["id"]
    h = account["headers"]
    assert (await client.put(f"/v1/messages/{mid}/feedback", json={"rating": "up"}, headers=h)).status_code == 200
    r = await client.put(f"/v1/messages/{mid}/feedback", json={"rating": "down", "comment": "wrong"}, headers=h)
    assert r.json() == {"messageId": mid, "rating": "down", "comment": "wrong"}
    assert (await client.get(f"/v1/messages/{mid}/feedback", headers=h)).json()["rating"] == "down"
    async with app.state.db.sessionmaker() as s:
        assert await s.scalar(select(func.count()).select_from(MessageFeedback)) == 1
    assert (await client.put(f"/v1/messages/{user_mid}/feedback", json={"rating": "up"}, headers=h)).status_code == 404
    assert (await client.put(f"/v1/messages/{mid}/feedback", json={"rating": "meh"}, headers=h)).status_code == 422
    assert (await client.delete(f"/v1/messages/{mid}/feedback", headers=h)).status_code == 204
    assert (await client.get(f"/v1/messages/{mid}/feedback", headers=h)).status_code == 404


async def test_per_user_generation_quota(fake_llm):
    import httpx

    from app.auth.emails import MemoryEmailSender
    from app.main import create_app

    application = create_app(
        make_settings(chat_generations_per_minute=2), llm=fake_llm, email_sender=MemoryEmailSender()
    )
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://t") as client:
            account = await register(client, application)
            for _ in range(2):
                r, _ = await stream_chat(client, account["headers"], "hi")
                assert r.status_code == 200
            r = await client.post("/v1/chat/stream", json={"message": "hi"}, headers=account["headers"])
            assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
            # deleting conversations does not reset the quota
            for c in (await client.get("/v1/conversations", headers=account["headers"])).json()["items"]:
                await client.delete(f"/v1/conversations/{c['id']}", headers=account["headers"])
            r = await client.post("/v1/chat/stream", json={"message": "hi"}, headers=account["headers"])
            assert r.status_code == 429
