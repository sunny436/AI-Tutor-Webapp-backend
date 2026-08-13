"""
tests/test_continuation.py
--------------------------
"Tell me more" must ADD, not repeat.

    python tests/test_continuation.py

The bug this pins down, reproduced verbatim before the fix:

    what is ashwagandha?  ->  "Ashwagandha is a root-based herb widely used..."
    tell me more          ->  "Ashwagandha is a root-based herb widely used..."

Both phrasings matched `is_followup_request` and both went to `rework_answer`,
whose prompt says to work ONLY from the previous answer and introduce no new
facts. Correct for "say that in English"; exactly wrong for a request for more.

Live calls, deliberately. The whole failure was a prompt doing what it was told,
so a mocked model would have passed while the product stayed broken.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.consult.graph import run_turn  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((PASS if ok else FAIL, name, detail))
    print(f"[{PASS if ok else FAIL}] {name}" + (f"  -  {detail}" if detail else ""))


def _sentences(text: str) -> set[str]:
    """Normalised sentences, for measuring how much of an answer came back."""
    cleaned = re.sub(r"\s+", " ", (text or "").lower())
    return {s.strip() for s in re.split(r"[.!?\n]+", cleaned) if len(s.strip()) >= 25}


def overlap(a: str, b: str) -> float:
    """Fraction of the FIRST answer's sentences that reappear in the second."""
    first, second = _sentences(a), _sentences(b)
    if not first:
        return 0.0
    return len(first & second) / len(first)


async def main() -> int:
    # --- 1e: a continuation must bring new material -------------------------
    first = await run_turn(
        problem="what is ashwagandha?", raw_context=None, answers=None, free_text=None
    )
    check(
        "a knowledge question is answered",
        first.kind == "chat" and len(first.answer) > 120,
        f"kind={first.kind} chars={len(first.answer)}",
    )

    more = await run_turn(
        problem="tell me more",
        raw_context=first.context.model_dump(),
        answers=None,
        free_text=None,
    )
    repeated = overlap(first.answer, more.answer)
    check(
        "'tell me more' does not repeat the previous answer",
        repeated < 0.34,
        f"{repeated:.0%} of the first answer's sentences came back verbatim",
    )
    check(
        "'tell me more' actually says something",
        len(more.answer) > 120,
        f"chars={len(more.answer)}",
    )

    # --- 1f: a continuation with nothing to continue -------------------------
    cold = await run_turn(
        problem="tell me more", raw_context=None, answers=None, free_text=None
    )
    refused = re.search(
        r"only (help|answer|talk|discuss)|sirf .*(ayurveda|yoga)|can'?t help with",
        cold.answer,
        re.IGNORECASE,
    )
    check(
        "'tell me more' as the first message is not refused as off-topic",
        not refused,
        (cold.answer or "")[:90],
    )
    check(
        "...it asks what about instead",
        "?" in (cold.answer or ""),
        (cold.answer or "")[:90],
    )

    # --- the rework path must still rework -----------------------------------
    english = await run_turn(
        problem="explain this in English",
        raw_context=first.context.model_dump(),
        answers=None,
        free_text=None,
    )
    check(
        "'explain this in English' still re-presents the SAME answer",
        len(english.answer) > 80,
        f"chars={len(english.answer)}",
    )

    short = await run_turn(
        problem="summarise that",
        raw_context=first.context.model_dump(),
        answers=None,
        free_text=None,
    )
    check(
        "'summarise that' is still shorter than what it summarises",
        len(short.answer) < len(first.answer),
        f"{len(short.answer)} vs {len(first.answer)} chars",
    )

    failures = sum(1 for status, _, _ in results if status == FAIL)
    print(f"\n{len(results) - failures}/{len(results)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
