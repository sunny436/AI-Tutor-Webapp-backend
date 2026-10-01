"""Practice tests in a reply (app/assessments/state.py): built with the reply, all or nothing;
answered in order, graded and recorded by the server; a retry records nothing twice; a
regenerated reply's test is closed; the tutor is told the record, latest test first."""

import asyncio
import json
import uuid

from app.db.models import Message
from tests.conftest import parse_sse, register, stream_chat

QUESTIONS = [
    {
        "question": "Which organelle makes most of a cell's ATP?",
        "options": ["Nucleus", "Mitochondrion", "Ribosome"],
        "answer": "B",
        "explanation": "Respiration happens there.",
    },
    {"question": "What carries genes?", "options": ["DNA", "Lipids", "Starch"], "answer": 0},
    {"question": "Which part only plant cells have?", "options": ["Cell wall", "Centriole"], "answer": "Cell wall"},
]
QUIZ = "Here is your test.\n\n```quiz\n" + json.dumps({"title": "Cells", "questions": QUESTIONS}, indent=2) + "\n```"


async def quiz_reply(client, app, fake_llm, reply: str = QUIZ, ask: str = "Quiz me with 3 MCQs on cells"):
    fake_llm.reply = lambda messages: reply
    account = await register(client, app)
    response, events = await stream_chat(client, account["headers"], ask)
    assert response.status_code == 200 and events[-1][0] == "done", response.text
    return account, events[-1][1]["message"]


async def respond(client, headers, message: dict, question: int, action: str = "answer", value=None, test=None):
    test = test or message["metadata"]["assessments"][0]
    body = {"position": 0, "hash": test["hash"], "question": question, "action": action}
    if value is not None:
        body["value"] = value
    return await client.post(f"/v1/messages/{message['id']}/assessment-responses", json=body, headers=headers)


async def stored(app, message_id: str) -> list[tuple]:
    async with app.state.db.sessionmaker() as session:
        record = (await session.get(Message, uuid.UUID(message_id))).metadata_["assessments"][0]
    return [(r["question"], r["status"], r["value"], r["earned"]) for r in record["responses"]]


async def test_a_test_is_built_with_its_reply_then_answered_skipped_completed_and_reloaded(client, app, fake_llm):
    account, message = await quiz_reply(client, app, fake_llm)
    [test] = message["metadata"]["assessments"]
    assert test["id"] == f"{message['id']}:0" and test["schemaVersion"] == 1 and test["kind"] == "test"
    assert (test["state"], test["answerable"], test["total"], test["current"]) == ("not_started", True, 3, 0)
    assert all(q["response"] is None and q["correct"] is None and q["explanation"] is None for q in test["questions"])

    h = account["headers"]
    first = await respond(client, h, message, 0, value=1)
    assert first.status_code == 200, first.text
    first = first.json()
    assert (first["state"], first["current"], first["earned"]) == ("active", 1, 1)
    assert (
        first["questions"][0]["correct"] == 1 and first["questions"][0]["explanation"] == "Respiration happens there."
    )
    assert first["questions"][1]["correct"] is None  # the next answer stays on the server
    skipped = (await respond(client, h, message, 1, action="skip")).json()
    assert skipped["questions"][1]["response"]["status"] == "skipped" and skipped["earned"] == 1
    last = (await respond(client, h, message, 2, value=1)).json()
    assert (last["state"], last["answerable"], last["current"]) == ("completed", False, None)
    assert (last["earned"], last["possible"]) == (1, 3)

    # A reload shows exactly what was recorded.
    page = await client.get(f"/v1/conversations/{message['conversationId']}/messages", headers=h)
    assert page.json()["items"][-1]["metadata"]["assessments"] == [last]
    assert await stored(app, message["id"]) == [(0, "answered", 1, 1), (1, "skipped", None, 0), (2, "answered", 1, 0)]


async def test_a_retried_response_is_recorded_once(client, app, fake_llm):
    account, message = await quiz_reply(client, app, fake_llm)
    h = account["headers"]
    # The first reply was lost on the way back: the client sends the same response again.
    first, again = await respond(client, h, message, 0, value=2), await respond(client, h, message, 0, value=2)
    assert first.status_code == again.status_code == 200 and first.json() == again.json()
    skip, skip_again = (
        await respond(client, h, message, 1, action="skip"),
        await respond(client, h, message, 1, action="skip"),
    )
    assert skip.status_code == skip_again.status_code == 200
    assert await stored(app, message["id"]) == [(0, "answered", 2, 0), (1, "skipped", None, 0)]


