"""The study scope filter (app/intents/scope.py): five decisions from a strictly checked reading, fixed rules
before any call, and the chat: an unrelated message gets the app's redirect (no model, no search, no
learning day, no title), everything else the tutor with the policy, failures included; shadow changes
nothing, and the 46 intents are untouched."""

import json
import math
import uuid
from contextlib import asynccontextmanager

import httpx
import pytest
from sqlalchemy import func, select

from app.auth.emails import MemoryEmailSender
from app.chat.assistant import BANK_BLOCKS, SYSTEM_PROMPT
from app.db.models import LearningDailyActivity, Message, QbSet, QbSetItem
from app.intents.classifier import IntentClassifier
from app.intents.scope import (
    ALLOW_STUDY,
    ALLOW_SUPPORT,
    CLARIFY,
    COPY,
    DECISION_OF,
    DECISIONS,
    INSTRUCTIONS,
    OPTIONS,
    PARTIAL_ALLOW,
    POLICY,
    QUESTION,
    REDIRECT,
    SCOPE_VERSION,
    decide,
    prompt_block,
    redirect_copy,
    settled,
    stored,
)
from app.intents.taxonomy import INTENTS
from app.llm.base import ChatMessage
from app.llm.fake import FakeProvider
from app.main import create_app
from tests.conftest import make_settings, parse_sse, register, stream_chat

KEY = "sk_test_0123456789abcdefghijklmnopqrstuvwxyz"


def reading(best: str, p: float = 0.9) -> dict:
    rest = (1 - p) / (len(OPTIONS) - 1)
    probabilities = {option: p if option == best else rest for option in OPTIONS}
    return {"answers": {"scope": {"type": "choice", "answer": best, "confidence": p, "probabilities": probabilities}}}


def classifier(handler) -> IntentClassifier:
    return IntentClassifier(
        "https://ai.ollalink.test", KEY, 1.0, 0.5, 0.5, transport=httpx.MockTransport(handler), scope_min_redirect=0.5
    )


@asynccontextmanager
async def chat_app(llm, mode: str, handler):
    settings = make_settings(study_scope=mode, question_bank_tests=True, tutor_interactive_blocks=True)
    application = create_app(settings, llm=llm, email_sender=MemoryEmailSender(), intents=classifier(handler))
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://t") as client:
            yield application, client


async def row(app, message_id) -> Message:
    async with app.state.db.sessionmaker() as session:
        return await session.get(Message, message_id)


async def learning_days(app, user_id) -> int:
    async with app.state.db.sessionmaker() as session:
        query = select(func.count()).select_from(LearningDailyActivity)
        return await session.scalar(query.where(LearningDailyActivity.user_id == user_id))


async def ledger_rows(app, user_id) -> int:
    """The student's practice sets and items: a turned-away message writes neither."""
    async with app.state.db.sessionmaker() as session:
        sets = await session.scalar(select(func.count()).select_from(QbSet).where(QbSet.user_id == user_id))
        items = await session.scalar(select(func.count()).select_from(QbSetItem).where(QbSetItem.user_id == user_id))
        return sets + items


