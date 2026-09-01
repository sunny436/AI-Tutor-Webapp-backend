"""
"Just tell me" must end the intake, and the plan must not blame a prescription.

Two defects found in the same live turn, in the browser, on 2026-09-01.

ONE — the questions would not stop. Someone typed "poora plan batao" after
three rounds about acidity and was asked two more questions, which were the
SAME two the previous turn had already asked (sleep, bowels):

    User: "Mujhe acidity ho rahi hai."
    You:  "...kab se ho rahi hai...?"
    User: "2 hafte se hai. Khaane ke baad jalan..."
    You:  "...neend kaisi rehti hai... koi medical condition...?"
    User: "Main 32 saal ka hoon. Sugar hai, metformin leta hoon."
    You:  "...raat mein sone mein dikkat... stress level...?"
    User: "poora plan batao"
    You:  "...raat mein sone mein dikkat... stress level...?"    <-- again

GATHERING_PROMPT already carried the rule ("true - they ask you to just give
the advice") and the model did not follow it, so it is settled in code now:
`router.asks_for_guidance_now` + the branch in `graph.run_turn`.

TWO — the plan that finally arrived told a diabetic that their metformin was
causing the acidity. Rule 2 forbade telling anyone to STOP a prescribed drug
and said nothing about blaming one, which is the sentence that actually makes
somebody stop it. Fixed in `prompts.PERSONA_CORE` rule 2 and detected by
`safety.blames_medicine`.

Sections 1-2 are DETERMINISTIC. Section 3 is live and needs Ollima.

    python tests/test_guidance_request.py
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

# Devanagari appears in the test NAMES here, and on Windows a redirected stdout
# defaults to cp1252 — which turns a passing assertion into a UnicodeEncodeError
# from inside `print`. Same reconfigure `server.py` applies, for the same reason.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from src import safety  # noqa: E402
from src.consult import graph, run_turn  # noqa: E402
from src.consult.gathering import Gathered  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


# ===========================================================================
# 1. asks_for_guidance_now — the closed set, decided without a model.
# ===========================================================================
ASKS = [
    # the exact phrasings section 13 of the QA brief names
    "poora plan batao",
    "sirf yoga batao",
    "root cause batao",
    "sirf diet batao",
    "root cause aur yoga dono batao",
    # and the rest of how people really type it
    "plan bata do",
    "pura plan bata dijiye",
    "complete plan batao",
    "koi gharelu upay bata do",
    "ilaj batao",
    "mujhe remedies batao",
    "upay bataiye",
    "yoga bata do",
    "diet ke baare me bata dijiye",
    "sab kuch batao",
    "just tell me the plan",
    "give me the plan",
    "tell me some remedies",
    "what should i do",
    "kya karna chahiye",
    "no more questions, just tell me",
    "stop asking and give me the plan",
    "aur sawal mat pucho",
    "bas ab batao",
    "seedha batao",
    # "That's all I have, you tell me" — the intake-ending phrase this repo's
    # own test_intake.py has always used as filler. Seen live answering with
    # the SAME two questions the previous turn had already asked.
    "bas itna hi hai, aap bata dijiye",
    "bas itna hi hai",
    "itna hi hai",
    "aap batao",
    "aap hi bata dijiye",
    "mujhe nahi pata, aap batao",
    "that's all",
    "nothing else",
    "aur kuch nahi hai",
    "पूरा प्लान बताओ",
    "उपाय बताइए",
    "योग बताओ",
    "और सवाल मत पूछो",
]
for _text in ASKS:
    check(
        f"asks for guidance: {_text!r}",
        graph.asks_for_guidance_now(_text),
    )

# THE NEGATIVES CARRY MORE WEIGHT THAN THE POSITIVES. A false positive here
# ends the intake early and hands somebody a plan built from one sentence, so
# ordinary answers to gathering questions must all read as answers.
NOT_ASKS = [
    "2 hafte se hai",
    "khaane ke baad jalan hoti hai",
    "main 32 saal ka hoon, sugar hai, metformin leta hoon",
    "raat ko der se khana khata hoon",
    "pet subah saaf ho jata hai",
    "spicy khane se badh jata hai",
    "kabhi kabhi hota hai",
    "haan",
    "nahi",
    "pata nahi",
    "theek hai",
    "mujhe nahi pata",
    "mujhe acidity ho rahi hai",
    "mujhe cancer ho gaya hai",
    "blood cancer hai",
    "AML hai, chemotherapy chal rahi hai",
    "chest me dard ho raha hai",
    "main vomit kar raha hoon 5 baar se zyada",
    "hi",
    "thanks",
    # Real answers to real gathering questions. These are the ones a loose
    # pattern would swallow, ending the intake on the user's first reply.
    "din me 3 baar khana khata hoon",
    "subah 8 baje nashta karta hoon",
    "kabz 1 mahine se hai",
    "haan thoda stress rehta hai",
    "pani kam peeta hoon",
]
for _text in NOT_ASKS:
    check(
        f"is NOT a request for guidance: {_text!r}",
        not graph.asks_for_guidance_now(_text),
    )


# ===========================================================================
# 2. The branch in run_turn — `gather` stubbed, so this pins the WIRING
#    rather than the model's mood.
# ===========================================================================
def _install_gather_stub(ready: bool, reply: str = "Aur bataiye?"):
    """Replace `graph.gather` with one that returns a fixed verdict."""
    calls: list[dict] = []

    async def stub(**kwargs):
        calls.append(kwargs)
        return Gathered(
            reply=reply,
            condition="acidity",
            symptoms=["acidity"],
            ready=ready,
        )

    graph.gather = stub  # type: ignore[assignment]
    return calls


def _install_focus_stub(value):
    seen: list[str] = []

    async def stub(reply, language=""):
        seen.append(reply)
        return list(value)

    graph.classify_focus = stub  # type: ignore[assignment]
    return seen


_real_gather = graph.gather
_real_focus = graph.classify_focus
_real_plan = graph.write_plan
_real_retrieve = graph._retrieve


async def _no_retrieval(context, principal, conversation_id):
    class _Pipeline:
        def to_sources(self, results):
            return []

        def to_prompt_block(self, results):
            return ""

    return _Pipeline(), []


async def _fake_plan(**kwargs):
    return "**Root Cause**\nstub plan\n\n**When To See A Doctor**\nstub"


async def _run(typed, phase="gathering", rounds=2):
    context = {
        "problem": "acidity",
        "phase": phase,
        "round": rounds,
        "condition": "acidity",
        "language": "hinglish",
        "greeted": True,
        "profile_loaded": True,
        "chat_history": [
            {"role": "user", "text": "mujhe acidity ho rahi hai"},
            {"role": "assistant", "text": "kab se ho rahi hai?"},
            {"role": "user", "text": "2 hafte se"},
            {"role": "assistant", "text": "neend kaisi rehti hai?"},
        ],
    }
    return await run_turn(
        problem="",
        raw_context=context,
        answers=None,
        free_text=typed,
        profile="",
        principal={"user_id": "test-guidance"},
    )


async def _section_2():
    graph._retrieve = _no_retrieval  # type: ignore[assignment]
    graph.write_plan = _fake_plan  # type: ignore[assignment]

    # (a) The model says "keep asking" and the user says "just tell me".
    #     The user wins.
    _install_gather_stub(ready=False, reply="Aur ek sawaal — neend kaisi hai?")
    focus_seen = _install_focus_stub(["complete"])
    result = await _run("poora plan batao")
    check(
        "an outright request beats the model's 'not ready'",
        result.kind == "answer",
        f"kind={result.kind} answer={(result.answer or '')[:60]!r}",
    )
    check(
        "the intake question is NOT what comes back",
        "sawaal" not in (result.answer or "").lower(),
        (result.answer or "")[:80],
    )
    check(
        "the focus was read from that same message, not asked back",
        focus_seen == ["poora plan batao"],
        str(focus_seen),
    )
    check(
        "and the focus question is not appended either",
        "kya jaanna chahenge" not in (result.answer or "").lower(),
        (result.answer or "")[:80],
    )

    # (b) A named focus is honoured, not widened to the whole plan.
    _install_gather_stub(ready=False)
    _install_focus_stub(["yoga"])
    result = await _run("sirf yoga batao")
    check(
        "'sirf yoga batao' ends the intake too",
        result.kind == "answer",
        result.kind,
    )
    check(
        "'sirf yoga batao' records yoga as the focus",
        result.context.help_types == ["yoga"],
        str(result.context.help_types),
    )

    # (c) Nothing in particular named -> the complete plan, NOT one more
    #     question. Somebody who just said "no more questions" must not be
    #     answered with the focus question.
    _install_gather_stub(ready=False)
    _install_focus_stub([])
    result = await _run("bas ab batao")
    check(
        "a bare refusal to answer more falls back to the complete plan",
        result.kind == "answer" and result.context.help_types == ["complete"],
        f"kind={result.kind} focus={result.context.help_types}",
    )

    # (d) AN ORDINARY ANSWER STILL GATHERS. The whole risk of this change is
    #     ending intakes that should have continued.
    _install_gather_stub(ready=False, reply="Aur bataiye, neend kaisi hai?")
    _install_focus_stub(["complete"])
    result = await _run("raat ko der se khana khata hoon")
    check(
        "an ordinary answer does NOT end the intake",
        result.kind == "chat" and result.context.phase == "gathering",
        f"kind={result.kind} phase={result.context.phase}",
    )

    # (e) SAFETY IS STILL ABOVE THIS. A red flag in the same sentence that
    #     asks for a remedy must escalate, not produce a plan.
    _install_gather_stub(ready=False)
    _install_focus_stub(["complete"])
    result = await _run("ulti me khoon aa raha hai, koi gharelu upay bata do")
    check(
        "a red flag in the same sentence escalates instead of planning",
        result.kind != "answer" and result.context.risk_level == "urgent",
        f"kind={result.kind} risk={result.context.risk_level}",
    )

    graph.gather = _real_gather  # type: ignore[assignment]
    graph.classify_focus = _real_focus  # type: ignore[assignment]
    graph.write_plan = _real_plan  # type: ignore[assignment]
    graph._retrieve = _real_retrieve  # type: ignore[assignment]


asyncio.run(_section_2())


# ===========================================================================
# 3. safety.blames_medicine — deterministic, no model.
# ===========================================================================
BLAMES = [
    # the sentence that actually reached a user
    "Metformin lene ke baad digestion mein badlav aana aur acidity mehsoos "
    "hona ek common baat ho sakti hai.",
    "Aapke case mein, metformin ka sevan is acidity aur jalan ka karan ho sakta hai.",
    "Your acidity may be caused by the omeprazole you are taking.",
    "Ye jalan aapki tablet ki wajah se ho sakti hai.",
    "This is a common side effect of metformin.",
    "Acidity started after taking metformin, which is common.",
]
for _text in BLAMES:
    check(f"blame is caught: {_text[:52]!r}", bool(safety.blames_medicine(_text)))

# Mentioning the medicine is fine and necessary — it is what makes the advice
# safe. Only blaming it is not.
CLEAN = [
    "Aap metformin le rahe hain, isliye main koi bhi suggestion dete waqt uska "
    "dhyan rakhunga.",
    "Agar aapko lagta hai ki takleef badhi hai to apne doctor ko zaroor bataiyega.",
    "Khali pet chai peene ki wajah se pitta badhta hai aur jalan hoti hai.",
    "Aap metformin le rahe hain. Khane ke baad 10 minute ki slow walk karein.",
    "Khane ke baad turant letna band karein aur raat ka khana halka rakhein.",
    "Raat ko der se khane ki wajah se digestion par asar padta hai.",
]
for _text in CLEAN:
    check(
        f"clean text is not flagged: {_text[:52]!r}",
        not safety.blames_medicine(_text),
        safety.blames_medicine(_text)[:60],
    )


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== guidance request: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}{f' [{detail}]' if detail else ''}")
sys.exit(0 if passed == len(results) else 1)
