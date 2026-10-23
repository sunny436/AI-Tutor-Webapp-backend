"""The intent router (app/intents): the owner's 46 intents read in two short requests (the group, then
the intent within it), a reading used only when every field checks out, an explicit "hint only" before
any reading, fast failure without the key in a log, and the chat: an applied intent changes the
prompt, anything else leaves the tutor as it was (shadow included)."""

import asyncio
import json
import logging
import math
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx

from app.auth.emails import MemoryEmailSender
from app.chat.assistant import BANK_BLOCKS, SYSTEM_PROMPT, intent_block
from app.db.models import Message
from app.intents.classifier import QUESTIONS, IntentClassifier, explicit_hint_only, score, text_for
from app.intents.taxonomy import BANK_INTENTS, GROUP_MEMBERS, GROUPS, INTENTS, TAXONOMY_VERSION
from app.llm.base import ChatMessage
from app.llm.fake import FakeProvider
from app.main import create_app
from app.progress import activity
from tests.conftest import make_settings, parse_sse, register, stream_chat

KEY = "sk_test_0123456789abcdefghijklmnopqrstuvwxyz"
IDS = (
    "explain_concept define_term why_how real_life_application analogy_example prerequisite_learning deeper_learning "
    "misconception_check solve_numerical solve_equation step_by_step_solution textbook_exercise homework_help "
    "hint_only check_answer debug_solution alternative_method word_problem textbook_lookup chapter_summary "
    "revision_notes key_points formula_sheet flashcards mind_map translation simplify_text answer_formatting "
    "generate_mcq conduct_quiz mock_test exam_prep important_topics marking_rubric evaluate_written_answer "
    "difficulty_adjustment performance_analysis study_schedule diagram_explanation diagram_labeling "
    "graph_interpretation image_question_solving experiment_procedure observation_inference lab_safety "
    "project_assignment"
).split()


def choice(options: list[str], chosen: str, p: float) -> dict:
    rest = (1 - p) / (len(options) - 1)
    probabilities = {option: p if option == chosen else rest for option in options}
    return {"type": "choice", "answer": chosen, "confidence": p, "probabilities": probabilities}


def answer(question: str, best: str | None, p: float = 0.9) -> dict:
    """Ollalink's response to one question about a message read as `best` (None: "other"), which gets p:
    the group question chooses its group, and its group's own question chooses it."""
    if question == "group":
        options, chosen = list(GROUPS), INTENTS[best].group if best else "other"
    else:
        options = list(GROUP_MEMBERS[question])
        chosen = best if best in options else options[0]
    return {"answers": {question: choice(options, chosen, p)}, "characters": 40}


def reading(best: str | None, p: float = 0.9):
    """A classify endpoint that reads every message as `best`, whichever question it is asked."""

    def handler(request: httpx.Request) -> httpx.Response:
        (question,) = json.loads(request.content)["questions"]
        return httpx.Response(200, json=answer(question, best, p))

    return handler


def classifier(handler, timeout_s: float = 1.0) -> IntentClassifier:
    return IntentClassifier(
        "https://ai.ollalink.test", KEY, timeout_s, 0.5, 0.5, transport=httpx.MockTransport(handler)
    )


@asynccontextmanager
async def chat_app(llm, mode: str, handler):
    """The app with the router in `mode` and a classifier answering through `handler`; tests come from the
    question bank, so a test intent's chapters show in the prompt."""
    settings = make_settings(intent_router=mode, question_bank_tests=True, tutor_interactive_blocks=True)
    application = create_app(settings, llm=llm, email_sender=MemoryEmailSender(), intents=classifier(handler))
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://t") as client:
            yield application, client


async def stored(app, message_id) -> dict:
    async with app.state.db.sessionmaker() as session:
        return (await session.get(Message, message_id)).metadata_


