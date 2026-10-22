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
    assert meta["conversation"]["title"] == done["conversation"]["title"] == "New chat"  # small talk names nothing
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


LONG_QUESTION = "Explain how photosynthesis works in plants and why it matters for life on Earth today"


def _log_blob(records) -> str:
    """What the JSON formatter writes for these records: message, extra fields, exception text."""
    import logging

    standard = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}
    return " ".join(
        f"{r.getMessage()} { {k: v for k, v in r.__dict__.items() if k not in standard} } {r.exc_text or ''}"
        for r in records
    )


async def test_new_chat_is_named_once_when_its_first_meaningful_question_is_answered(client, app, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="app.chat")
    account = await register(client, app)
    h = account["headers"]
    _, events = await stream_chat(client, h, "hi")
    cid = events[0][1]["conversationId"]
    assert events[0][1]["conversation"]["title"] == events[-1][1]["conversation"]["title"] == "New chat"

    _, events = await stream_chat(client, h, LONG_QUESTION, conversation_id=cid)
    assert events[0][1]["conversation"]["title"] == "New chat"  # named when the reply completes, not before
    assert events[-1][1]["conversation"]["title"] == "How Photosynthesis Works in Plants"
    _, events = await stream_chat(client, h, "What is the difference between mitosis and meiosis?", cid)
    assert events[-1][1]["conversation"]["title"] == "How Photosynthesis Works in Plants"  # never renamed
    listed = (await client.get("/v1/conversations", headers=h)).json()["items"]
    assert [c["title"] for c in listed] == ["How Photosynthesis Works in Plants"]

    titled = [r for r in caplog.records if r.getMessage() == "conversation titled"]
    assert [(r.source, r.words) for r in titled] == [("question", 5)]
    assert {r.reason for r in caplog.records if r.getMessage() == "conversation title skipped"} == {"small_talk"}
    blob = _log_blob(caplog.records).lower()
    assert "photosynthesis" not in blob and "mitosis" not in blob  # no question, reply or title text


async def test_an_empty_or_renamed_conversation_is_named_only_while_it_is_new_chat(client, app):
    account = await register(client, app)
    h = account["headers"]
    created = (await client.post("/v1/conversations", json={}, headers=h)).json()
    _, events = await stream_chat(client, h, "Explain photosynthesis", conversation_id=created["id"])
    assert events[-1][1]["conversation"]["title"] == "Photosynthesis Explained"

    renamed = (await client.post("/v1/conversations", json={}, headers=h)).json()
    await client.patch(f"/v1/conversations/{renamed['id']}", json={"title": "Trip plans"}, headers=h)
    _, events = await stream_chat(client, h, "Explain photosynthesis", conversation_id=renamed["id"])
    assert events[-1][1]["conversation"]["title"] == "Trip plans"


async def test_naming_touches_only_the_owners_conversation(client, app):
    alice, bob = await register(client, app), await register(client, app)
    await client.post("/v1/conversations", json={}, headers=bob["headers"])
    await stream_chat(client, alice["headers"], "Explain photosynthesis")
    bobs = (await client.get("/v1/conversations", headers=bob["headers"])).json()["items"]
    alices = (await client.get("/v1/conversations", headers=alice["headers"])).json()["items"]
    assert [c["title"] for c in bobs] == ["New chat"]
    assert [c["title"] for c in alices] == ["Photosynthesis Explained"]


async def test_a_failed_reply_names_nothing_and_a_successful_retry_does(client, app, fake_llm):
    fake_llm.fail_before_first = LLMUnavailable("down")
    account = await register(client, app)
    h = account["headers"]
    _, events = await stream_chat(client, h, "Explain photosynthesis")
    cid = events[0][1]["conversationId"]
    assert events[-1][0] == "error"
    assert (await client.get(f"/v1/conversations/{cid}", headers=h)).json()["title"] == "New chat"
    fake_llm.fail_before_first = None
    retried = parse_sse((await client.post(f"/v1/conversations/{cid}/regenerate/stream", headers=h)).text)
    assert retried[-1][0] == "done" and retried[-1][1]["conversation"]["title"] == "Photosynthesis Explained"


async def test_a_title_failure_never_fails_the_reply(client, app, caplog, monkeypatch):
    import logging

    from app.chat import service

    def broken(question, reply):
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "topic_title", broken)
    caplog.set_level(logging.INFO, logger="app.chat")
    account = await register(client, app)
    _, events = await stream_chat(client, account["headers"], "Explain photosynthesis")
    assert events[-1][0] == "done" and events[-1][1]["message"]["status"] == "complete"
    assert events[-1][1]["conversation"]["title"] == "New chat"
    assert "conversation title failed" in {r.getMessage() for r in caplog.records}


