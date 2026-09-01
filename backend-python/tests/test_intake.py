"""
Guided intake: gather -> ask focus -> retrieve -> answer. Live (Ollima +
GraphRAG), matching how test_safety.py/test_reversal.py already verify this
session's changes against the real orchestrator, not stubs of it.

    python tests/test_intake.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

# Windows redirects stdout as cp1252, and several test NAMES below are
# Devanagari — so `print`ing a PASS raised UnicodeEncodeError and killed the
# run partway through. The suite could not be run to completion on the
# platform its own docstring tells you to run it on. Same reconfigure
# `server.py` applies, for the same reason.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


from src.consult import run_turn  # noqa: E402
from src.consult.sections import SECTION_LIBRARY, looks_like_plan  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


# THE FILLER IS A REAL ANSWER, not a request for the plan.
#
# It used to be "bas itna hi hai, aap bata dijiye". That sentence now ENDS the
# intake and goes straight to the plan — it is a person saying they have
# nothing more to add and asking to be told (router.asks_for_guidance_now,
# added after the live browser showed it being answered with the SAME question
# the previous turn had already asked). A helper whose job is to WALK the
# intake as far as the focus question therefore has to reply the way somebody
# still answering questions replies.
_INTAKE_FILLER = "haan, thoda stress rehta hai aur khana time par nahi hota"

async def run_to_focus(opener: str, filler: str = _INTAKE_FILLER):
    """Drive a fresh consultation from `opener` up to (and including) the
    turn that asks what kind of help they want. Returns the list of
    (result, context_dict) pairs for every turn taken."""
    turns = []
    context = None
    message = opener
    for _ in range(6):
        result = await run_turn(
            problem=message if context is None else "",
            raw_context=context,
            answers=None,
            free_text=None if context is None else message,
            profile="",
        )
        context = result.context.model_dump()
        turns.append((result, context))
        if context.get("phase") == "asking_focus":
            return turns
        if result.kind in ("answer", "escalation", "error"):
            return turns
        message = filler
    return turns


async def run_full(opener: str, focus_reply: str, filler: str = _INTAKE_FILLER):
    """Full consultation: gather -> focus question -> focus_reply -> plan."""
    turns = await run_to_focus(opener, filler)
    last_result, last_context = turns[-1]
    if last_context.get("phase") != "asking_focus":
        return turns  # escalated or errored before reaching a focus question
    result = await run_turn(
        problem="", raw_context=last_context, answers=None, free_text=focus_reply, profile="",
    )
    turns.append((result, result.context.model_dump()))
    return turns


# ===========================================================================
# 1 & 2. A health complaint does NOT immediately produce a knowledge answer;
# the first reply is a genuine question, not a plan.
# ===========================================================================
async def _test_no_immediate_answer():
    result = await run_turn(
        problem="I am facing acidity since last night",
        raw_context=None, answers=None, free_text=None, profile="",
    )
    check(
        "a health complaint does NOT immediately produce a plan",
        result.kind == "chat" and result.context.phase == "gathering",
        f"kind={result.kind} phase={result.context.phase}",
    )
    check(
        "the first reply is a question, not the sectioned plan format",
        not looks_like_plan(result.answer),
        result.answer[:150],
    )
    check(
        "the first reply is non-empty prose (an actual question, not silence)",
        len(result.answer.strip()) > 20,
        result.answer[:100],
    )


asyncio.run(_test_no_immediate_answer())


# ===========================================================================
# 3. Answers are retained across turns — symptoms accumulate, questions
# don't repeat verbatim.
# ===========================================================================
async def _test_retention():
    turns = await run_to_focus("mujhe subah subah pet me gas aur bloating hoti hai")
    gathering_turns = [t for t, c in turns if c.get("phase") == "gathering"]
    replies = [t.answer for t in gathering_turns]
    check(
        "at least 2 gathering turns happened before reaching focus/plan",
        len(gathering_turns) >= 1,
        f"{len(gathering_turns)} gathering turns, {len(turns)} total",
    )
    check(
        "no two gathering questions are textually identical",
        len(replies) == len(set(replies)),
        replies,
    )
    final_context = turns[-1][1]
    check(
        "symptoms were accumulated into context by the end of gathering",
        len(final_context.get("symptoms") or []) > 0 or final_context.get("phase") == "asking_focus",
        final_context.get("symptoms"),
    )


asyncio.run(_test_retention())


# ===========================================================================
# 4. The bot asks what type of help is wanted, once gathering is ready —
# and NOT before (constraint: retrieval/plan only after focus is picked).
# ===========================================================================
async def _test_asks_focus():
    turns = await run_to_focus("mujhe kaafi din se neend nahi aa rahi hai raat ko")
    last_result, last_context = turns[-1]
    check(
        "gathering eventually reaches the asking_focus phase",
        last_context.get("phase") == "asking_focus",
        last_context.get("phase"),
    )
    check(
        "the focus turn mentions a condition and offers a choice (not a plan)",
        not looks_like_plan(last_result.answer) and len(last_result.answer) > 20,
        last_result.answer[:200],
    )
    check(
        "help_type is NOT set yet at the asking_focus turn itself",
        last_context.get("help_type") == "",
        last_context.get("help_type"),
    )


asyncio.run(_test_asks_focus())


# ===========================================================================
# 5 & 6. Selecting a focus is retained in state, and scopes the final answer
# to the right section(s) — proving retrieval/writing only happens once a
# focus is chosen, and that the five categories map correctly.
# ===========================================================================
_EXPECTED_HEADINGS = {
    "root_cause": ["root_cause"],
    "remedies": ["changes"],
    "yoga": ["yoga"],
    "diet": ["food"],
}
_OTHER_HEADINGS = {
    key: [k for k in SECTION_LIBRARY if k not in (*sections, "doctor")]
    for key, sections in _EXPECTED_HEADINGS.items()
}


async def _test_focus_selection(reply_text: str, expected_help_type: str):
    turns = await run_full("mujhe khaana khane ke baad pet me jalan hoti hai", reply_text)
    final_result, final_context = turns[-1]
    check(
        f"replying {reply_text!r} sets help_type={expected_help_type!r} in state",
        final_context.get("help_type") == expected_help_type,
        final_context.get("help_type"),
    )
    check(
        f"help_type={expected_help_type!r} produces a real generated plan (kind=answer)",
        final_result.kind == "answer",
        final_result.kind,
    )
    wanted_headings = {SECTION_LIBRARY[k][0] for k in _EXPECTED_HEADINGS[expected_help_type]}
    unwanted_headings = {SECTION_LIBRARY[k][0] for k in _OTHER_HEADINGS[expected_help_type]}
    present = {h for h in wanted_headings | unwanted_headings if h in final_result.answer}
    check(
        f"the answer contains the requested section heading(s) for {expected_help_type!r}",
        wanted_headings <= present,
        f"wanted={wanted_headings} present={present}",
    )
    check(
        f"the answer does NOT contain unrelated section headings for {expected_help_type!r}",
        not (unwanted_headings & present),
        f"leaked={unwanted_headings & present}",
    )


asyncio.run(_test_focus_selection("sirf yoga bata do", "yoga"))
asyncio.run(_test_focus_selection("root cause kya hai bas", "root_cause"))
asyncio.run(_test_focus_selection("diet chart chahiye", "diet"))


# ===========================================================================
# 7. Retrieval happens only once the consultation has enough information —
# GraphRAG/_retrieve is never reached during gathering turns.
# ===========================================================================
async def _test_retrieval_timing():
    import src.consult.graph as graph_module

    call_count = {"n": 0}
    original_retrieve = graph_module._retrieve

    async def counting_retrieve(*args, **kwargs):
        call_count["n"] += 1
        return await original_retrieve(*args, **kwargs)

    graph_module._retrieve = counting_retrieve
    try:
        turns = await run_to_focus("mujhe khujli ho rahi hai kaafi dino se")
        check(
            "_retrieve is NOT called during any gathering-phase turn",
            call_count["n"] == 0,
            f"{call_count['n']} calls before asking_focus",
        )
        last_context = turns[-1][1]
        if last_context.get("phase") == "asking_focus":
            await run_turn(problem="", raw_context=last_context, answers=None,
                            free_text="poora plan bata do", profile="")
            check(
                "_retrieve IS called once the focus turn resolves",
                call_count["n"] >= 1,
                call_count["n"],
            )
    finally:
        graph_module._retrieve = original_retrieve


asyncio.run(_test_retrieval_timing())


# ===========================================================================
# 8. GraphRAG is still used only for retrieval — reuse test_reversal.py's
# static regression rather than duplicate it.
# ===========================================================================
import re as _re  # noqa: E402

_src_dir = Path(__file__).resolve().parents[1] / "src"
_offending = []
for _py in _src_dir.rglob("*.py"):
    for _lineno, _line in enumerate(_py.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if _re.search(r"graphrag\.answer(?:_stream)?\s*\(", _line.split("#", 1)[0]):
            _offending.append(f"{_py}:{_lineno}")
check("GraphRAG is still retrieval-only (no code calls graphrag.answer)", _offending == [], _offending)


# ===========================================================================
# 9. Hindi/Hinglish multi-turn intake works — both scripts reach a focus
# question and resolve a help_type.
# ===========================================================================
async def _test_language(opener: str, label: str):
    turns = await run_full(opener, "yoga bata dijiye")
    final_result, final_context = turns[-1]
    check(
        f"{label} intake reaches asking_focus at some point",
        any(c.get("phase") == "asking_focus" for _, c in turns),
        [c.get("phase") for _, c in turns],
    )
    check(
        f"{label} intake resolves a help_type and produces an answer",
        final_context.get("help_type") != "" and final_result.kind == "answer",
        f"help_type={final_context.get('help_type')!r} kind={final_result.kind}",
    )


asyncio.run(_test_language("मुझे कल रात से पेट में जलन हो रही है", "Devanagari"))
asyncio.run(_test_language("mujhe kal raat se pet me jalan ho rahi hai", "Hinglish"))


# ===========================================================================
# 10. Existing API contract shape is unchanged — same top-level keys,
# help_type/missing_info live inside the already-opaque `context`.
# ===========================================================================
async def _test_contract_shape():
    result = await run_turn(
        problem="mujhe sar dard ho raha hai", raw_context=None, answers=None, free_text=None, profile="",
    )
    dumped = result.model_dump()
    check(
        "ConsultResult still has exactly the documented top-level keys",
        set(dumped.keys()) == {"kind", "condition", "message", "intake", "answer", "context", "sources"},
        sorted(dumped.keys()),
    )
    check(
        "help_type and missing_info live inside context, not as new top-level fields",
        "help_type" not in dumped and "missing_info" not in dumped
        and "help_type" in dumped["context"] and "missing_info" in dumped["context"],
        list(dumped["context"].keys()),
    )


asyncio.run(_test_contract_shape())


# ===========================================================================
# 11. THE PRODUCTION SHAPE. docs/api-contract.md tells clients to send
# `problem` whenever phase is outside CONSULTING, and `asking_focus` is
# outside it - so a contract-conformant client sends the focus reply as
# `problem`, not `freeText`. Every helper above (and try_it.py, and
# test_evidence.py) sends `freeText`, which is why this shape reached
# production unexercised: the reply was routed as a brand new message, got a
# generic "I am an AI wellness assistant..." answer, phase was reset to
# "casual", help_type stayed "", and the user was asked to describe the same
# complaint again. Both shapes must now reach the plan.
# ===========================================================================
async def _test_focus_reply_as_problem():
    turns = await run_to_focus("mujhe acidity ho rahi hai")
    _, focus_context = turns[-1]
    if focus_context.get("phase") != "asking_focus":
        check("PRECONDITION: reached asking_focus", False, focus_context.get("phase"))
        return

    condition_before = focus_context.get("condition")
    symptoms_before = list(focus_context.get("symptoms") or [])

    # The focus reply, sent the way the documented contract says to send it.
    result = await run_turn(
        problem="root cause and complete plan both",
        raw_context=focus_context,
        answers=None,
        free_text=None,
        profile="",
    )
    final = result.context.model_dump()

    check(
        "a focus reply sent as `problem` produces the PLAN, not a chat reply",
        result.kind == "answer",
        f"kind={result.kind} phase={final.get('phase')}",
    )
    check(
        "a focus reply sent as `problem` does NOT reset the phase to casual",
        final.get("phase") == "completed",
        final.get("phase"),
    )
    check(
        "a focus reply sent as `problem` resolves a help_type",
        bool(final.get("help_types")) and final.get("help_type") != "",
        f"help_types={final.get('help_types')} help_type={final.get('help_type')!r}",
    )
    check(
        "the condition survives a `problem`-shaped focus reply",
        final.get("condition") == condition_before and condition_before,
        f"before={condition_before!r} after={final.get('condition')!r}",
    )
    check(
        "the gathered symptoms survive a `problem`-shaped focus reply",
        list(final.get("symptoms") or []) == symptoms_before and symptoms_before,
        f"before={symptoms_before} after={final.get('symptoms')}",
    )
    check(
        "the answer is the sectioned plan, not generic onboarding prose",
        looks_like_plan(result.answer),
        result.answer[:160],
    )
    lowered = result.answer.lower()
    check(
        "the answer does NOT ask the user to describe their problem again",
        not any(
            phrase in lowered
            for phrase in (
                "describe any specific health problem",
                "describe your health problem",
                "what's troubling you",
                "apni problem likhiye",
                "apni samasya bataye",
            )
        ),
        result.answer[-200:],
    )


asyncio.run(_test_focus_reply_as_problem())


# ===========================================================================
# 12. MULTI-FOCUS. Asking for two categories at once is an ordinary answer to
# the focus question; collapsing it to one silently gave the user less than
# they asked for ("yoga and diet" became the complete six-section plan).
# ===========================================================================
async def _test_multi_focus_yoga_and_diet():
    turns = await run_full("mujhe acidity ho rahi hai", "yoga and diet dono bata do")
    result, final = turns[-1]
    if final.get("phase") != "completed":
        check("PRECONDITION: multi-focus turn completed", False, final.get("phase"))
        return

    help_types = final.get("help_types") or []
    check(
        "'yoga and diet dono' resolves BOTH focuses, not just one",
        set(help_types) == {"yoga", "diet"},
        help_types,
    )
    wanted = {SECTION_LIBRARY["yoga"][0], SECTION_LIBRARY["food"][0]}
    unwanted = {
        SECTION_LIBRARY[k][0] for k in ("root_cause", "changes", "routine")
    }
    present = {h for h in wanted | unwanted if h in result.answer}
    check(
        "the multi-focus plan contains BOTH requested sections",
        wanted <= present,
        f"wanted={wanted} present={present}",
    )
    check(
        "the multi-focus plan does NOT expand to the unrelated sections",
        not (unwanted & present),
        f"leaked={unwanted & present}",
    )


asyncio.run(_test_multi_focus_yoga_and_diet())


async def _test_multi_focus_including_complete():
    """"root cause and complete plan both" - complete is a superset, so this
    must give the whole plan rather than only Root Cause."""
    turns = await run_full("mujhe acidity ho rahi hai", "root cause and complete plan both")
    result, final = turns[-1]
    if final.get("phase") != "completed":
        check("PRECONDITION: complete-superset turn completed", False, final.get("phase"))
        return

    help_types = final.get("help_types") or []
    check(
        "'root cause and complete plan both' captures BOTH requests",
        "complete" in help_types and "root_cause" in help_types,
        help_types,
    )
    check(
        "'complete' wins for the legacy single-valued help_type",
        final.get("help_type") == "complete",
        final.get("help_type"),
    )
    present = [
        key for key in SECTION_LIBRARY if SECTION_LIBRARY[key][0] in result.answer
    ]
    check(
        "asking for root cause AND the complete plan yields the full plan",
        len(present) >= 5,
        f"sections present: {present}",
    )


asyncio.run(_test_multi_focus_including_complete())


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== intake: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, _ in results:
        if not ok:
            print(f"  - {name}")
sys.exit(0 if passed == len(results) else 1)
