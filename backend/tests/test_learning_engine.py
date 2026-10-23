"""The learning engine: a question-bank test in the chat grows a question per answer, chosen from the
answer before it (app/qbank/chat_tests.py); every answer is recorded once in the practice ledger, in
the transaction and under the lock that records it on the reply (app/chat/router.py); a retry is a
replay; five answers make a learning day, once; and the practice record (/v1/progress/*,
app/progress/practice.py) is the student's own and outlives the chat. The bank is synthetic
(tests/test_question_bank.py's book()); nothing calls a model."""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text, update

from app.assessments import state as assessments
from app.db.models import Message
from app.progress.learning import learning_date
from app.qbank import chat_tests
from app.qbank.importer import import_bank
from tests.conftest import PASSWORD, make_settings, parse_sse, register, stream_chat
from tests.test_question_bank import approve, book, save

PRACTICE = ("plan", "mastery", "revisions", "mistakes", "practice-tests", "practice-topics")
LEDGER = text(
    """
    SELECT i.position, i.question_id, i.chosen, i.is_correct, q.level, q.topic_id || ' ' || q.concept_tag AS concept,
           i.served_hash = q.content_hash AS current, s.closed_at IS NOT NULL AS closed, s.served, s.requested
    FROM qb_sets s
    JOIN qb_set_items i ON i.set_id = s.id
    JOIN qb_questions q ON q.question_id = i.question_id
    WHERE s.request_id = :message_id AND s.mode = 'chat'
    ORDER BY i.position
    """
)


@pytest.fixture
def settings():
    return make_settings(question_bank_tests=True, tutor_interactive_blocks=True)


@pytest.fixture
async def bank(app, tmp_path):
    """Two chapters of three topics, each topic with an easy, a medium and a hard question per concept
    (alpha, beta): 36 questions. Chapter ids in the form the chat reads (JESC1-CH09)."""
    written = json.loads(
        json.dumps(book(chapters=((1, 1000), (2, 1000)), topics=3, per_level=2)).replace("C10-SCI-EN-CH", "TSCI1-CH")
    )
    written["questions"] = {
        chapter: [approve(record, "english") for record in records] for chapter, records in written["questions"].items()
    }
    async with app.state.db.sessionmaker() as db:
        report = await import_bank(db, save(tmp_path, written), apply=True)
    assert report.applied, report.errors


def requesting(spec: dict) -> str:
    return "Here is your test.\n\n```question-bank\n" + json.dumps(spec) + "\n```"


async def bank_test(client, headers, fake_llm, spec: dict) -> dict:
    """A reply that sets a test from the bank. The question is small talk ("test"), so the turn itself
    never makes a learning day."""
    fake_llm.reply = lambda messages: requesting(spec)
    response, events = await stream_chat(client, headers, "test")
    assert response.status_code == 200 and events[-1][0] == "done", response.text
    return events[-1][1]["message"]


async def respond(client, headers, message: dict, test: dict, question: int, value: int | None = None):
    body = {"position": 0, "hash": test["hash"], "question": question}
    body |= {"action": "answer", "value": value} if value is not None else {"action": "skip"}
    return await client.post(f"/v1/messages/{message['id']}/assessment-responses", json=body, headers=headers)


async def ledger(app, message: dict) -> list[dict]:
    async with app.state.db.sessionmaker() as db:
        rows = await db.execute(LEDGER, {"message_id": uuid.UUID(message["id"])})
        return [dict(row) for row in rows.mappings()]


async def key(app, message: dict, position: int) -> int:
    """The right option of the question served at `position` (a test may look it up; a client never can)."""
    async with app.state.db.sessionmaker() as db:
        letter = await db.scalar(
            text(
                "SELECT q.correct_option FROM qb_sets s JOIN qb_set_items i ON i.set_id = s.id "
                "JOIN qb_questions q ON q.question_id = i.question_id WHERE s.request_id = :m AND i.position = :p"
            ),
            {"m": uuid.UUID(message["id"]), "p": position},
        )
    return "ABCD".index(letter)


async def take(client, app, headers, message: dict, rights: list[bool]) -> dict:
    """Answer the test's questions in turn, right or wrong as listed; the test as it ends."""
    test = message["metadata"]["assessments"][0]
    for question, right in enumerate(rights):
        answer = await key(app, message, question + 1)
        reply = await respond(client, headers, message, test, question, answer if right else (answer + 1) % 4)
        assert reply.status_code == 200, reply.text
        test = reply.json()
    return test