async def test_answers_are_final_and_in_order(client, app, fake_llm):
    account, message = await quiz_reply(client, app, fake_llm)
    h = account["headers"]
    assert (await respond(client, h, message, 0, value=1)).status_code == 200
    for response, code in [
        (await respond(client, h, message, 0, value=0), "assessment_answered"),
        (await respond(client, h, message, 0, action="skip"), "assessment_answered"),
        (await respond(client, h, message, 2, value=0), "assessment_out_of_order"),
        (await respond(client, h, message, 1, value=0, test={"hash": "0" * 64}), "assessment_changed"),
    ]:
        assert response.status_code == 409 and response.json()["error"]["code"] == code, response.text
    assert (await respond(client, h, message, 1, value=7)).status_code == 422  # no such option
    url = f"/v1/messages/{message['id']}/assessment-responses"
    test = message["metadata"]["assessments"][0]
    no_value = {"position": 0, "hash": test["hash"], "question": 1, "action": "answer"}
    assert (await client.post(url, json=no_value, headers=h)).status_code == 422
    assert (await client.post(url, json={**no_value, "position": 1, "value": 0}, headers=h)).status_code == 404
    assert await stored(app, message["id"]) == [(0, "answered", 1, 1)]


async def test_a_double_tap_or_two_tabs_record_one_response(client, app, fake_llm):
    account, message = await quiz_reply(client, app, fake_llm)
    h = account["headers"]
    same = await asyncio.gather(*(respond(client, h, message, 0, value=1) for _ in range(3)))
    assert [r.status_code for r in same] == [200, 200, 200]
    different = await asyncio.gather(respond(client, h, message, 1, value=0), respond(client, h, message, 1, value=2))
    assert sorted(r.status_code for r in different) == [200, 409]
    assert len(await stored(app, message["id"])) == 2


async def test_a_regenerated_reply_closes_its_test_and_brings_a_new_one(client, app, fake_llm):
    account, old = await quiz_reply(client, app, fake_llm)
    h = account["headers"]
    assert (await respond(client, h, old, 0, value=1)).status_code == 200
    events = parse_sse(
        (await client.post(f"/v1/conversations/{old['conversationId']}/regenerate/stream", headers=h)).text
    )
    new = events[-1][1]["message"]
    assert new["id"] != old["id"] and new["metadata"]["assessments"][0]["state"] == "not_started"
    closed = await respond(client, h, old, 1, value=0)
    assert closed.status_code == 409 and closed.json()["error"]["code"] == "assessment_closed"
    # Another test's hash names a different test: refused, nothing recorded.
    _, other = await quiz_reply(client, app, fake_llm, reply=QUIZ.replace("Cells", "Cell biology"))
    assert other["metadata"]["assessments"][0]["hash"] != new["metadata"]["assessments"][0]["hash"]
    crossed = await respond(client, h, new, 0, value=1, test=other["metadata"]["assessments"][0])
    assert crossed.status_code == 409 and crossed.json()["error"]["code"] == "assessment_changed"
    assert await stored(app, new["id"]) == []


async def test_a_malformed_test_is_never_kept_in_part(client, app, fake_llm):
    two_blocks = QUIZ + "\n\n```mcq\n" + json.dumps(QUESTIONS[0]) + "\n```"
    duplicate_option = QUIZ.replace('"Starch"', '"DNA"')
    for reply, ask, code in [
        (two_blocks, "Quiz me on cells", "multiple_tests"),
        (duplicate_option, "Quiz me on cells", "invalid_question"),
        (QUIZ, "Give me 10 MCQ one by one", "count_mismatch"),
    ]:
        _, message = await quiz_reply(client, app, fake_llm, reply=reply, ask=ask)
        assert "assessments" not in message["metadata"], code
        assert message["metadata"]["assessmentError"] == {"code": code}
        assert message["content"] == reply  # the reply itself is kept as written


async def test_the_tutor_is_told_the_recorded_test_first(client, app, fake_llm):
    account, message = await quiz_reply(client, app, fake_llm)
    h = account["headers"]
    await respond(client, h, message, 0, value=0)  # wrong: the answer is B
    fake_llm.reply = lambda messages: "Because the mitochondrion makes ATP."
    await stream_chat(client, h, "why was that wrong?", message["conversationId"])
    system = fake_llm.calls[-1][0].content
    tests = system[system.index("## Practice tests in this chat") :]
    assert "question 2 of 3 is waiting" in tests and "Q1 A wrong (answer B)" in tests
    assert 'Why Q1: "Respiration happens there."' in tests
