"""
The whole pipeline, end to end, with the model stubbed.

WHAT THIS COVERS THAT NOTHING ELSE DOES
Every other suite tests one module. This tests the WIRING: that a message
actually travels routing -> patient state -> episode -> safety -> reasoning ->
uncertainty -> retrieval -> evidence -> gate -> response -> state update, in
that order, and that each stage's output really reaches the next one. Modules
that are individually perfect and not connected produce exactly the behaviour
this catches.

STUBBED, NOT LIVE. `gather`, `classify_focus`, `reason`, `write_plan` and
retrieval are replaced with fixtures, so the ORDER and the PLUMBING are what is
under test rather than the model's mood. The live suites cover the prose.

It also pins the short path: a greeting must not pay for reasoning or
retrieval. That is a cost property, and cost properties rot silently.

    python tests/test_pipeline_integration.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from src.clinical import episodes as ep  # noqa: E402
from src.clinical import timeline as tl  # noqa: E402
from src.clinical.reasoning import Reasoning, parse  # noqa: E402
from src.consult import graph, run_turn  # noqa: E402
from src.consult.gathering import Gathered  # noqa: E402
from src.consult.router import Route  # noqa: E402
from src.retrieval.base import Chunk, RetrievalResult  # noqa: E402

results: list[tuple[str, bool, str]] = []
CALLS: dict[str, int] = {}


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
class _Pipeline:
    def to_sources(self, results):
        return [{"source": "graphrag:1-caraka-samhita.pdf"}]

    def to_prompt_block(self, results):
        return "passage text"


CHUNKS = [
    Chunk(text="Amlapitta arises from vidahi ahara. Sheeta virya dravyas are "
                "indicated. Guggulu should not be given with blood thinners.",
          source="graphrag:1-caraka-samhita.pdf", score=0.8),
]


def install(*, ready=True, focus=("complete",), plan=None, reasoning_ok=True,
            condition="Acidity", intent="health"):
    """Replace every model-backed step with a fixture. Returns the call log."""
    CALLS.clear()

    async def _gather(**kw):
        CALLS["gather"] = CALLS.get("gather", 0) + 1
        CALLS["gather_history"] = kw.get("history", "")
        return Gathered(reply="Aur bataiye?", condition=condition,
                        symptoms=["jalan", "khaane ke baad"], ready=ready,
                        profile_facts=kw.get("_facts") or {})

    async def _focus(reply, language=""):
        CALLS["classify_focus"] = CALLS.get("classify_focus", 0) + 1
        return list(focus)

    async def _reason(**kw):
        CALLS["reason"] = CALLS.get("reason", 0) + 1
        CALLS["reason_guide"] = kw.get("guide", "")
        CALLS["reason_triage"] = kw.get("triage", "")
        if not reasoning_ok:
            return Reasoning(ok=False)
        return parse({
            "modern": {"possible_explanations": [
                {"name": "acid reflux", "supports": ["burning after meals"],
                 "likelihood": "common"}], "uncertainty": "low",
                "lifestyle_contributors": ["late dinner"]},
            "ayurveda": {"presenting_pattern": "amlapitta-like",
                         "dosha_involvement": ["pitta"], "nidana": ["late meals"],
                         "prakriti_status": "not assessed"},
            "synthesis": {"combined_scope": "diet and routine"},
        }, history="acidity")

    async def _retrieve(context, principal, conversation_id):
        CALLS["retrieve"] = CALLS.get("retrieve", 0) + 1
        return _Pipeline(), [RetrievalResult(section="notes", chunks=CHUNKS)]

    async def _route(message, history="", greeted=False, language="", documents=""):
        CALLS["route_message"] = CALLS.get("route_message", 0) + 1
        # For every CONVERSATIONAL intent the real router does not just
        # classify, it also WRITES the reply the user reads. A stub that
        # returns an empty one makes a greeting look unanswered.
        if intent == "health":
            return Route(intent=intent, problem=message)
        return Route(intent=intent, reply="Namaste! Bataiye, kya pareshani hai?")

    async def _plan(**kw):
        CALLS["write_plan"] = CALLS.get("write_plan", 0) + 1
        CALLS["plan_knowledge"] = kw.get("knowledge", "")
        CALLS["plan_details"] = kw.get("details", "")
        CALLS["plan_sections"] = list(kw.get("sections") or [])
        return plan or (
            "Samajh gaya.\n\n**Root Cause**\nPitta.\n\n**Changes To Make**\n"
            "Do: Ashwagandha lijiye. Do: samay par khana khaiye.\n\n"
            "**Yoga & Breathing**\nAsanas: Vajrasana.\n\n**Food Chart**\n"
            "Eat: moong dal.\n\n**Daily Routine**\nSubah uthiye.\n\n"
            "**When To See A Doctor**\nKhoon aaye to."
        )

    graph.gather = _gather
    graph.classify_focus = _focus
    graph.clinical_reasoning.reason = _reason
    graph._retrieve = _retrieve
    graph.write_plan = _plan
    graph.route_message = _route
    return CALLS


BASE = {
    "phase": "gathering", "round": 2, "problem": "acidity", "condition": "Acidity",
    "language": "hinglish", "greeted": True, "profile_loaded": True,
    "chat_history": [{"role": "user", "text": "mujhe acidity hai"}],
}


def ctx(**over):
    out = dict(BASE)
    out.update(over)
    return out


# ===========================================================================
# 1. The full path, in order, for a health message
# ===========================================================================
async def test_full_path():
    install()
    r = await run_turn(problem="", raw_context=ctx(
        patient_profile={"conditions": ["diabetes"], "medications": ["metformin"]}),
        answers=None, free_text="poora plan batao", profile="")
    c = r.context

    check("1. the turn produces an answer", r.kind == "answer", r.kind)
    check("2. an episode was selected", bool(c.active_episode_id))
    check("3. the episode carries what was learned",
          bool(ep.get(c.episodes, c.active_episode_id).associated_symptoms))
    check("4. reasoning ran once", CALLS.get("reason") == 1, CALLS.get("reason"))
    check("5. triage reached the reasoner",
          CALLS.get("reason_triage") in ("YELLOW", "ORANGE"), CALLS.get("reason_triage"))
    check("6. the CONDITION GUIDE reached the reasoner",
          "digestion and the gut" in CALLS.get("reason_guide", ""),
          CALLS.get("reason_guide", "")[:60])
    check("7. retrieval ran", CALLS.get("retrieve") == 1)
    check("8. the EVIDENCE GRADE reached the plan prompt",
          "EVIDENCE:" in CALLS.get("plan_knowledge", ""))
    check("9. CLAIMS reached the plan prompt",
          "not permission" in CALLS.get("plan_knowledge", ""),
          CALLS.get("plan_knowledge", "")[:80])
    check("10. a classical source is marked as traditional, not research",
          "Traditionally described" in CALLS.get("plan_knowledge", ""))
    check("11. the REASONING block reached the plan prompt",
          "AYURVEDA VIEW" in CALLS.get("plan_details", ""),
          CALLS.get("plan_details", "")[-120:])
    check("12. prakriti is declared unestablished to the composer",
          "PRAKRITI IS NOT ESTABLISHED" in CALLS.get("plan_details", ""))
    # NOT blocked here, and that is correct: ashwagandha clashes with THYROID
    # medication and immunosuppressants, not with metformin. A gate that
    # removed it for every diabetic would be a gate nobody could trust.
    check("13. a herb with no clash for THIS patient survives the gate",
          "shwagandha" in r.answer, r.answer[:80])
    check("14. the plan still reaches the reader", "**Root Cause**" in r.answer)
    check("15. the doctor section survived", "When To See A Doctor" in r.answer)


asyncio.run(test_full_path())


async def test_gate_blocks_for_the_right_patient():
    """The other half of 13: the same plan, a patient it IS unsafe for."""
    install()
    r = await run_turn(problem="", raw_context=ctx(
        patient_profile={"conditions": ["hypothyroidism"], "medications": ["thyronorm"]}),
        answers=None, free_text="poora plan batao", profile="")
    check("13b. the SAME herb is removed for a thyroid patient",
          "shwagandha" not in r.answer, r.answer[:90])
    check("13c. ...and the reader is told something was withheld",
          "jaan-bujhkar" in r.answer, r.answer[-90:])
    check("13d. ...while the safe advice in the same section survives",
          "samay par khana" in r.answer, r.answer[:140])


asyncio.run(test_gate_blocks_for_the_right_patient())


# ===========================================================================
# 2. Scoped intent — the gate enforces what was asked for
# ===========================================================================
async def test_scoped():
    install(focus=("yoga",))
    r = await run_turn(problem="", raw_context=ctx(), answers=None,
                       free_text="sirf yoga batao", profile="")
    kept = [h for h, _b in graph.clinical_gate.split_sections(r.answer) if h]
    check("16. 'sirf yoga batao' returns yoga and the doctor section only",
          kept == ["Yoga & Breathing", "When To See A Doctor"], kept)
    check("17. the requested sections reached write_plan",
          set(CALLS.get("plan_sections", [])) == {"yoga", "doctor"},
          CALLS.get("plan_sections"))


asyncio.run(test_scoped())


# ===========================================================================
# 3. Multi-intent, and changing your mind after the plan
# ===========================================================================
async def test_multi_intent():
    install(focus=("yoga", "diet"))
    r = await run_turn(problem="", raw_context=ctx(), answers=None,
                       free_text="yoga aur diet dono batao", profile="")
    check("18. two intents at once are both honoured",
          set(r.context.help_types) == {"yoga", "diet"}, r.context.help_types)
    kept = [h for h, _b in graph.clinical_gate.split_sections(r.answer) if h]
    check("19. ...and both sections come back",
          set(kept) == {"Yoga & Breathing", "Food Chart", "When To See A Doctor"}, kept)

    # NARROWING after the plan replaces the old choice.
    done = r.context.model_dump()
    install(focus=("diet",))
    r2 = await run_turn(problem="", raw_context=done, answers=None,
                        free_text="ab sirf diet batao", profile="")
    check("20. narrowing the request after a plan REPLACES the old focus",
          set(r2.context.help_types) == {"diet"}, r2.context.help_types)

    # ADDING ("bhi") keeps what they already had.
    install(focus=("yoga",))
    r3 = await run_turn(problem="", raw_context=r2.context.model_dump(), answers=None,
                        free_text="yoga bhi batao", profile="")
    check("21. 'bhi' ADDS rather than replaces",
          set(r3.context.help_types) == {"diet", "yoga"}, r3.context.help_types)

    # Widening to the whole plan.
    install(focus=("complete",))
    r4 = await run_turn(problem="", raw_context=r3.context.model_dump(), answers=None,
                        free_text="poora plan de do", profile="")
    check("22. widening to the complete plan works",
          r4.context.help_type == "complete", r4.context.help_types)


asyncio.run(test_multi_intent())


# ===========================================================================
# 4. Safety outranks everything downstream
# ===========================================================================
async def test_safety_precedence():
    install()
    r = await run_turn(problem="", raw_context=ctx(), answers=None,
                       free_text="ulti me khoon aa raha hai, koi upay batao", profile="")
    check("23. a red flag escalates instead of planning", r.kind == "escalation", r.kind)
    check("24. NO REASONING RUNS once it is an emergency", "reason" not in CALLS, CALLS)
    check("25. NO RETRIEVAL RUNS either", "retrieve" not in CALLS)
    check("26. no plan is written", "write_plan" not in CALLS)
    check("27. risk is recorded and sticks", r.context.risk_level == "urgent")
    check("28. the reply names no yoga practice",
          not graph.safety.names_practice(r.answer or ""), r.answer[:60])


asyncio.run(test_safety_precedence())


# ===========================================================================
# 5. The short path — a greeting must not pay for the clinical layer
# ===========================================================================
async def test_short_path():
    install(intent="casual")
    r = await run_turn(problem="hii", raw_context=None, answers=None,
                       free_text=None, profile="")
    check("29. a greeting is answered", bool(r.answer))
    check("30. NO REASONING for a greeting", "reason" not in CALLS, CALLS)
    check("31. NO RETRIEVAL for a greeting", "retrieve" not in CALLS)
    check("32. NO PLAN for a greeting", "write_plan" not in CALLS)


asyncio.run(test_short_path())


# ===========================================================================
# 6. Current-turn visibility — no one-turn lag
# ===========================================================================
async def test_current_turn():
    install(ready=False)
    r = await run_turn(problem="", raw_context=ctx(), answers=None,
                       free_text="2 hafte se hai aur raat ko zyada hoti hai", profile="")
    check("33. THE MESSAGE JUST TYPED IS IN THE HISTORY gather() READS",
          "raat ko zyada" in CALLS.get("gather_history", ""),
          CALLS.get("gather_history", "")[-90:])
    check("34. it appears exactly once",
          CALLS.get("gather_history", "").count("raat ko zyada") == 1)

    # ...and on the NEXT turn it is still there, once, with the new one after it.
    install(ready=False)
    r2 = await run_turn(problem="", raw_context=r.context.model_dump(), answers=None,
                        free_text="khaane ke baad bhi hoti hai", profile="")
    history = CALLS.get("gather_history", "")
    check("35. the previous answer is still there on the next turn",
          history.count("raat ko zyada") == 1, history[-140:])
    check("36. and so is the new one", "khaane ke baad bhi" in history)


asyncio.run(test_current_turn())


# ===========================================================================
# 7. Topic switching keeps both problems
# ===========================================================================
async def test_topic_switch():
    install(ready=False)
    r = await run_turn(problem="mujhe acidity ho rahi hai", raw_context=None,
                       answers=None, free_text=None, profile="")

    async def _knee(**kw):
        return Gathered(reply="Aur bataiye?", condition="Knee pain",
                        symptoms=["ghutne me dard"], ready=False)

    graph.gather = _knee
    r2 = await run_turn(problem="", raw_context=r.context.model_dump(), answers=None,
                        free_text="ab mere ghutne me bhi dard hai", profile="")
    names = [e.problem_name for e in r2.context.episodes]
    check("37. a second problem opens its own episode", len(r2.context.episodes) == 2, names)

    install(ready=False)
    r3 = await run_turn(problem="", raw_context=r2.context.model_dump(), answers=None,
                        free_text="acidity abhi bhi hai", profile="")
    active = ep.get(r3.context.episodes, r3.context.active_episode_id)
    check("38. coming back returns to the FIRST episode, not a third",
          len(r3.context.episodes) == 2 and active.problem_name == "Acidity",
          [e.problem_name for e in r3.context.episodes])


asyncio.run(test_topic_switch())


# ===========================================================================
# 8. What was already tried reaches the composer
# ===========================================================================
async def test_outcomes_reach_composer():
    outcomes, _ = tl.start_intervention([], "ginger tea", episode_id="e1")
    outcomes, _ = tl.report_outcome(outcomes, "ginger tea", response="no_change")
    events, _ = tl.record([], "symptom_worsened", "worse after late dinners",
                          episode_id="e1")
    install()
    r = await run_turn(problem="", raw_context=ctx(
        episodes=[{"episode_id": "e1", "problem_name": "Acidity",
                   "canonical_concepts": ["acidity"], "status": "active"}],
        active_episode_id="e1",
        outcomes=[o.model_dump() for o in outcomes],
        timeline=[e.model_dump() for e in events],
    ), answers=None, free_text="poora plan batao", profile="")
    details = CALLS.get("plan_details", "")
    check("39. WHAT DID NOT HELP reaches the composer",
          "ginger tea" in details and "do not re-offer" in details, details[-160:])
    check("40. the timeline reaches the composer",
          "worse after late dinners" in details, details[:160])


asyncio.run(test_outcomes_reach_composer())


# ===========================================================================
# 9. Degradation — a failed reasoner must not fail the turn
# ===========================================================================
async def test_degradation():
    install(reasoning_ok=False)
    r = await run_turn(problem="", raw_context=ctx(), answers=None,
                       free_text="poora plan batao", profile="")
    check("41. a failed reasoner still produces an answer", r.kind == "answer", r.kind)
    check("42. ...and contributes nothing rather than something half-parsed",
          "AYURVEDA VIEW" not in CALLS.get("plan_details", ""))


asyncio.run(test_degradation())


# ===========================================================================
# AN EPISODE IS OPENED BY A COMPLAINT, NOT BY EVERY MESSAGE
#
# `episodes.select` opens a new episode whenever the text does not match an
# existing one, and MOST turns in a consultation name no complaint at all:
# "root cause kya hai bas", "poora plan batao", "2 mahine se ho raha hai",
# "haan". Measured against the live model: "root cause kya hai bas" minted an
# episode called "Digestive imbalance" and made it active, stealing the turn
# from the gas and bloating the person was actually discussing.
#
# That is not a cosmetic mislabel. A new episode starts with empty
# `associated_symptoms`, and the reasoner, the condition guide, the timeline
# and the already-tried list are all keyed off the active one — so the
# consultation forgets itself halfway through, at the exact moment the reader
# asks for the conclusion.
# ===========================================================================
async def test_episode_needs_a_complaint():
    install(ready=False)
    first = await run_turn(problem="mujhe gas aur bloating hoti hai", raw_context=ctx(
        chat_history=[], phase="gathering", round=0, problem="", condition=""),
        answers=None, free_text="", profile="")
    opened = list(first.context.episodes)
    check("E1. the opening complaint opens exactly one episode",
          len(opened) == 1, [e.problem_name for e in opened])
    active_id = first.context.active_episode_id

    # Every one of these names no complaint. None may open an episode, and
    # none may change which one is active.
    NOT_COMPLAINTS = [
        "root cause kya hai bas",
        "poora plan batao",
        "sirf yoga bata do",
        "2 mahine se ho raha hai",
        "haan",
        "theek hai dhanyavaad",
    ]
    carried = first.context.model_dump()
    for text in NOT_COMPLAINTS:
        install(ready=False)
        turn = await run_turn(problem="", raw_context=carried, answers=None,
                              free_text=text, profile="")
        check(f"E2. no new episode for a message naming no complaint: {text!r}",
              len(turn.context.episodes) == 1, [e.problem_name for e in turn.context.episodes])
        check(f"E3. ...and the active episode is unchanged: {text!r}",
              turn.context.active_episode_id == active_id,
              f"{turn.context.active_episode_id[:8]} != {active_id[:8]}")
        check(f"E4. ...and what was learned survives: {text!r}",
              bool(ep.get(turn.context.episodes, active_id).associated_symptoms),
              ep.get(turn.context.episodes, active_id).associated_symptoms)

    # A GENUINELY NEW COMPLAINT STILL OPENS ONE. The guard must not be so
    # tight that a second problem can never be raised — that was the whole
    # reason episodes exist.
    # The real gatherer names the NEW complaint here; the default fixture
    # answers "Acidity" to everything, and that word alone was enough for the
    # knee message to match the acidity episode. Stubbing the condition the
    # live model would actually return is what makes this case real.
    install(ready=False, condition="Knee Pain")
    knee = await run_turn(problem="", raw_context=carried, answers=None,
                          free_text="ab mere ghutne me bhi dard hai", profile="")
    check("E5. A SECOND REAL COMPLAINT STILL OPENS ITS OWN EPISODE",
          len(knee.context.episodes) == 2,
          [e.problem_name for e in knee.context.episodes])
    check("E6. ...and it becomes the active one",
          knee.context.active_episode_id != active_id)


asyncio.run(test_episode_needs_a_complaint())


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== pipeline integration: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}{f' [{detail}]' if detail else ''}")
sys.exit(0 if passed == len(results) else 1)
