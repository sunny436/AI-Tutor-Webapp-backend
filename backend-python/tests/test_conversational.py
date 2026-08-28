"""
The conversational consultation, and the safety it had to replace.

    python tests/test_conversational.py

The card intake is gone. This checks the three things that were load-bearing
about it and are now carried elsewhere:

  1. THE RETRIEVAL QUERY. `search_query` used to be built from tapped option
     labels. It is now built from `symptoms`. Its docstring records why the
     shape matters: on this corpus, appending the full collected text dropped an
     acidity query from 0.408 to 0.172 -- enough to start losing notes that
     genuinely match. So `symptoms` must stay SHORT, and that is enforced in
     code, not hoped for.

  2. THE RED-FLAG MECHANISM. The planner marked individual options `red_flag`,
     and safety.py describes its own keyword scan as the BACKSTOP to those
     markers rather than the only defence. Removing the cards removed the
     primary mechanism. Three replacements are checked here.

  3. RESUMING. Conversations persisted mid-cards carry phase `collecting` or
     `choosing`. `load_context` returns a FRESH context whenever validation
     raises, so a narrowed phase enum would silently wipe them.

No real LLM is called -- the gathering model is stubbed so the assertions are
about our logic, not about whether a model cooperated on the day.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src import safety  # noqa: E402
from src.consult import gathering, graph  # noqa: E402
from src.consult import state as ctx_state  # noqa: E402
from src.consult.gathering import MAX_GATHERING_ROUNDS, gather  # noqa: E402
from src.consult.schema import CONSULTING, LEGACY_PHASES, ConsultContext  # noqa: E402
from src.consult.sections import ALWAYS_INCLUDED, resolve_sections  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def stub_llm(payload: dict):
    """Replace the gathering model with a fixed reply."""
    return lambda *a, **k: json.dumps(payload)


def run_gather(payload, **kwargs):
    real = gathering.llm_invoke
    try:
        gathering.llm_invoke = stub_llm(payload)
        return asyncio.run(gather(problem=kwargs.pop("problem", "acidity"), **kwargs))
    finally:
        gathering.llm_invoke = real


# --- 1. symptoms are keywords, not transcript -------------------------------
print("\nsymptoms are SHORT retrieval keywords")

good = run_gather(
    {"reply": "Kab se?", "condition": "Acidity", "symptoms": ["gas", "after meals", "spicy food"],
     "red_flag": False, "ready": False}
)
check("keeps short keywords", good.symptoms == ["gas", "after meals", "spicy food"], str(good.symptoms))

dumped = run_gather(
    {"reply": "ok", "condition": "Acidity", "red_flag": False, "ready": False,
     "symptoms": [
         "The user says they have had gas since yesterday after eating out at a restaurant",
         "burning",
     ]}
)
check(
    "DROPS a transcript dump, keeping only the keyword",
    dumped.symptoms == ["burning"],
    str(dumped.symptoms),
)
check(
    "a non-list symptoms field degrades to empty rather than raising",
    run_gather({"reply": "ok", "symptoms": "gas, burning", "ready": False}).symptoms == [],
)

# The measurement this protects.
short_q = ctx_state.search_query(
    ConsultContext(problem="acidity", condition="Acidity", symptoms=["after meals", "spicy food"])
)
transcript = ConsultContext(problem="acidity", condition="Acidity")
transcript.notes = [
    "I have been having a burning feeling in my stomach since yesterday and it gets worse after I eat",
]
check(
    "a keyword query stays far shorter than a transcript one",
    len(short_q) < len(ctx_state.search_query(transcript)),
    f"{len(short_q)} vs {len(ctx_state.search_query(transcript))} chars",
)
check("search_query contains no sentence punctuation", "." not in short_q, short_q)


# --- 2. gathering behaviour --------------------------------------------------
print("\ngathering: readiness, ceiling, and failing safe")

check(
    "not ready -> keeps asking",
    run_gather({"reply": "Kab se?", "ready": False}).ready is False,
)
check(
    "ready -> proceeds to the plan",
    run_gather({"reply": "", "ready": True}).ready is True,
)
check(
    f"hard ceiling: forced ready at round {MAX_GATHERING_ROUNDS}",
    run_gather({"reply": "one more?", "ready": False}, rounds=MAX_GATHERING_ROUNDS).ready is True,
)
check(
    "an empty reply with nothing to ask counts as ready, never an empty bubble",
    run_gather({"reply": "", "ready": False}).ready is True,
)


def exploding(*a, **k):
    raise RuntimeError("model unreachable")


real = gathering.llm_invoke
try:
    gathering.llm_invoke = exploding
    dead = asyncio.run(gather(problem="acidity", language="hinglish"))
    check("model outage FAILS SAFE: asks again rather than planning blind", dead.ready is False)
    check("...and still says something, in the user's language", bool(dead.reply), dead.reply[:50])
finally:
    gathering.llm_invoke = real


# --- 3. the three red-flag replacements --------------------------------------
print("\nsafety: three replacements for the planner's red_flag markers")

# (a) transcript-wide keyword scan
late = ConsultContext(problem="mujhe acidity hai")
late = ctx_state.remember_chat(late, "kal se ho raha hai", "Kya khaya tha?")
late = ctx_state.remember_chat(late, "aaj vomit me blood aaya", "")
check(
    "(a) a red flag typed THREE TURNS LATE is still caught",
    safety.scan(*ctx_state.safety_fragments(late)),
    "blood in vomit, mid-conversation",
)
check(
    "...which the old opening-complaint-only scan would have MISSED",
    not safety.scan(late.problem),
    "proves the widening is what catches it",
)
check(
    "a benign conversation is not flagged",
    not safety.scan(*ctx_state.safety_fragments(
        ctx_state.remember_chat(ConsultContext(problem="acidity"), "spicy khana khaya", "ok")
    )),
)
check(
    "symptoms are scanned too, not just the transcript",
    safety.scan(*ctx_state.safety_fragments(
        ConsultContext(problem="thakan", symptoms=["blood in stool"])
    )),
)

# (b) the gathering model's own verdict
flagged = run_gather({"reply": "Doctor ko dikhaiye.", "red_flag": True, "ready": False})
check("(b) the gathering step can raise a red flag itself", flagged.red_flag is True)

# (c) untouched
check(
    "(c) is_serious_condition still works, unchanged",
    safety.is_serious_condition("mujhe cancer hai ek saal se"),
)


# --- 4. escalation actually happens in the graph ------------------------------
print("\nescalation reaches the user")

class _FakeRoute:
    def __init__(self, intent="health", reply="", problem="acidity"):
        self.intent = intent
        self.reply = reply
        self.problem = problem


def run_turn_with(gathered, problem=None, free_text=None, raw_context=None, intent="health"):
    """One turn with the router and the gathering model stubbed.

    `problem` vs `free_text` is not cosmetic: it is the distinction the FRONTEND
    makes. Outside a consultation it sends `problem`; once the phase is in
    CONSULTING it sends `freeText` instead. A follow-up must therefore be tested
    as free_text, or it takes the "this is a different complaint" branch — which
    correctly starts a fresh context and would make a context-preservation
    assertion pass or fail for the wrong reason.
    """
    real_route, real_gather = graph.route_message, graph.gather

    async def fake_route(*a, **k):
        return _FakeRoute(intent=intent)

    async def fake_gather(**k):
        return gathered

    try:
        graph.route_message = fake_route
        graph.gather = fake_gather
        return asyncio.run(
            graph.run_turn(
                problem=problem or "",
                raw_context=raw_context,
                answers=None,
                free_text=free_text,
            )
        )
    finally:
        graph.route_message, graph.gather = real_route, real_gather


escalated = run_turn_with(
    gathering.Gathered(reply="", red_flag=True), problem="mujhe acidity hai"
)
check(
    "a gathering red flag escalates instead of continuing",
    escalated.kind == "escalation",
    escalated.kind,
)
check("escalation ends the consultation", escalated.context.phase == "completed")

# Hinglish, because that is what these users type. The English list alone held
# "vomiting blood", which does not appear anywhere in this sentence.
typed_flag = run_turn_with(
    gathering.Gathered(reply="Kab se?", ready=False),
    problem="mujhe vomit me blood aa raha hai",
)
check(
    "a HINGLISH typed red flag escalates before any gathering happens",
    typed_flag.kind == "escalation",
    typed_flag.kind,
)


# --- 5. no cards, and context survives turns ---------------------------------
print("\nconversation, not cards")

turn1 = run_turn_with(
    gathering.Gathered(reply="Ye kab se ho rahi hai?", condition="Gas & Bloating",
                       symptoms=["gas"], ready=False),
    problem="mujhe gas ho rahi hai",
)
check("turn 1 is a CHAT turn, not an intake", turn1.kind == "chat", turn1.kind)
check("turn 1 renders NO cards", turn1.intake is None, str(turn1.intake))
check("turn 1 enters the gathering phase", turn1.context.phase == "gathering", turn1.context.phase)
check("turn 1 asks a question", "kab se" in turn1.answer.lower(), turn1.answer[:60])

# The brief's own script, continued. Sent as free_text because the phase is now
# `gathering` — exactly what the frontend does once IN_CONSULTATION matches.
# `intent="casual"` stands in for the router's aside classification, so the turn
# continues the consultation rather than starting a new one.
turn2 = run_turn_with(
    gathering.Gathered(reply="Kal kya khaya tha?", condition="Gas & Bloating",
                       symptoms=["aaj se"], ready=False),
    free_text="aaj se",
    raw_context=turn1.context.model_dump(),
    intent="knowledge",
)
check("turn 2 still renders no cards", turn2.intake is None)
check(
    "CONTEXT SURVIVES: the condition carries across turns",
    turn2.context.condition == "Gas & Bloating",
    turn2.context.condition,
)
check(
    "symptoms accumulate across turns rather than replacing",
    set(turn2.context.symptoms) >= {"gas", "aaj se"},
    str(turn2.context.symptoms),
)
check(
    "the transcript grows with each turn",
    len(turn2.context.chat_history) > len(turn1.context.chat_history),
    f"{len(turn1.context.chat_history)} -> {len(turn2.context.chat_history)}",
)
check("the round counter advances", turn2.context.round > turn1.context.round)


# --- 6. resuming a pre-change conversation ------------------------------------
print("\nold conversations still open")

check("SUPPORTED_VERSION is still 2", ctx_state.SUPPORTED_VERSION == 2)

for legacy in LEGACY_PHASES:
    blob = {
        "v": 2, "phase": legacy, "problem": "acidity", "condition": "Acidity",
        "greeted": True, "language": "hinglish",
        "chat_history": [{"role": "user", "text": "mujhe acidity hai"}],
    }
    restored = ctx_state.load_context(blob)
    check(f"phase {legacy!r} -> 'gathering'", restored.phase == "gathering", restored.phase)
    check(f"...{legacy!r} keeps the conversation rather than resetting",
          restored.problem == "acidity" and len(restored.chat_history) == 1)

check(
    "both legacy phases are still accepted by the model (not narrowed away)",
    all(p in CONSULTING for p in LEGACY_PHASES),
)
check(
    "a context with NO phase field still loads",
    ctx_state.load_context({"v": 2, "problem": "x"}).phase == "idle",
)
check(
    "an unknown version is still discarded, as before",
    ctx_state.load_context({"v": 99, "problem": "x"}).problem == "",
)


# --- 7. the plan still contains everything -----------------------------------
print("\nthe plan itself is unchanged")

check(
    "no section picker means everyone gets the complete plan",
    len(resolve_sections(None)) >= 6,
    f"{len(resolve_sections(None))} sections",
)
for required in ALWAYS_INCLUDED:
    check(f"ALWAYS_INCLUDED still forced: {required!r}", required in resolve_sections(None))


# ---------------------------------------------------------------------------
# has_health_signal must not fire on words that merely CONTAIN a symptom word.
#
# It used to, because the test was `signal in lowered` - a plain substring
# match. Measured before the fix, every line in FALSE_POSITIVES below returned
# True: "will" and "skill" and "bill" and "still" via "ill", "tissue" via
# "issue", "carpet" and "petrol" via "pet", "persona" via "sona", and
# "attached" via "ache".
#
# That last one is how it surfaced - a question about an uploaded file could not
# reach the document path, because this guard swore it was a health complaint -
# but the real damage was that a guard which says yes to everything is not a
# guard at all. Its whole job is to stop the classifier inventing a complaint
# the user never made.
#
# Both halves are asserted on purpose. Tightening this is only safe if real
# complaints still register, and a boundary that is too strict would break the
# stems: "allerg" has to reach allergy, "bloat" bloating, "ache" aches.
from src.consult.router import has_health_signal  # noqa: E402

FALSE_POSITIVES = (
    "now can u see the file which i was attached",
    "tell me something about the file i was attached",
    "i will tell you later",
    "that is a good skill",
    "please fill the form",
    "send me the bill",
    "this is still pending",
    "i need a tissue",
    "the carpet is dirty",
    "he has a strong persona",
    "what is the petrol price",
    "open the file",
)

REAL_COMPLAINTS = (
    "i have a headache",
    "mujhe gas ho rahi hai",
    "i feel sick",
    "mujhe pet dard ho raha hai",
    "pet saaf nahi hota",
    "raat ko neend nahi aati",
    "my appetite is low",
    "i have joint pain",
    "khujli ho rahi hai",
    "bahut thakan lagti hai",
    "mujhe allergy hai",
    "bloating problem",
    "thyroid ke liye kya khana chahiye",
    "baal jhad rahe hain",
    "acidity ho rahi hai",
    "saans lene me dikkat",
    "sar dard ho raha hai",
    "my back aches",
    "i have an illness",
    "swelling in my leg",
    "mujhe cold hai",
    "stomach pain",
)

for phrase in FALSE_POSITIVES:
    check(f"not a health signal: {phrase!r}", not has_health_signal(phrase))

for phrase in REAL_COMPLAINTS:
    check(f"still a health signal: {phrase!r}", has_health_signal(phrase))


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== conversational: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}: {detail}")
sys.exit(0 if passed == len(results) else 1)