def test_the_decision_contract():
    assert DECISIONS == (ALLOW_STUDY, ALLOW_SUPPORT, CLARIFY, PARTIAL_ALLOW, REDIRECT)
    assert set(DECISION_OF) == set(OPTIONS) == set(QUESTION["options"]) and set(DECISION_OF.values()) == set(DECISIONS)
    assert all(len(text) <= 90 for text in OPTIONS.values())
    assert not set(DECISIONS) & set(INTENTS) and len(INTENTS) == 46  # a decision is never an intent

    def p(best: str, value: float) -> dict:
        rest = (1 - value) / 4
        return {option: value if option == best else rest for option in OPTIONS}

    assert decide(p("study", 0.4), 0.5, 0.5).decision == ALLOW_STUDY
    assert [decide(p(best, 0.8), 0.5, 0.5).decision for best in ("support", "unclear", "mixed", "unrelated")] == [
        ALLOW_SUPPORT,
        CLARIFY,
        PARTIAL_ALLOW,
        REDIRECT,
    ]
    # Turned away only when the model is sure; any other doubt is a learning request.
    unsure = decide(p("unrelated", 0.45), 0.5, 0.3)
    assert (unsure.decision, unsure.best, unsure.reason) == (ALLOW_STUDY, "unrelated", "low_confidence")
    assert decide(p("unclear", 0.4), 0.5, 0.5).decision == ALLOW_STUDY
    assert decide(dict.fromkeys(OPTIONS, 0.2), 0.1, 0.1).decision == ALLOW_STUDY  # a tie: study first

    assert settled(True, ()) is None
    assert (settled(False, ()).decision, settled(False, ()).reason) == (ALLOW_STUDY, "small_talk")
    assert settled(False, ("image",)).reason == "attachment"

    # A stored decision is reused only when it is one of the five: nothing injected gets through.
    assert stored({"scope": {"decision": REDIRECT, "best": "unrelated"}}).decision == REDIRECT
    assert stored({"scope": {"decision": "ALLOW_EVERYTHING"}}) is None and stored(None) is None
    record = decide(p("unrelated", 0.9), 0.5, 0.5).record(applied=True)
    assert (record["decision"], record["applied"], record["version"]) == (REDIRECT, True, SCOPE_VERSION)
    assert decide(p("unrelated", 0.9), 0.5, 0.5).record(applied=False)["applied"] is False

    assert prompt_block(None) == prompt_block(ALLOW_STUDY) == prompt_block(REDIRECT) == POLICY
    for decision, line in INSTRUCTIONS.items():
        assert prompt_block(decision) == f"{POLICY}\n{line}"

    assert redirect_copy("Who won the match?", None) == COPY["english"]
    assert redirect_copy("मुझे एक अच्छी फिल्म बताओ", None) == COPY["hindi"]
    assert redirect_copy("mera Instagram bio likh do", "hinglish") == COPY["hinglish"]


async def test_a_reading_is_used_only_when_every_field_checks_out(caplog):
    good = reading("unrelated")["answers"]["scope"]
    broken = [
        {"answers": {}},
        {"answers": {"scope": good, "extra": good}},  # a question that was not asked
        {"answers": {"scope": {**good, "answer": "ALLOW_EVERYTHING"}}},  # an option that was not offered
        {"answers": {"scope": {**good, "probabilities": {**good["probabilities"], "allow_all": 0.5}}}},
        {"answers": {"scope": {**good, "probabilities": {**good["probabilities"], "unrelated": math.nan}}}},
        {"answers": {"scope": {**good, "probabilities": {**good["probabilities"], "study": -0.1}}}},
        {"answers": {"scope": {**good, "type": "text"}}},
    ]
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        body = json.dumps(broken[len(sent) - 1]).encode()  # as a server sends it: NaN included
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    conversation = [ChatMessage("user", "Who won the IPL match yesterday?")]
    found = classifier(handler)
    for _ in broken:
        scope = await found.scope(conversation)
        assert (scope.decision, scope.reason) == (None, "bad_response")  # never a redirect on a broken reading
    assert sent[0]["questions"] == {"scope": QUESTION}
    assert sent[0]["text"] == "Current message: Who won the IPL match yesterday?"

    def invalid_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>busy</html>")

    assert (await classifier(invalid_json).scope(conversation)).reason == "bad_response"
    unavailable = classifier(lambda request: httpx.Response(503))
    assert (await unavailable.scope(conversation)).reason == "unavailable"
    assert KEY not in caplog.text