async def test_slow_generations_are_logged_without_content(client, app, caplog, monkeypatch):
    import logging

    from app.chat import service

    monkeypatch.setattr(service, "SLOW_TOTAL_MS", -1)
    caplog.set_level(logging.INFO, logger="app.chat")
    account = await register(client, app)
    await stream_chat(client, account["headers"], "Explain photosynthesis")
    slow = [r for r in caplog.records if r.getMessage() == "generation slow"]
    assert len(slow) == 1 and slow[0].levelname == "WARNING" and slow[0].status == "complete"
    assert slow[0].latency_ms >= 0 and "photosynthesis" not in _log_blob(slow).lower()


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
    llm = slow_app.state.llm
    for _ in range(200):  # cancel only once the model has demonstrably produced tokens
        if llm.emitted >= 3:
            break
        await asyncio.sleep(0.05)
    r = await slow_client.post(f"/v1/messages/{streaming.id}/cancel", headers=account["headers"])
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    response, events = await asyncio.wait_for(task, 10)
    done = events[-1]
    assert done[0] == "done" and done[1]["message"]["status"] == "cancelled"
    partial = done[1]["message"]["content"]
    assert partial and partial.startswith("w0") and len(partial.split()) < 60
    assert done[1]["conversation"]["title"] == "New chat"  # a stopped reply names nothing
    async with slow_app.state.db.sessionmaker() as s:
        msg = await s.get(Message, streaming.id)
    assert msg.status == "cancelled" and msg.content == partial
    # cancelling again is idempotent
    again = await slow_client.post(f"/v1/messages/{streaming.id}/cancel", headers=account["headers"])
    assert again.json()["status"] == "cancelled"


async def test_a_rename_during_the_first_reply_is_never_overwritten(slow_client, slow_app):
    account = await register(slow_client, slow_app)
    h = account["headers"]
    task = asyncio.create_task(stream_chat(slow_client, h, "Explain photosynthesis"))
    streaming = await _wait_for_streaming(slow_app)
    r = await slow_client.patch(
        f"/v1/conversations/{streaming.conversation_id}", json={"title": "My biology notes"}, headers=h
    )
    assert r.status_code == 200
    _, events = await asyncio.wait_for(task, 10)
    assert events[-1][0] == "done" and events[-1][1]["message"]["status"] == "complete"
    assert events[-1][1]["conversation"]["title"] == "My biology notes"


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


# ------------------------------------------------------------------ RAG through the chat API
KB_DOC = "# Aurelian Quokka protocol\n\nThe Aurelian Quokka protocol listens on port 7777 for telemetry."
KB_QUESTION = "Which port does the Aurelian Quokka protocol use for telemetry?"


async def _rag_app(**settings_overrides):
    from app.auth.emails import MemoryEmailSender
    from app.main import create_app
    from app.rag.embeddings import KeywordHashEmbeddings
    from tests.conftest import SpyEmbeddings

    spy = SpyEmbeddings(KeywordHashEmbeddings(1536, model="fake:text-embedding-3-small"))
    llm = FakeProvider()
    application = create_app(
        make_settings(**settings_overrides), llm=llm, email_sender=MemoryEmailSender(), embeddings=spy
    )
    return application, llm, spy


async def _assistant_row(app, message_id):
    async with app.state.db.sessionmaker() as s:
        return await s.get(Message, message_id)


async def test_chat_uses_the_knowledge_base_end_to_end(client, app, fake_llm):
    from tests.conftest import ingest_docs

    await ingest_docs(app, {"quokka.md": KB_DOC})
    account = await register(client, app)
    _, events = await stream_chat(client, account["headers"], KB_QUESTION)
    done = events[-1][1]["message"]
    prompt = fake_llm.calls[-1]
    assert prompt[1].role == "system" and "[1] Aurelian Quokka protocol" in prompt[1].content
    assert "port 7777" in prompt[1].content and prompt[-1].content == KB_QUESTION
    row = await _assistant_row(app, done["id"])
    retrieval = row.metadata_["retrieval"]
    assert row.status == "complete" and retrieval["status"] == "ok" and retrieval["chunkCount"] >= 1
    assert retrieval["sources"][0]["uri"] == "quokka.md" and retrieval["sources"][0]["title"]
    assert "retrieval" not in done["metadata"]  # internal only: the public contract is unchanged