def test_the_owners_46_intents_in_eight_groups_and_what_is_sent_stays_short():
    assert TAXONOMY_VERSION == "2026-10-22"
    assert list(INTENTS) == IDS and len(IDS) == 46  # the owner's order, which also breaks ties
    assert sorted(name for members in GROUP_MEMBERS.values() for name in members) == sorted(IDS)
    assert list(GROUPS) == [
        "understand",
        "solve",
        "feedback",
        "materials",
        "language",
        "tests",
        "planning",
        "visual_lab",
        "other",
    ]
    assert [len(members) for members in GROUP_MEMBERS.values()] == [8, 7, 5, 7, 3, 6, 2, 8]
    assert "other" not in INTENTS and "follow_up" not in INTENTS  # an abstain option and a context rule only
    assert list(QUESTIONS) == ["group", *GROUP_MEMBERS]  # one per request: the group's, then the group's own
    assert all(2 <= len(question["options"]) <= 10 for question in QUESTIONS.values())
    assert all(question["question"].endswith("earlier lines are context only.") for question in QUESTIONS.values())
    # Every option sent is a short fixed text (each one costs time); the owner's criteria never are.
    sent = [text for question in QUESTIONS.values() for text in question["options"].values()]
    assert len(sent) == 55 and all(0 < len(text) <= 80 for text in sent)
    assert all(intent.option in sent and intent.criterion not in sent for intent in INTENTS.values())
    assert all("Example:" in intent.criterion and len(intent.guidance) <= 450 for intent in INTENTS.values())
    assert BANK_INTENTS == {"generate_mcq", "conduct_quiz", "mock_test", "difficulty_adjustment"}
    unsearched = {name for name, intent in INTENTS.items() if not intent.retrieval}
    assert unsearched == {"performance_analysis", "study_schedule"}  # answered from the app's own records
    # The text: context only for a short follow-up, and never more than about 1,100 characters.
    earlier, kinds = [ChatMessage("user", "p" * 3000), ChatMessage("assistant", "r" * 3000)], ("image", "pdf", "txt")
    follow_up = text_for([*earlier, ChatMessage("user", "why " + "z" * 196)], kinds)
    pasted = text_for([*earlier, ChatMessage("user", "z" * 3000)], kinds)  # one word, but no follow-up
    assert "Previous message (context only)" in follow_up and "context only" not in pasted
    assert max(len(follow_up), len(pasted)) <= 1_100


def test_a_reading_is_used_only_when_every_field_checks_out():
    group, understand = answer("group", "define_term"), answer("understand", "define_term")
    scored = score(group, understand)
    assert (scored.group, scored.best) == ("understand", "define_term")
    assert (round(scored.group_confidence, 2), round(scored.confidence, 2)) == (0.9, 0.81)
    assert scored.decide(0.5, 0.5) == ("define_term", None)
    assert scored.decide(0.85, 0.5) == (None, "low_confidence")  # the score, 0.81
    assert scored.decide(0.5, 0.95) == (None, "low_confidence")  # P(group), 0.9
    assert score(group).decide(0.0, 0.0) == (None, "low_confidence")  # its group's question not answered
    other = score(answer("group", None), understand)  # `other` has no question of its own
    assert (other.group, other.best, other.decide(0.0, 0.0)) == ("other", None, (None, "other"))
    tied = answer("understand", "define_term", 0.5)
    tied["answers"]["understand"]["probabilities"] = {
        name: 0.5 if name in ("explain_concept", "define_term") else 0.0 for name in GROUP_MEMBERS["understand"]
    }
    assert score(group, tied).best == "explain_concept"  # equal scores: the owner's order
    assert score(group, answer("solve", "solve_numerical")) is None  # not the chosen group's question

    def broken(question: str, change) -> dict:
        payload = answer(question, "define_term")
        change(payload["answers"])
        return payload

    for question, change in (
        ("group", lambda answers: answers.pop("group")),  # the question missing
        ("group", lambda answers: answers.update(solve=answers["group"])),  # an id never asked
        ("group", lambda answers: answers["group"].update(type="text")),
        ("understand", lambda answers: answers["understand"].update(answer="solve_numerical")),  # not sent
        ("understand", lambda answers: answers["understand"]["probabilities"].update(solve_numerical=0.1)),
        ("understand", lambda answers: answers["understand"]["probabilities"].pop("why_how")),
        ("group", lambda answers: answers["group"]["probabilities"].update(solve=math.nan)),
        ("group", lambda answers: answers["group"]["probabilities"].update(solve=-0.1)),
        ("group", lambda answers: answers["group"]["probabilities"].update(solve=math.inf)),
        ("group", lambda answers: answers["group"].update(probabilities=dict.fromkeys(GROUPS, 0.0))),
        ("understand", lambda answers: answers["understand"].update(confidence=None)),
    ):
        payloads = {"group": group, "understand": understand}
        payloads[question] = broken(question, change)
        assert score(payloads["group"], payloads["understand"]) is None  # bad_response: none of it is used
    assert score({"characters": 40}) is None and score(["answers"]) is None


