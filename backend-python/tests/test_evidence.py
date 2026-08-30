"""
Section-level evidence policy: partial grounding, no internal-term leaks.
Matches how test_reversal.py/test_intake.py already verify this session's
changes against the real orchestrator — unit checks against
consult.evidence directly, live checks against write_plan/run_turn.

    python tests/test_evidence.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src import safety  # noqa: E402
from src.consult import evidence  # noqa: E402
from src.consult.responder import write_plan  # noqa: E402
from src.consult.schema import ConsultContext  # noqa: E402
from src.consult.graph import run_turn  # noqa: E402
from src.retrieval.base import Chunk, RetrievalResult  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


def _kb_chunk(heading: str, body: str = "some content") -> Chunk:
    return Chunk(text=f"{heading}\n{body}", source="knowledge:acidity.md", score=0.8)


def _graph_chunk(text: str) -> Chunk:
    return Chunk(text=text, source="graphrag:acidity.md", score=0.7)


def _graph_edges_chunk() -> Chunk:
    return Chunk(
        text="Extracted relationships (automatically generated; may not be "
        "accurate, do not state as settled fact):\nYoga — helps with — Acidity",
        source="graphrag:graph",
    )


def _report_chunk(text: str) -> Chunk:
    return Chunk(text=text, source="report:labs.txt", score=0.5)


def _results(*chunks: Chunk, section: str = "Trusted Ayurveda / Yoga knowledge") -> list[RetrievalResult]:
    return [RetrievalResult(section=section, chunks=tuple(chunks))]


# ===========================================================================
# 1. Yoga exists, Diet missing
# ===========================================================================
check(
    "yoga has knowledge: evidence, food has none",
    evidence.evaluate_sections(
        ["yoga", "food"], _results(_kb_chunk("## Yoga & Breathing", "Asanas: Vajrasana."))
    )
    == {"yoga": True, "food": False},
)

# ===========================================================================
# 2. Diet exists, Yoga missing
# ===========================================================================
check(
    "food has knowledge: evidence, yoga has none",
    evidence.evaluate_sections(
        ["yoga", "food"], _results(_kb_chunk("## Food Chart", "Eat: moong dal."))
    )
    == {"yoga": False, "food": True},
)

# ===========================================================================
# 3. Root cause exists, another requested section has only a graphrag:graph
#    relationship-edge chunk (must NOT count — unverified structure, not prose)
# ===========================================================================
check(
    "graphrag:graph relationship edges never count as section evidence",
    evidence.evaluate_sections(
        ["root_cause", "routine"],
        _results(_kb_chunk("## Root Cause", "Agni asantulan."), _graph_edges_chunk()),
    )
    == {"root_cause": True, "routine": False},
)

# ===========================================================================
# 4. Complete plan, partial evidence across all six sections
# ===========================================================================
_complete = evidence.evaluate_sections(
    ["root_cause", "changes", "yoga", "food", "routine", "doctor"],
    _results(
        _kb_chunk("## Root Cause", "text"),
        _kb_chunk("## Yoga & Breathing", "text"),
        _graph_chunk("Some passage that discusses food chart eat avoid."),
    ),
)
check(
    "complete plan: mixed evidence dict is exactly as expected",
    _complete
    == {
        "root_cause": True,
        "changes": False,
        "yoga": True,
        "food": True,  # via graphrag: keyword match ("food chart")
        "routine": False,
        "doctor": False,
    },
    _complete,
)

# ===========================================================================
# 5. No evidence anywhere — empty results, and report:/memory:-only results
# ===========================================================================
check(
    "empty retrieval -> every requested section has no evidence",
    evidence.evaluate_sections(["yoga", "food", "doctor"], [])
    == {"yoga": False, "food": False, "doctor": False},
)
check(
    "report:/memory: chunks never count as Ayurveda-content evidence",
    evidence.evaluate_sections(
        ["food"],
        _results(_report_chunk("Diet notes: low fibre, eat more food."))
        + [RetrievalResult(section="Earlier consultations", chunks=(Chunk(text="food chart discussed", source="memory:abc"),))],
    )
    == {"food": False},
)

# ===========================================================================
# 6a. find_leaked_terms: unit check against synthetic strings
# ===========================================================================
for term in evidence.LEAKED_TERMS:
    sample = f"Some answer text mentioning {term} in passing."
    check(f"find_leaked_terms detects {term!r}", bool(evidence.find_leaked_terms(sample)))

check(
    "find_leaked_terms returns nothing for a clean answer",
    evidence.find_leaked_terms(
        "Root Cause: this often comes from eating late and spicy food. "
        "Try eating dinner earlier and drinking warm water in the morning."
    )
    == [],
)


# ===========================================================================
# 6b (live). A fully ungrounded plan never leaks internal terms and never
# names a specific herb/branded item.
# ===========================================================================
async def _test_ungrounded_plan_no_leak():
    answer = await write_plan(
        knowledge="",  # nothing retrieved at all
        profile="",
        details="User has mild, vague discomfort, first time mentioning it.",
        sections=["root_cause", "yoga", "food"],
        language="english",
        section_evidence={"root_cause": False, "yoga": False, "food": False},
    )
    leaked = evidence.find_leaked_terms(answer)
    check(
        "a fully ungrounded live plan contains no leaked internal terms",
        leaked == [],
        f"leaked={leaked} answer[:200]={answer[:200]!r}",
    )
    check(
        "a fully ungrounded live plan names no specific herb/brand/dose",
        not safety.names_medicine(answer),
        safety.names_medicine(answer),
    )
    check(
        "a fully ungrounded live plan is still a real generated plan",
        len(answer) > 100 and "Root Cause" in answer,
        answer[:150],
    )


asyncio.run(_test_ungrounded_plan_no_leak())


# ===========================================================================
# 8 (live). Ollima still generates the final answer, with the new
# evidence-aware prompt, when a section IS supported.
# ===========================================================================
async def _test_supported_section_generates_from_evidence():
    answer = await write_plan(
        knowledge=(
            "--- TRUSTED AYURVEDA / YOGA KNOWLEDGE ---\n"
            "## Yoga & Breathing\n"
            "Asanas: Vajrasana after meals, Pawanmuktasana, Shitali pranayama for cooling."
        ),
        profile="",
        details="User has acidity after meals for two weeks.",
        sections=["yoga"],
        language="english",
        section_evidence={"yoga": True},
    )
    check(
        "a supported-section plan is generated prose reflecting the evidence",
        "Vajrasana" in answer or "Shitali" in answer or "pranayama" in answer.lower(),
        answer[:200],
    )
    check(
        "a supported-section plan also contains no leaked internal terms",
        evidence.find_leaked_terms(answer) == [],
        evidence.find_leaked_terms(answer),
    )


asyncio.run(_test_supported_section_generates_from_evidence())


# ===========================================================================
# 9. Existing NO_KNOWLEDGE/abstention behaviour for OTHER callers (write_
# knowledge's continuation/document path) is untouched — knowledge_for_prompt
# with the default include_sentinel=True still returns the sentinel.
# ===========================================================================
from src.consult.graph import knowledge_for_prompt  # noqa: E402
from src.retrieval.pipeline import RetrievalPipeline  # noqa: E402
from src.consult.responder import NO_KNOWLEDGE  # noqa: E402


check(
    "knowledge_for_prompt still prefixes NO_KNOWLEDGE by default (untouched callers)",
    knowledge_for_prompt(RetrievalPipeline, []) == NO_KNOWLEDGE,
)
check(
    "knowledge_for_prompt(include_sentinel=False) never returns the sentinel text",
    knowledge_for_prompt(RetrievalPipeline, [], include_sentinel=False) == "",
)


# ===========================================================================
# 10 (live). Hindi/Hinglish plan, partial evidence, no leaked terms.
# ===========================================================================
async def run_to_focus(opener: str, filler: str = "bas itna hi hai, aap bata dijiye"):
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
        if context.get("phase") == "asking_focus" or result.kind in ("answer", "escalation", "error"):
            return result, context
        message = filler
    return result, context


async def _test_hinglish_plan_no_leak():
    _, context = await run_to_focus("mujhe khaana khane ke baad pet me jalan hoti hai")
    if context.get("phase") != "asking_focus":
        check("Hinglish flow reaches asking_focus (precondition for this test)", False, context.get("phase"))
        return
    final = await run_turn(
        problem="", raw_context=context, answers=None, free_text="poora plan bata dijiye", profile="",
    )
    check(
        "Hinglish complete-plan reaches a real answer",
        final.kind == "answer",
        final.kind,
    )
    leaked = evidence.find_leaked_terms(final.answer)
    check(
        "Hinglish plan contains no leaked internal terms",
        leaked == [],
        f"leaked={leaked}",
    )


asyncio.run(_test_hinglish_plan_no_leak())


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== evidence: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, _ in results:
        if not ok:
            print(f"  - {name}")
sys.exit(0 if passed == len(results) else 1)
