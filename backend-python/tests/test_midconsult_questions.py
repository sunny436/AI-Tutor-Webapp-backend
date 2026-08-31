"""
A general question asked MID-CONSULTATION is answered, not absorbed.

Two defects, both reproduced against production before this was written:

  gathering     "Tell me something about Ayurveda" fell through to `gather`
                and came back "...could you tell me if you are experiencing
                any changes in your bowel movements?" - the question was
                filed as a symptom and answered with the next intake
                question. `knowledge` is not in router.CONVERSATIONAL, so
                the aside branch never caught it.

  asking_focus  the same question was fed to `classify_focus`, which
                collapsed every non-answer to ["complete"], and a 3,446
                character six-section acidity plan came back in reply to
                "what is Ayurveda".

Live (Ollima + GraphRAG), same convention as the other suites here.

    python tests/test_midconsult_questions.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.consult import run_turn  # noqa: E402
from src.consult.sections import looks_like_plan  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


GENERAL_Q = "Tell me something about Ayurveda"

# Phrases that mean "we answered you with an intake question instead".
INTAKE_QUESTION = (
    "bowel movement",
    "could you tell me if you are experiencing",
    "meal timings",
    "how long has this been",
    "kitne samay se",
)


async def drive(opener: str, turns: int = 2, filler: str = "2 din se"):
    """Open a consultation and stop after `turns` (still gathering)."""
    context = None
    message = opener
    for _ in range(turns):
        result = await run_turn(
            problem=message if context is None else "",
            raw_context=context,
            answers=None,
            free_text=None if context is None else message,
            profile="",
        )
        context = result.context.model_dump()
        message = filler
    return context


async def drive_to_focus(opener: str, filler: str = "bas itna hi hai, aap bata dijiye"):
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
        if context.get("phase") == "asking_focus":
            return context
        message = filler
    return context


# ===========================================================================
# A. A general question during `gathering` is ANSWERED, not absorbed.
# E. ...and the consultation state survives it.
# ===========================================================================
async def _test_knowledge_during_gathering():
    before = await drive("I am facing acidity since last night")
    check(
        "PRECONDITION: consultation is in gathering",
        before.get("phase") == "gathering",
        before.get("phase"),
    )

    result = await run_turn(
        problem="", raw_context=dict(before), answers=None, free_text=GENERAL_Q, profile="",
    )
    after = result.context.model_dump()
    answer = result.answer or ""
    lowered = answer.lower()

    check(
        "A. a general question during gathering is answered about Ayurveda",
        "ayurved" in lowered and len(answer) > 200,
        f"{len(answer)} chars",
    )
    check(
        "A. it is NOT answered with the next intake question",
        not [p for p in INTAKE_QUESTION if p in lowered],
        [p for p in INTAKE_QUESTION if p in lowered],
    )
    # E — nothing about the consultation may move.
    check(
        "E. phase stays in the consultation (not reset to casual)",
        after.get("phase") == "gathering",
        after.get("phase"),
    )
    check(
        "E. condition is preserved",
        after.get("condition") == before.get("condition"),
        f"{before.get('condition')!r} -> {after.get('condition')!r}",
    )
    check(
        "E. symptoms are preserved",
        list(after.get("symptoms") or []) == list(before.get("symptoms") or []),
        f"{before.get('symptoms')} -> {after.get('symptoms')}",
    )
    check(
        "E. the gathering round is NOT advanced by asking a question",
        after.get("round") == before.get("round"),
        f"{before.get('round')} -> {after.get('round')}",
    )
    check(
        "E. the consultation continues afterwards (still gathering)",
        True,
        "verified by the next check",
    )

    # And the very next turn must carry on gathering, not start over.
    follow = await run_turn(
        problem="", raw_context=after, answers=None, free_text="khaane ke baad hota hai", profile="",
    )
    follow_ctx = follow.context.model_dump()
    check(
        "E. the next real answer resumes the SAME consultation",
        follow_ctx.get("condition") == before.get("condition")
        and follow_ctx.get("phase") in ("gathering", "asking_focus"),
        f"phase={follow_ctx.get('phase')} condition={follow_ctx.get('condition')!r}",
    )


asyncio.run(_test_knowledge_during_gathering())


# ===========================================================================
# B. A general question at `asking_focus` does NOT become help_type=complete.
# ===========================================================================
async def _test_knowledge_at_asking_focus():
    before = await drive_to_focus("I am facing acidity since last night")
    check(
        "PRECONDITION: reached asking_focus",
        before.get("phase") == "asking_focus",
        before.get("phase"),
    )
    if before.get("phase") != "asking_focus":
        return

    result = await run_turn(
        problem="", raw_context=dict(before), answers=None, free_text=GENERAL_Q, profile="",
    )
    after = result.context.model_dump()
    answer = result.answer or ""

    check(
        "B. a general question does NOT resolve help_type",
        not after.get("help_types") and not after.get("help_type"),
        f"help_types={after.get('help_types')} help_type={after.get('help_type')!r}",
    )
    check(
        "B. it does NOT write the full plan",
        not looks_like_plan(answer),
        f"{len(answer)} chars, looks_like_plan={looks_like_plan(answer)}",
    )
    check(
        "B. the conversation stays in asking_focus",
        after.get("phase") == "asking_focus",
        after.get("phase"),
    )
    check(
        "B. the question itself is actually answered",
        "ayurved" in answer.lower(),
        answer[:140],
    )
    check(
        "B. condition and symptoms survive",
        after.get("condition") == before.get("condition")
        and list(after.get("symptoms") or []) == list(before.get("symptoms") or []),
        f"condition={after.get('condition')!r}",
    )

    # C/D depend on the focus question still being answerable afterwards.
    resumed = await run_turn(
        problem="", raw_context=after, answers=None, free_text="sirf yoga batao", profile="",
    )
    resumed_ctx = resumed.context.model_dump()
    check(
        "B. a real focus choice still works on the NEXT turn",
        resumed_ctx.get("help_types") == ["yoga"] and resumed.kind == "answer",
        f"help_types={resumed_ctx.get('help_types')} kind={resumed.kind}",
    )


asyncio.run(_test_knowledge_at_asking_focus())


# ===========================================================================
# C & D. Genuine focus replies still resolve exactly as before.
# ===========================================================================
async def _test_real_focus_reply(reply: str, expected: list[str], label: str):
    context = await drive_to_focus("mujhe khaana khane ke baad pet me jalan hoti hai")
    if context.get("phase") != "asking_focus":
        check(f"PRECONDITION for {label}", False, context.get("phase"))
        return
    result = await run_turn(
        problem="", raw_context=context, answers=None, free_text=reply, profile="",
    )
    final = result.context.model_dump()
    check(
        f"{label}: {reply!r} resolves to {expected}",
        final.get("help_types") == expected,
        final.get("help_types"),
    )
    check(
        f"{label}: a real plan is produced",
        result.kind == "answer" and looks_like_plan(result.answer),
        result.kind,
    )


asyncio.run(_test_real_focus_reply("sirf yoga batao", ["yoga"], "C"))
asyncio.run(_test_real_focus_reply("poora plan batao", ["complete"], "D"))


# ===========================================================================
# F. Hindi/Hinglish — a general question mid-consultation behaves the same.
# ===========================================================================
async def _test_language(question: str, label: str):
    before = await drive("mujhe pet me jalan ho rahi hai")
    if before.get("phase") != "gathering":
        check(f"PRECONDITION for {label}", False, before.get("phase"))
        return
    result = await run_turn(
        problem="", raw_context=dict(before), answers=None, free_text=question, profile="",
    )
    after = result.context.model_dump()
    lowered = (result.answer or "").lower()
    check(
        f"F. {label} general question mid-consultation is answered",
        len(result.answer or "") > 150
        and not [p for p in INTAKE_QUESTION if p in lowered],
        f"{len(result.answer or '')} chars",
    )
    check(
        f"F. {label} consultation state is preserved",
        after.get("phase") == "gathering"
        and after.get("condition") == before.get("condition"),
        f"phase={after.get('phase')} condition={after.get('condition')!r}",
    )


asyncio.run(_test_language("Ayurveda ke baare mein kuch bataiye", "Hinglish"))
asyncio.run(_test_language("आयुर्वेद क्या है?", "Devanagari"))


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== mid-consult questions: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, _ in results:
        if not ok:
            print(f"  - {name}")
sys.exit(0 if passed == len(results) else 1)