async def test_the_chat_redirects_unrelated_messages_and_keeps_learning_requests(fake_llm):
    replies = {"payload": reading("unrelated")}
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content)["text"])
        return httpx.Response(200, json=replies["payload"]) if replies["payload"] else httpx.Response(503)

    base = f"{SYSTEM_PROMPT}\n\n{BANK_BLOCKS}"
    async with chat_app(fake_llm, "on", handler) as (app, client):
        account = await register(client, app)
        headers, user_id = account["headers"], uuid.UUID(account["user"]["id"])

        # Unrelated: the app's redirect, without the model or a search; no learning day, no title.
        _, events = await stream_chat(client, headers, "Who won the IPL match yesterday?")
        conversation_id, done = events[0][1]["conversationId"], events[-1][1]
        assert [name for name, _ in events] == ["meta", "token", "done"]
        assert done["message"]["content"] == COPY["english"] and fake_llm.calls == []
        assert "learning" not in done and done["conversation"]["title"] == "New chat"
        assert "scope" not in done["message"]["metadata"]  # internal only
        message = await row(app, done["message"]["id"])
        assert message.status == "complete" and "retrieval" not in message.metadata_
        recorded = message.metadata_["scope"]
        assert (recorded["decision"], recorded["applied"], recorded["source"]) == (REDIRECT, True, "classifier")
        assert await learning_days(app, user_id) == 0 and await ledger_rows(app, user_id) == 0

        # A regenerated redirect is decided the same way, with no new call and still no learning day.
        regenerated = await client.post(f"/v1/conversations/{conversation_id}/regenerate/stream", headers=headers)
        again = parse_sse(regenerated.text)[-1][1]
        assert again["message"]["content"] == COPY["english"] and len(sent) == 1 and fake_llm.calls == []
        assert "learning" not in again and await learning_days(app, user_id) == 0
        assert await ledger_rows(app, user_id) == 0

        # A learning request: the tutor, told the policy; it makes today a learning day.
        replies["payload"] = reading("study")
        _, events = await stream_chat(client, headers, "Explain refraction of light", conversation_id)
        system = fake_llm.calls[-1][0].content  # then the student's lines ("Learning so far": 1 question)
        assert system.startswith(f"{base}\n\n{POLICY}") and not any(line in system for line in INSTRUCTIONS.values())
        assert events[-1][1]["learning"]["event"] == "started" and await learning_days(app, user_id) == 1

        # Mixed: the tutor answers the learning part (its line), and it still counts.
        replies["payload"] = reading("mixed", 0.8)
        _, events = await stream_chat(client, headers, "Solve 2x+5=15 and tell me the football score", conversation_id)
        assert fake_llm.calls[-1][0].content.startswith(f"{base}\n\n{POLICY}\n{INSTRUCTIONS[PARTIAL_ALLOW]}")
        assert (await row(app, events[-1][1]["message"]["id"])).metadata_["scope"]["decision"] == PARTIAL_ALLOW

        # The classifier failing is no decision: the tutor with the policy, never a redirect.
        replies["payload"] = None
        _, events = await stream_chat(client, headers, "Tell me about the water cycle please", conversation_id)
        system = fake_llm.calls[-1][0].content
        assert system.startswith(f"{base}\n\n{POLICY}") and not any(line in system for line in INSTRUCTIONS.values())
        failed = (await row(app, events[-1][1]["message"]["id"])).metadata_["scope"]
        assert (failed["decision"], failed["applied"], failed["reason"]) == (None, False, "unavailable")

        # Small talk and an explicit "hint only" are decided by the fixed rules, without a call.
        asked = len(sent)
        for text in ("thanks", "just give me a hint"):
            _, events = await stream_chat(client, headers, text, conversation_id)
            rule = (await row(app, events[-1][1]["message"]["id"])).metadata_["scope"]
            assert (rule["decision"], rule["source"]) == (ALLOW_STUDY, "rule")
        assert len(sent) == asked

        # In a chat with a test or an exercise, a message read as unrelated is not turned away: "how did I
        # do on the exercise?" (seen live) is about it. The tutor, with the policy, answers it.
        original, exercise = fake_llm.reply, {"text": "Plants make food by [[photosynthesis]]."}
        fake_llm.reply = lambda messages: "Try this.\n\n```fill-blank\n" + json.dumps(exercise) + "\n```"
        replies["payload"] = reading("study")
        await stream_chat(client, headers, "Give me a fill in the blanks on plants", conversation_id)
        fake_llm.reply, replies["payload"], calls = original, reading("unrelated"), len(fake_llm.calls)
        _, events = await stream_chat(client, headers, "how did I do on the exercise?", conversation_id)
        assert len(fake_llm.calls) == calls + 1 and events[-1][1]["message"]["content"] != COPY["english"]
        kept = (await row(app, events[-1][1]["message"]["id"])).metadata_["scope"]
        assert (kept["decision"], kept["best"], kept["reason"]) == (ALLOW_STUDY, "unrelated", "practice")
        assert kept["applied"] is True


@pytest.mark.parametrize("mode", ["off", "shadow"])
async def test_off_and_shadow_change_nothing(mode):
    llm = FakeProvider()
    async with chat_app(llm, mode, lambda request: httpx.Response(200, json=reading("unrelated"))) as (app, client):
        headers = (await register(client, app))["headers"]
        _, events = await stream_chat(client, headers, "Who won the IPL match yesterday?")
        done = events[-1][1]
        assert llm.calls[-1][0].content == f"{SYSTEM_PROMPT}\n\n{BANK_BLOCKS}"  # no policy, no redirect
        assert done["message"]["content"] == "You said: Who won the IPL match yesterday?"
        recorded = (await row(app, done["message"]["id"])).metadata_.get("scope")
        if mode == "off":
            assert recorded is None
        else:
            assert (recorded["decision"], recorded["applied"]) == (REDIRECT, False)