async def test_a_bank_test_grows_a_question_per_answer_chosen_from_it_and_each_answer_is_evidence(
    client, app, fake_llm, bank
):
    headers = (await register(client, app))["headers"]
    message = await bank_test(client, headers, fake_llm, {"chapter": "TSCI1-CH01", "count": 4})
    [test] = message["metadata"]["assessments"]
    assert (test["total"], len(test["questions"]), test["current"]) == (4, 1, 0)
    assert "setId" not in json.dumps(message)  # the ledger stays on the server
    finished = await take(client, app, headers, message, [True, False, True, True])
    assert (finished["state"], finished["earned"], finished["possible"], len(finished["questions"])) == (
        "completed",
        3,
        4,
        4,
    )
    rows = await ledger(app, message)
    assert [(row["position"], row["is_correct"]) for row in rows] == [(1, True), (2, False), (3, True), (4, True)]
    assert (
        all(row["current"] for row in rows)
        and rows[0]["closed"]
        and (rows[0]["served"], rows[0]["requested"]) == (4, 4)
    )
    # Medium first; right: one level harder, another concept; wrong: one level easier, the same concept.
    assert [row["level"] for row in rows] == [2, 3, 2, 3]
    assert rows[1]["concept"] != rows[0]["concept"] and rows[2]["concept"] == rows[1]["concept"]
    assert rows[3]["concept"] != rows[2]["concept"] and len({row["question_id"] for row in rows}) == 4
    page = await client.get(f"/v1/conversations/{message['conversationId']}/messages", headers=headers)
    assert finished.pop("learning") is None  # 4 answers: not yet a learning day
    assert page.json()["items"][-1]["metadata"]["assessments"] == [finished]  # a reload shows what was recorded


async def test_a_retry_is_a_replay_of_the_test_as_it_is_now_and_nothing_is_recorded_twice(client, app, fake_llm, bank):
    headers = (await register(client, app))["headers"]
    message = await bank_test(client, headers, fake_llm, {"chapter": "TSCI1-CH01", "count": 3})
    [shown] = message["metadata"]["assessments"]
    right = await key(app, message, 1)
    # Three taps at once, and then the client retries with the hash it had, its reply lost on the way.
    taps = await asyncio.gather(*(respond(client, headers, message, shown, 0, right) for _ in range(3)))
    assert [tap.status_code for tap in taps] == [200, 200, 200]
    again = await respond(client, headers, message, shown, 0, right)
    assert again.status_code == 200 and all(tap.json() == again.json() for tap in taps)
    advanced = again.json()
    assert (advanced["answered"], len(advanced["questions"]), advanced["current"]) == (1, 2, 1)
    rows = await ledger(app, message)
    assert [row["chosen"] is not None for row in rows] == [True, False]  # one answer, one question served
    for test, question, value, code in [
        (shown, 0, (right + 1) % 4, "assessment_answered"),  # another answer to an answered question
        (shown, 1, 0, "assessment_changed"),  # the old hash never showed question 2
        (advanced, 2, 0, "assessment_out_of_order"),  # question 3 is not chosen yet
    ]:
        refused = await respond(client, headers, message, test, question, value)
        assert refused.status_code == 409 and refused.json()["error"]["code"] == code, refused.text
    assert await ledger(app, message) == rows


async def test_a_skip_is_not_evidence_and_the_next_question_keeps_its_level(client, app, fake_llm, bank):
    headers = (await register(client, app))["headers"]
    message = await bank_test(client, headers, fake_llm, {"chapter": "TSCI1-CH01", "count": 3})
    [test] = message["metadata"]["assessments"]
    skipped = await respond(client, headers, message, test, 0)
    assert skipped.status_code == 200 and skipped.json()["learning"] is None
    rows = await ledger(app, message)
    assert rows[0]["chosen"] is None and rows[1]["level"] == rows[0]["level"] == 2
    assert rows[1]["concept"] != rows[0]["concept"]  # the same level, another concept
    mastery = (await client.get("/v1/progress/mastery", headers=headers)).json()
    assert (mastery["answered"], mastery["subjects"]) == (0, [])