def test_an_explicit_request_for_a_hint_only_is_read_in_english_hindi_and_hinglish():
    for text in (
        "hint only",
        "Just give me a hint for Q2",
        "Don't tell me the answer, I want to try",
        "dont show the solution yet",
        "without telling me the answer, help me start",
        "Answer mat batana, bas hint do.",
        "sirf hint do",
        "ek hint do na",
        "उत्तर मत बताना",
        "जवाब मत बताओ, बस हिंट दो",
        "सिर्फ़ संकेत दो",
        "सिर्" + chr(0x095E) + " संकेत दो",  # फ़ as one code point
        "Give me only the next step, not the full solution",  # only the next step: a hint by another name
        "just tell me the first step please",
        "bas pehla step bata do",
        "बस पहला चरण बताओ",
        "I want to do it myself, just tell me how to start",  # solve it myself + how to begin
        "Main khud solve karna chahta hoon, bas shuruaat batao",
        "मैं खुद हल करूँगा, बस पहला कदम बताओ",
        "No complete solution, just a nudge please",
    ):
        assert explicit_hint_only(text), text
    for text in (
        "I don't need a hint, just tell me the answer",
        "Give me the answer, not a hint",
        "hint nahi chahiye, answer batao",
        "संकेत नहीं चाहिए, उत्तर बताओ",
        "Give me a hint and then the full solution",
        "Give me a hint, then the full solution",
        "Don't give the answer in points, write a paragraph",  # a format, not a hint
        "What is a hint in a crossword?",
        "Solve 2x + 5 = 15",
        "Hints do not help me, give me the full solution",
        "Do not give hints only, solve it fully",
        "Which hint do I use for this crossword?",  # English "hint do", not Hinglish
        "Quiz me on light, don't show the answer until the end",  # an answer later, not a hint
        "Not just a hint, I want the whole solution",
        "Only the first step is hard, explain the whole thing",
        "What is the next step in the water cycle?",
        "sirf pehla step mushkil hai, poora samjhao",
        "I don't want to solve it myself, just give me the answer",
        "Give me the full solution and the first step",
        "How do I start this essay?",  # how to begin, without wanting to solve it themselves
        "I solved it myself, is my first step right?",
    ):
        assert not explicit_hint_only(text), text


async def test_two_short_requests_fail_fast_and_the_key_never_reaches_a_log(caplog):
    caplog.set_level(logging.DEBUG, logger="app.intents")
    calls = []
    question = [ChatMessage("user", "What is osmosis?")]

    def counted(handler):
        def record(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return handler(request)

        return classifier(record)

    # The group question, then only the chosen group's own: one question per request.
    ok = counted(reading("define_term"))
    assert (await ok.classify(question)).intent == "define_term"
    assert [json.loads(request.content) for request in calls] == [
        {"text": "Current message: What is osmosis?", "questions": {"group": QUESTIONS["group"]}},
        {"text": "Current message: What is osmosis?", "questions": {"understand": QUESTIONS["understand"]}},
    ]
    for request in calls:
        assert str(request.url) == "https://ai.ollalink.test/v1/classify"
        assert request.headers["X-NH-GPU-Key"] == KEY and "authorization" not in request.headers
    await ok.aclose()

    # No second request for `other`, or for a group below INTENT_MIN_GROUP_CONFIDENCE (0.5 here).
    for best, p, reason in ((None, 0.9, "other"), ("define_term", 0.4, "low_confidence")):
        calls.clear()
        unsure = counted(reading(best, p))
        routed = await unsure.classify(question)
        assert (routed.intent, routed.best, routed.reason, len(calls)) == (None, None, reason, 1)
        await unsure.aclose()

    def timeout(request):
        raise httpx.ReadTimeout(f"no answer for {KEY}")

    calls.clear()
    slow = counted(timeout)
    reasons = [(await slow.classify(question)).reason for _ in range(4)]
    assert reasons == ["timeout", "timeout", "timeout", "paused"] and len(calls) == 3  # no 4th request
    await slow.aclose()

    # A failure in the second request is no intent: never a guess from the group alone.
    def second_times_out(request: httpx.Request) -> httpx.Response:
        if "group" not in json.loads(request.content)["questions"]:
            raise httpx.ReadTimeout("no answer")
        return httpx.Response(200, json=answer("group", "define_term"))

    calls.clear()
    half = counted(second_times_out)
    routed = await half.classify(question)
    assert (routed.intent, routed.best, routed.reason, len(calls)) == (None, None, "timeout", 2)
    await half.aclose()

    for status, headers, reason, pause_s in (
        (403, {}, "unauthorized", 600),
        (429, {"Retry-After": "7"}, "rate_limited", 7),
        (429, {}, "rate_limited", 30),
    ):
        calls.clear()
        refused = counted(
            lambda request, status=status, headers=headers: httpx.Response(
                status, headers=headers, json={"error": {"code": "not_approved", "message": f"bad key {KEY}"}}
            )
        )
        assert [(await refused.classify(question)).reason for _ in range(2)] == [reason, "paused"]
        assert len(calls) == 1
        paused = [record.pause_s for record in caplog.records if record.getMessage() == "intent classifier paused"]
        assert paused[-1] == pause_s
        await refused.aclose()

    calls.clear()
    busy = counted(lambda request: httpx.Response(503, json={"error": {"code": "classification_unavailable"}}))
    assert [(await busy.classify(question)).reason for _ in range(4)] == ["unavailable"] * 4
    assert len(calls) == 4  # a busy or loading model is a fast failure: never paused
    await busy.aclose()

    sleepy_calls = []

    async def sleepy(request):
        sleepy_calls.append(request)
        await asyncio.sleep(0.15)
        (asked,) = json.loads(request.content)["questions"]
        return httpx.Response(200, json=answer(asked, "define_term"))

    sleeper = classifier(sleepy, timeout_s=0.25)  # each request in time, the two together not
    assert (await sleeper.classify(question)).reason == "timeout" and len(sleepy_calls) == 2  # one cap for both
    await sleeper.aclose()

    standard = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}
    blob = " ".join(
        f"{r.getMessage()} { {k: v for k, v in r.__dict__.items() if k not in standard} } {r.exc_text or ''}"
        for r in caplog.records
    )
    assert "intent classified" in blob and "intent classifier key unknown" in blob
    assert KEY not in blob and "osmosis" not in blob.lower()  # metadata only


