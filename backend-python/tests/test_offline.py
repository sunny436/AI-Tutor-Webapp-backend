"""
The answer served when GraphRAG cannot be reached.

    python tests/test_offline.py

No network and no model: this is the path that has to work when everything else
is down, so its test must not depend on anything that can be down.

The thing being guarded is not "does it produce text". It is that a DEGRADED
answer is still a COMPLETE one — six sections, in the order the frontend renders
and the prompt asks GraphRAG for, with the safety guidance intact. A fallback
that quietly drops "When To See A Doctor" is worse than no fallback, because it
reads as a finished plan.
"""

from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from src.consult.offline import offline_answer, read_sections  # noqa: E402
from src.consult.sections import SECTION_LIBRARY  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


HEADINGS = [heading for heading, _ in SECTION_LIBRARY.values()]
NOTES = sorted(os.path.basename(p) for p in glob.glob(str(Path(config.KNOWLEDGE_DIR) / "*.md")))

print("\nevery note yields a complete plan")
check("there are notes to fall back on at all", len(NOTES) > 0, f"{len(NOTES)} notes")

incomplete = []
for note in NOTES:
    answer = offline_answer(note)
    missing = [h for h in HEADINGS if h not in answer]
    if not answer or missing:
        incomplete.append((note, missing))
check(
    f"all {len(NOTES)} notes render all six sections",
    not incomplete,
    "; ".join(f"{n}: {m}" for n, m in incomplete[:3]),
)

answer = offline_answer("constipation.md")

print("\norder, content and the two dropped headings")
positions = [answer.find(h) for h in HEADINGS]
check(
    "sections come out in SECTION_LIBRARY order",
    positions == sorted(positions) and -1 not in positions,
    str(positions),
)
check(
    "'## What It Is' is dropped — it defines, it does not advise",
    "What It Is" not in answer,
)
check(
    "'## Home Remedies' is folded in rather than dropped",
    "munakka" in answer or "anjeer" in answer,
)
# The reason it is folded in rather than dropped.
check(
    "and the no-self-medication line survives with it",
    "khud se na lein" in answer,
)
check(
    "the note's own '##' markup does not leak into the plan",
    "## " not in answer,
    answer[:60],
)

print("\nfailing safe")
check("a note that does not exist yields nothing, not a broken plan", offline_answer("no-such-note.md") == "")
check("read_sections on a missing file is empty, not an exception", read_sections("no-such-note.md") == {})

# ALWAYS_INCLUDED. A degraded answer missing this section reads as complete
# while having lost the one part that says to stop self-treating, so the whole
# answer is refused rather than served short.
import src.consult.offline as offline_module  # noqa: E402

real_read = offline_module.read_sections
try:
    offline_module.read_sections = lambda _f: {
        "Root Cause": "- something",
        "Changes To Make": "- something",
        "Yoga & Breathing": "- something",
        "Food Chart": "- something",
        "Daily Routine": "- something",
    }
    check(
        "a note with no 'When To See A Doctor' is refused outright",
        offline_module.offline_answer("whatever.md") == "",
    )
finally:
    offline_module.read_sections = real_read

passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== offline fallback: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}: {detail}")
sys.exit(0 if passed == len(results) else 1)