async def test_a_regenerated_or_late_stopped_reply_closes_its_test(client, app, fake_llm, bank, monkeypatch):
    headers = (await register(client, app))["headers"]
    old = await bank_test(client, headers, fake_llm, {"chapter": "TSCI1-CH01", "count": 3})
    await take(client, app, headers, old, [True])
    events = parse_sse(
        (await client.post(f"/v1/conversations/{old['conversationId']}/regenerate/stream", headers=headers)).text
    )
    new = events[-1][1]["message"]
    assert (await ledger(app, old))[0]["closed"] and not (await ledger(app, new))[0]["closed"]

    original = chat_tests.fill

    async def stopped_while_saving(session, content, seed, *args, **kwargs):  # the Stop button, just then
        filled = await original(session, content, seed, *args, **kwargs)
        async with app.state.db.sessionmaker() as other:
            await other.execute(update(Message).where(Message.id == uuid.UUID(seed)).values(status="cancelled"))
            await other.commit()
        return filled

    monkeypatch.setattr(chat_tests, "fill", stopped_while_saving)
    stopped = await bank_test(client, headers, fake_llm, {"chapter": "TSCI1-CH01", "count": 3})
    assert stopped["status"] == "cancelled" and stopped["metadata"]["assessments"][0]["answerable"] is False
    assert (await ledger(app, stopped))[0]["closed"]


async def test_the_fifth_answer_of_the_day_makes_a_learning_day_once_also_from_two_tabs(client, app, fake_llm, bank):
    headers = (await register(client, app))["headers"]
    message = await bank_test(client, headers, fake_llm, {"chapter": "TSCI1-CH01", "count": 6})
    test, learning = message["metadata"]["assessments"][0], []
    for question in range(6):
        reply = (await respond(client, headers, message, test, question, 0)).json()
        test = reply
        learning.append(reply["learning"])
    assert learning == [None, None, None, None, {"event": "started", "streak": 1}, None]
    streak = (await client.get("/v1/progress/streak", headers=headers)).json()
    assert (streak["currentStreak"], streak["todayActive"]) == (1, True)

    other = (await register(client, app))["headers"]  # four answers, then the 5th and 6th at once
    first = await bank_test(client, other, fake_llm, {"chapter": "TSCI1-CH01", "count": 5})
    second = await bank_test(client, other, fake_llm, {"chapter": "TSCI1-CH02", "count": 5})
    first_test = await take(client, app, other, first, [True, True, True])
    second_test = await take(client, app, other, second, [False])
    both = await asyncio.gather(
        respond(client, other, first, first_test, 3, 0), respond(client, other, second, second_test, 1, 0)
    )
    assert [reply.status_code for reply in both] == [200, 200]
    assert sorted(json.dumps(reply.json()["learning"]) for reply in both) == [
        "null",
        '{"event": "started", "streak": 1}',
    ]


async def test_the_evidence_outlives_the_chat_and_goes_with_the_account(client, app, fake_llm, bank):
    account = await register(client, app)
    headers = account["headers"]
    message = await bank_test(client, headers, fake_llm, {"chapter": "TSCI1-CH01", "count": 2})
    await take(client, app, headers, message, [True, False])
    mastery = (await client.get("/v1/progress/mastery", headers=headers)).json()
    mistakes = (await client.get("/v1/progress/mistakes", headers=headers)).json()
    assert (
        mastery["answered"] == 2 and mistakes["concepts"][0]["items"][0]["conversationId"] == message["conversationId"]
    )

    assert (await client.delete(f"/v1/conversations/{message['conversationId']}", headers=headers)).status_code == 204
    assert (await client.get("/v1/progress/mastery", headers=headers)).json() == mastery
    after = (await client.get("/v1/progress/mistakes", headers=headers)).json()
    assert after["concepts"][0]["items"][0]["conversationId"] is None
    [taken] = (await client.get("/v1/progress/practice-tests", headers=headers)).json()["items"]
    assert (taken["conversationId"], taken["messageId"], taken["open"], taken["answered"]) == (None, None, False, 2)

    deleted = await client.request("DELETE", "/v1/me", json={"password": PASSWORD}, headers=headers)
    assert deleted.status_code == 204
    async with app.state.db.sessionmaker() as db:
        user = uuid.UUID(account["user"]["id"])
        for table in ("qb_sets", "qb_set_items"):
            assert await db.scalar(text(f"SELECT count(*) FROM {table} WHERE user_id = :u"), {"u": user}) == 0


