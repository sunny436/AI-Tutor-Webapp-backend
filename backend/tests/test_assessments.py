"""Practice tests and fill-in-the-blanks exercises in a reply (app/assessments/state.py): built
with the reply, all or nothing; answered in order, graded and recorded by the server; a retry
records nothing twice; a regenerated reply's test is closed; the tutor is told the record, latest
first, in words it uses (scripts/eval_tutor_record.py checks that against the model)."""

import asyncio
import json
import uuid

from sqlalchemy import update

from app.assessments import state as assessments
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

    # A reload shows exactly what was recorded (the response adds only `learning`, null for a model's test).
    page = await client.get(f"/v1/conversations/{message['conversationId']}/messages", headers=h)
    assert last.pop("learning") is None and page.json()["items"][-1]["metadata"]["assessments"] == [last]
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
    assert (await respond(client, h, message, 1, value=["A"])).status_code == 422  # texts are for blanks
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

    async def told(question: str) -> str:
        fake_llm.reply = lambda messages: "Here is how it went."
        await stream_chat(client, h, question, message["conversationId"])
        system = fake_llm.calls[-1][0].content
        return system[system.index("## Practice tests in this chat") :]

    await respond(client, h, message, 0, value=0)  # wrong: the answer is B
    tests = await told("why was that wrong?")
    assert 'Latest test "Cells": IN PROGRESS, 1 of 3 answered (0 right); question 2 is waiting.' in tests
    assert "Q1 A wrong (B)" in tests and "Never say you cannot see their answers." in tests
    await respond(client, h, message, 1, value=0)  # right
    await respond(client, h, message, 2, action="skip")
    # The state that went wrong live (2026-10-01): a finished test must read as finished, with
    # every answer, and no longer as something answered in the card.
    tests = await told("how was my performance?")
    assert 'Latest test "Cells": FINISHED. Score 1 out of 3 (1 right, 1 wrong, 1 skipped).' in tests
    assert "Q1 A wrong (B); Q2 A right; Q3 skipped (A)" in tests and "test card" not in tests
    # The wording of what they missed: still there once a long chat pushes the test out of view.
    assert (
        '- Missed questions (the latest 2): Q1 "Which organelle makes most of a cell\'s ATP?": '
        'chose "Nucleus", right "Mitochondrion"; Q3 "Which part only plant cells have?": skipped, right "Cell wall"'
    ) in tests


EXERCISE = (
    "Fill these in.\n\n```fill-blank\n"
    + json.dumps(
        {
            "text": "Water boils at [[100|hundred]] °C and freezes at [[0|zero]] °C. Ice is [[solid]].",
            "explanation": "At sea level.",
        }
    )
    + "\n```"
)


async def test_a_fill_in_the_blanks_exercise_is_recorded_graded_and_told_to_the_tutor(client, app, fake_llm):
    account, message = await quiz_reply(client, app, fake_llm, reply=EXERCISE, ask="Give me a fill in the blanks")
    h = account["headers"]
    [exercise] = message["metadata"]["assessments"]
    blank = exercise["questions"][0]
    assert (exercise["kind"], exercise["total"], exercise["possible"]) == ("exercise", 1, 3)
    assert (blank["kind"], blank["blanks"], blank["segments"][0]) == ("fill_blank", 3, "Water boils at ")
    assert blank["answers"] is None and blank["explanation"] is None  # nothing given away before checking
    assert (await respond(client, h, message, 0, value=["100", "0"])).status_code == 422  # one text per blank

    typed = ["Hundred.", " ZERO ", "liquid"]
    checked = await respond(client, h, message, 0, value=typed)
    assert checked.status_code == 200, checked.text
    checked = checked.json()
    assert (checked["state"], checked["earned"], checked["possible"]) == ("completed", 2, 3)
    assert checked["questions"][0]["response"]["marks"] == [True, True, False]  # case, spaces, a trailing stop
    assert checked["questions"][0]["answers"] == [["100", "hundred"], ["0", "zero"], ["solid"]]
    again = await respond(client, h, message, 0, value=typed)
    assert again.status_code == 200 and again.json() == checked  # a retry records nothing new
    other = await respond(client, h, message, 0, value=["100", "0", "solid"])
    assert other.status_code == 409 and other.json()["error"]["code"] == "assessment_answered"
    page = await client.get(f"/v1/conversations/{message['conversationId']}/messages", headers=h)
    assert checked.pop("learning") is None  # an exercise is never practice evidence
    assert page.json()["items"][-1]["metadata"]["assessments"] == [checked]

    fake_llm.reply = lambda messages: "Nice work."
    await stream_chat(client, h, "did I get the blanks right?", message["conversationId"])
    system = fake_llm.calls[-1][0].content
    assert "CHECKED. Score 2 out of 3 blanks (2 right, 1 wrong)." in system
    assert '1 "Hundred." right; 2 "ZERO" right; 3 "liquid" wrong ("solid")' in system
    assert '- Text: "Water boils at __1__ °C and freezes at __2__ °C. Ice is __3__."' in system


async def test_an_unanswered_exercise_has_no_score_and_the_tutor_never_sees_its_answer_key(client, app, fake_llm):
    account, message = await quiz_reply(client, app, fake_llm, reply=EXERCISE, ask="Give me a fill in the blanks")
    fake_llm.reply = lambda messages: "You haven't answered it yet."
    await stream_chat(client, account["headers"], "did I get the blanks right?", message["conversationId"])
    system, *history = fake_llm.calls[-1]
    assert "NOT ANSWERED YET" in system.content and "There is no score yet" in system.content
    assert "answer from this record: the score" not in system.content  # nothing asks it for a score
    shown = next(turn.content for turn in history if turn.role == "assistant")
    assert "fill-blank" in shown and "[[" not in shown and shown.count("____") == 3  # the key never reaches it

    # Empty and blank-only answers are answers, checked and wrong; an accepted spelling and partial credit count.
    [record], _ = assessments.build(EXERCISE, "q")
    checked, changed = assessments.respond(
        record,
        status="complete",
        client_hash=record["hash"],
        question=0,
        action="answer",
        value=["", "   ", "Solid."],
        at="2026-10-23T10:00:00+00:00",
    )
    response = checked["responses"][0]
    assert changed and (response["status"], response["earned"], response["marks"]) == (
        "answered",
        1,
        [False, False, True],
    )
    assert "CHECKED. Score 1 out of 3 blanks (1 right, 2 wrong)." in assessments.tutor_summary([checked])


async def test_a_reply_saved_before_its_block_was_recorded_becomes_answerable(client, app, fake_llm):
    # Before 2026-10-01 a reply's test or exercise had no record: its text gives one when read.
    account, message = await quiz_reply(client, app, fake_llm, reply="Plain words.", ask="Hello there, tutor")
    h = account["headers"]
    async with app.state.db.sessionmaker() as session:
        await session.execute(
            update(Message).where(Message.id == uuid.UUID(message["id"])).values(content=EXERCISE, metadata_={})
        )
        await session.commit()
    page = await client.get(f"/v1/conversations/{message['conversationId']}/messages", headers=h)
    message = page.json()["items"][-1]
    [exercise] = message["metadata"]["assessments"]
    assert (exercise["kind"], exercise["state"], exercise["answerable"]) == ("exercise", "not_started", True)
    answered = await respond(client, h, message, 0, value=["100", "0", "ice"])
    assert answered.status_code == 200 and answered.json()["earned"] == 2
    assert await stored(app, message["id"]) == [(0, "answered", ["100", "0", "ice"], 2)]  # stored by the answer