async def test_the_chat_applies_an_intent_and_otherwise_stays_the_tutor_as_before(fake_llm):
    texts, now = [], {"best": "define_term", "status": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        texts.append(body["text"])
        if now["status"] != 200:
            return httpx.Response(now["status"])
        (question,) = body["questions"]
        return httpx.Response(200, json=answer(question, now["best"]))

    base = f"{SYSTEM_PROMPT}\n\n{BANK_BLOCKS}"  # what this student's tutor is told with no intent
    async with chat_app(fake_llm, "on", handler) as (app, client):
        headers = (await register(client, app))["headers"]
        _, events = await stream_chat(client, headers, "What is osmosis?")
        conversation_id, done = events[0][1]["conversationId"], events[-1][1]["message"]
        assert texts == ["Current message: What is osmosis?"] * 2  # the group, then the group's own question
        assert fake_llm.calls[-1][0].content == f"{base}\n\n{intent_block('define_term')}"
        assert "intent" not in done["metadata"]  # internal only
        recorded = (await stored(app, done["id"]))["intent"]
        assert {key: recorded[key] for key in ("id", "applied", "forced", "source", "bankMenu", "version")} == {
            "id": "define_term",
            "applied": True,
            "forced": False,
            "source": "classifier",
            "bankMenu": "none",
            "version": TAXONOMY_VERSION,
        }
        assert (recorded["groupConfidence"], recorded["confidence"]) == (0.9, 0.81)

        # A regenerated reply keeps its intent, with no new call.
        regenerated = await client.post(f"/v1/conversations/{conversation_id}/regenerate/stream", headers=headers)
        again = parse_sse(regenerated.text)[-1][1]["message"]
        assert len(texts) == 2 and intent_block("define_term") in fake_llm.calls[-1][0].content
        assert (await stored(app, again["id"]))["intent"]["source"] == "regenerate"

        # A test intent gets the bank's chapters although the words ask for no test; a short message is
        # read with the one before it and the end of the reply, labelled context only.
        now["best"] = "conduct_quiz"
        _, events = await stream_chat(client, headers, "Check what I remember about light", conversation_id)
        context = (
            "Previous message (context only): What is osmosis?\n"
            "Tutor's reply, end (context only): You said: What is osmosis?\n"
            "Current message: Check what I remember about light"
        )
        assert texts[-2:] == [context] * 2
        system = fake_llm.calls[-1][0].content
        assert intent_block("conduct_quiz") in system and "Question bank: it has tests for Classes 6-12" in system
        assert (await stored(app, events[-1][1]["message"]["id"]))["intent"]["bankMenu"] == "forced"

        # A planning intent is answered from the app's records: no knowledge search.
        now["best"] = "study_schedule"
        _, events = await stream_chat(client, headers, "Plan my next seven days of study please", conversation_id)
        assert (await stored(app, events[-1][1]["message"]["id"]))["retrieval"]["reason"] == "not_requested"

        # The classifier failing: exactly the prompt without the router. An explicit "hint only" still
        # applies, without asking the classifier.
        now["status"] = 503
        other = (await register(client, app))["headers"]
        _, events = await stream_chat(client, other, "Explain refraction of light in detail")
        assert fake_llm.calls[-1][0].content == base
        failed = (await stored(app, events[-1][1]["message"]["id"]))["intent"]
        assert (failed["id"], failed["applied"], failed["reason"]) == (None, False, "unavailable")
        asked, conversation_id = len(texts), events[0][1]["conversationId"]
        _, events = await stream_chat(client, other, "Answer mat batana, bas hint do", conversation_id)
        assert len(texts) == asked and intent_block("hint_only") in fake_llm.calls[-1][0].content
        forced = (await stored(app, events[-1][1]["message"]["id"]))["intent"]
        assert (forced["id"], forced["forced"], forced["source"]) == ("hint_only", True, "explicit")
        await client.post(f"/v1/conversations/{conversation_id}/regenerate/stream", headers=other)
        assert len(texts) == asked and intent_block("hint_only") in fake_llm.calls[-1][0].content  # again


async def test_shadow_mode_records_the_reading_and_changes_nothing(monkeypatch):
    # 11:30 India time, so the "Learning so far" line is the same in both runs.
    monkeypatch.setattr(activity, "utcnow", lambda: datetime(2026, 9, 26, 6, 0, tzinfo=UTC))
    messages = ("Check what I remember about light", "Plan my next seven days of study please", "just give me a hint")
    readings = dict(zip(messages[:2], ("conduct_quiz", "study_schedule"), strict=True))

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        (question,) = body["questions"]
        return httpx.Response(200, json=answer(question, readings[body["text"].removeprefix("Current message: ")]))

    seen = {}
    for mode in ("off", "shadow"):
        llm = FakeProvider()
        async with chat_app(llm, mode, handler) as (app, client):
            headers = (await register(client, app))["headers"]
            conversation_id, rows = None, []
            for text in messages:
                _, events = await stream_chat(client, headers, text, conversation_id)
                conversation_id = events[0][1]["conversationId"]
                rows.append(await stored(app, events[-1][1]["message"]["id"]))
        seen[mode] = (
            [call[0].content for call in llm.calls],  # the prompts: no guidance, no bank chapters
            [row["retrieval"]["reason"] for row in rows],  # the searches
            [row.get("intent") for row in rows],
        )
    assert seen["shadow"][:2] == seen["off"][:2]
    assert seen["off"][1] == ["empty_knowledge_base"] * 3 and seen["off"][2][:2] == [None] * 2
    # An explicit "hint only" is a fixed rule, not a reading: applied in every mode, the router off too.
    assert intent_block("hint_only") in seen["off"][0][2] and intent_block("hint_only") not in seen["off"][0][1]
    for mode in ("off", "shadow"):
        hint = seen[mode][2][2]
        assert (hint["id"], hint["forced"], hint["applied"], hint["source"]) == ("hint_only", True, True, "explicit")
    quiz, plan, _ = seen["shadow"][2]
    assert (quiz["id"], quiz["best"], quiz["applied"], quiz["bankMenu"]) == (None, "conduct_quiz", False, "none")
    assert (plan["id"], plan["best"], plan["applied"]) == (None, "study_schedule", False)


async def test_a_quiet_classifier_is_warmed_once_by_a_signed_in_request():
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(503) if len(sent) == 3 else httpx.Response(200, json={"answers": {}})

    def warm(after: float) -> IntentClassifier:
        return IntentClassifier(
            "https://ai.ollalink.test", KEY, 1.0, 0.5, 0.5, transport=httpx.MockTransport(handler), warm_after_s=after
        )

    found = warm(60)
    found.nudge()
    found.nudge()  # one warm-up, however many requests arrive
    await found._warming
    assert len(sent) == 1 and sent[0]["text"] == "Current message: hello" and list(sent[0]["questions"]) == ["scope"]
    found.nudge()  # just warmed: nothing
    assert len(sent) == 1
    found._used -= 61  # a quiet minute later: once more
    found.nudge()
    await found._warming
    assert len(sent) == 2
    found._used -= 61
    found.nudge()  # a failed warm-up (503) is only logged: no retry, nothing raised
    await found._warming
    assert len(sent) == 3
    found._used -= 61
    found._paused_until = time.monotonic() + 30  # paused after failures: no warm-up
    found.nudge()
    assert len(sent) == 3
    off = warm(0)  # 0: never
    off.nudge()
    assert off._warming is None and len(sent) == 3
    await found.aclose()
    await off.aclose()