async def test_the_practice_record_is_each_students_own_and_needs_a_session(client, app, fake_llm, bank):
    alice = (await register(client, app))["headers"]
    await take(
        client,
        app,
        alice,
        await bank_test(client, alice, fake_llm, {"chapter": "TSCI1-CH01", "count": 2}),
        [False, True],
    )
    bob = (await register(client, app))["headers"]
    for name in PRACTICE:
        assert (await client.get(f"/v1/progress/{name}")).status_code == 401, name
        mine = await client.get(f"/v1/progress/{name}", headers=alice)
        theirs = await client.get(f"/v1/progress/{name}", headers=bob)
        assert mine.status_code == theirs.status_code == 200, (name, mine.text, theirs.text)
    assert (await client.get("/v1/progress/mastery", headers=alice)).json()["answered"] == 2
    empty = {
        "mastery": ("subjects", []),
        "revisions": ("items", []),
        "mistakes": ("concepts", []),
        "practice-tests": ("items", []),
        "plan": ("tasks", []),
    }
    for name, (field, value) in empty.items():
        assert (await client.get(f"/v1/progress/{name}", headers=bob)).json()[field] == value, name


async def test_my_learning_reads_the_record_and_the_tutor_is_told_it(client, app, fake_llm, bank):
    headers = (await register(client, app))["headers"]
    exam = (learning_date(datetime.now(UTC)) + timedelta(days=20)).isoformat()  # the plan's India day
    profile = await client.patch(
        "/v1/learning/profile", json={"version": 0, "set": {"grade": "class_10", "examDate": exam}}, headers=headers
    )
    assert profile.status_code == 200 and profile.json()["examDate"] == exam, profile.text
    past = await client.patch(
        "/v1/learning/profile", json={"version": 1, "set": {"examDate": "2020-01-01"}}, headers=headers
    )
    assert past.status_code == 422
    subjects = await client.put(
        "/v1/learning/subjects", json={"version": 0, "items": [{"code": "science"}]}, headers=headers
    )
    assert subjects.status_code == 200, subjects.text
    message = await bank_test(client, headers, fake_llm, {"chapter": "TSCI1-CH01", "count": 3})
    await take(client, app, headers, message, [True, False, False])  # the 2nd and 3rd: one concept, both missed

    mastery = (await client.get("/v1/progress/mastery", headers=headers)).json()
    [science] = mastery["subjects"]
    assert (science["subjectCode"], science["chapters"][0]["chapterId"], mastery["answered"]) == (
        "science",
        "TSCI1-CH01",
        3,
    )
    assert science["coverage"] == 0.5 and mastery["model"]["masteredAt"] == 0.95  # 1 of the 2 chapters
    states = {
        concept["state"]
        for chapter in science["chapters"]
        for topic in chapter["topics"]
        for concept in topic["concepts"]
    }
    assert "weak" in states
    revisions = (await client.get("/v1/progress/revisions", headers=headers)).json()
    assert revisions["ladderDays"] == [1, 3, 7, 14, 30, 60] and {item["state"] for item in revisions["items"]} == {
        "upcoming"
    }
    [mistake] = (await client.get("/v1/progress/mistakes", headers=headers)).json()["concepts"]
    assert (mistake["wrong"], mistake["wrong14d"], mistake["recurring"], mistake["state"]) == (2, 2, True, "weak")
    assert all(item["chosen"] != item["correct"] and len(item["options"]) == 4 for item in mistake["items"])
    assert mistake["prompt"].startswith('Test me on Class 10 Science (Science EN) Chapter 1 "Chapter 1", topic ')
    plan = (await client.get("/v1/progress/plan", headers=headers)).json()
    assert (plan["needsProfile"], plan["daysToExam"], plan["answeredToday"], plan["answersForLearningDay"]) == (
        False,
        20,
        3,
        5,
    )
    assert [task["kind"] for task in plan["tasks"]] == ["learn"]  # all answers are today's; the exam is close
    topics = (await client.get("/v1/progress/practice-topics", headers=headers)).json()
    assert (topics["available"], topics["classLevel"], topics["language"]) == (True, 10, "english")
    chapters = topics["subjects"][0]["books"][0]["chapters"]
    assert [(chapter["chapterId"], chapter["questions"]) for chapter in chapters] == [
        ("TSCI1-CH01", 18),
        ("TSCI1-CH02", 18),
    ]

    fake_llm.reply = lambda messages: "Here is how you are doing."
    await stream_chat(client, headers, "How am I doing in science?", message["conversationId"])
    system = fake_llm.calls[-1][0].content
    assert "- Practice record (the app's question bank; estimates, not marks): weakest " in system
    assert "today 3 of the 5 answers that make a learning day" in system

    async with app.state.db.sessionmaker() as db:  # the first question is edited after it was served
        await db.execute(
            text(
                "UPDATE qb_questions SET review_status = 'needs_review', content_hash = md5(stem) || md5(question_id) "
                "WHERE question_id = (SELECT question_id FROM qb_set_items WHERE position = 1)"
            )
        )
        await db.commit()
    edited = (await client.get("/v1/progress/mastery", headers=headers)).json()
    assert (edited["answered"], edited["revisedAnswers"]) == (2, 1)  # its answer is set aside