async def test_small_talk_that_opens_a_chat_searches_nothing_but_a_follow_up_does(client, app):
    from tests.conftest import ingest_docs

    await ingest_docs(app, {"quokka.md": KB_DOC})
    headers = (await register(client, app))["headers"]
    _, events = await stream_chat(client, headers, "hi")
    cid = events[0][1]["conversationId"]
    greeting = await _assistant_row(app, events[-1][1]["message"]["id"])
    assert greeting.metadata_["retrieval"]["reason"] == "not_requested"
    _, events = await stream_chat(client, headers, KB_QUESTION, cid)
    assert (await _assistant_row(app, events[-1][1]["message"]["id"])).metadata_["retrieval"]["status"] == "ok"
    # "why?" alone would search for nothing; after a question it is searched with it (search_query_for).
    _, events = await stream_chat(client, headers, "why?", cid)
    follow_up = (await _assistant_row(app, events[-1][1]["message"]["id"])).metadata_["retrieval"]
    assert follow_up["status"] == "ok" and follow_up["sources"][0]["uri"] == "quokka.md"


async def test_embedding_outage_keeps_chat_working():
    import httpx

    from app.rag.errors import EmbeddingError
    from tests.conftest import ingest_docs

    application, _, spy = await _rag_app()
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://t") as client:
            await ingest_docs(application, {"quokka.md": KB_DOC})
            spy.fail_with = EmbeddingError("embedding_unauthorized")
            account = await register(client, application)
            _, events = await stream_chat(client, account["headers"], KB_QUESTION)
            assert events[-1][0] == "done" and events[-1][1]["message"]["status"] == "complete"
            row = await _assistant_row(application, events[-1][1]["message"]["id"])
            assert row.metadata_["retrieval"]["status"] == "failed"
            assert row.metadata_["retrieval"]["reason"] == "embedding_unauthorized"


async def test_rag_disabled_makes_no_embedding_calls():
    import httpx

    from tests.conftest import ingest_docs

    application, llm, spy = await _rag_app(rag_enabled=False)
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://t") as client:
            await ingest_docs(application, {"quokka.md": KB_DOC})
            calls_after_ingest = spy.calls
            account = await register(client, application)
            _, events = await stream_chat(client, account["headers"], KB_QUESTION)
            assert events[-1][0] == "done" and spy.calls == calls_after_ingest
            row = await _assistant_row(application, events[-1][1]["message"]["id"])
            assert row.metadata_["retrieval"] == {
                **row.metadata_["retrieval"],
                "status": "skipped",
                "reason": "disabled",
            }
            assert [m.role for m in llm.calls[-1]] == ["system", "user"]


async def test_private_knowledge_is_scoped_to_its_owner_in_chat(client, app, fake_llm):
    from sqlalchemy import select as sa_select

    from app.db.models import User
    from tests.conftest import ingest_docs

    alice = await register(client, app)
    bob = await register(client, app)
    async with app.state.db.sessionmaker() as s:
        alice_id = await s.scalar(sa_select(User.id).where(User.email == alice["email"]))
    await ingest_docs(app, {"quokka.md": KB_DOC}, source="alice-private", owner_user_id=alice_id)

    _, events = await stream_chat(client, bob["headers"], KB_QUESTION)
    assert "7777" not in "".join(m.content for m in fake_llm.calls[-1])
    bob_row = await _assistant_row(app, events[-1][1]["message"]["id"])
    assert bob_row.metadata_["retrieval"]["reason"] == "empty_knowledge_base"

    _, events = await stream_chat(client, alice["headers"], KB_QUESTION)
    assert "7777" in fake_llm.calls[-1][1].content


async def test_logs_never_contain_the_question_or_document_text(client, app, caplog):
    import logging

    from tests.conftest import ingest_docs

    caplog.set_level(logging.DEBUG)
    await ingest_docs(app, {"quokka.md": KB_DOC})
    account = await register(client, app)
    await stream_chat(client, account["headers"], KB_QUESTION)
    # Exactly what the JSON formatter writes: the message, the `extra` fields and any exception
    # text. LogRecord internals (timestamps, thread ids) are excluded: a timestamp such as
    # 1790167777.7 once matched "7777" and produced a false positive.
    standard = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}
    records = [
        (
            r.name,
            r.levelname,
            f"{r.getMessage()} { ({k: v for k, v in r.__dict__.items() if k not in standard}) } {r.exc_text or ''}",
        )
        for r in caplog.records
    ]
    names = {r.getMessage() for r in caplog.records}
    assert {"rag.retrieval", "rag.graph"} <= names, sorted(names)  # the events are logged...
    leaks = [
        (name, level, blob[:400])
        for name, level, blob in records
        for secret in ("Aurelian", "Quokka", "telemetry", "port 7777")
        if secret in blob
    ]
    assert leaks == []  # ...without query or document content (shows the offending record if not)