async def test_a_mock_test_spans_chapters_and_the_kill_switch_sets_every_question_at_once(
    client, app, fake_llm, bank, monkeypatch
):
    headers = (await register(client, app))["headers"]
    mock = await bank_test(client, headers, fake_llm, {"chapters": ["TSCI1-CH01", "TSCI1-CH02"], "count": 30})
    [test] = mock["metadata"]["assessments"]
    assert (test["total"], len(test["questions"])) == (30, 1) and "1. Chapter 1 · 2. Chapter 2" in test["title"]
    too_many = await bank_test(client, headers, fake_llm, {"chapters": ["TSCI1-CH01", "TSCI1-CH02"], "count": 40})
    assert too_many["metadata"]["assessments"][0]["total"] == 30  # at most 30

    monkeypatch.setattr(app.state.settings, "adaptive_chat_tests", False)
    fixed = await bank_test(client, headers, fake_llm, {"chapter": "TSCI1-CH01", "count": 5})
    [test] = fixed["metadata"]["assessments"]
    assert (test["total"], len(test["questions"])) == (5, 5)
    assert [row["position"] for row in await ledger(app, fixed)] == [1, 2, 3, 4, 5]  # all served at once
    finished = await take(client, app, headers, fixed, [True] * 5)
    assert (finished["state"], len(finished["questions"]), finished["earned"]) == ("completed", 5, 5)
    assert all(row["chosen"] is not None and row["closed"] for row in await ledger(app, fixed))


async def test_the_tutor_may_write_a_fill_in_the_blanks_exercise_which_is_never_evidence(client, app, fake_llm):
    headers = (await register(client, app))["headers"]
    exercise = {
        "text": "Water boils at [[100|hundred]] °C and freezes at [[0|zero]] °C.",
        "explanation": "At sea level.",
    }
    fake_llm.reply = lambda messages: "Fill these in.\n\n```fill-blank\n" + json.dumps(exercise) + "\n```"
    response, events = await stream_chat(client, headers, "Give me a fill in the blanks on water")
    assert response.status_code == 200 and events[-1][0] == "done", response.text
    message = events[-1][1]["message"]
    assert "```fill-blank" in message["content"]  # kept, no longer replaced by a note
    [record] = message["metadata"]["assessments"]
    checked = await client.post(
        f"/v1/messages/{message['id']}/assessment-responses",
        json={"position": 0, "hash": record["hash"], "question": 0, "action": "answer", "value": ["100", "ice"]},
        headers=headers,
    )
    assert checked.status_code == 200 and (checked.json()["earned"], checked.json()["learning"]) == (1, None)
    assert (await client.get("/v1/progress/mastery", headers=headers)).json()["answered"] == 0
    async with app.state.db.sessionmaker() as db:
        assert await db.scalar(text("SELECT count(*) FROM qb_sets")) == 0
    for malformed in ("Water boils at [[100|]] °C.", "Water boils at [[" + "1" * 81 + "]] °C and freezes at [[0]] °C."):
        block = "```fill-blank\n" + json.dumps({"text": malformed}) + "\n```"
        assert assessments.build(block, None) == (None, "invalid_question")  # the tutor's key: refused whole
    # Written as a ::: card, the study cards' form (seen live): put in its fence, so the student gets the
    # exercise and not its answer key.
    fake_llm.reply = lambda messages: ":::fill-blank\n" + json.dumps(exercise, indent=2) + "\n:::"
    response, events = await stream_chat(client, headers, "Another fill in the blanks on water, please")
    message = events[-1][1]["message"]
    assert message["content"] == "```fill-blank\n" + json.dumps(exercise, indent=2) + "\n```"
    assert message["metadata"]["assessments"][0]["kind"] == "exercise"
