"""
The answer we can still give when GraphRAG cannot be reached.

WHY THIS EXISTS

Until now a GraphRAG outage merely degraded us: the consultation completed and
said the notes did not cover the question. Once GraphRAG also WRITES the reply,
an outage would leave the product with nothing to say at all.

That is not hypothetical. On 2026-08-25 every retrieval endpoint returned 500
for most of a day — an expired model-provider credential on the vendor's side,
which we could neither see nor fix. `/health` stayed green throughout.

THE NOTES ALREADY SOLVE IT

All 29 files in `data/knowledge/` carry the same eight `##` headings, six of
which are exactly the sections `sections.SECTION_LIBRARY` defines and the
frontend renders as cards. So the fallback is a text transform, not a model:
find the note, read its sections, relabel them. No network, no LLM, no tokens.

`## Home Remedies` is folded into **Changes To Make** rather than dropped.
Both are things to do, and — more importantly — that section is where the
no-self-medication line lives:

    "Koi laxative churna, tablet ya brand khud se na lein — aadat pad jati hai."

Dropping it would quietly remove medicine-safety guidance from the answer given
in exactly the situation where nothing else is checking. `## What It Is` IS
dropped: it defines the condition rather than advising on it, and the six
sections are the contract.

WHAT THIS IS NOT

It is the textbook answer for a topic, not a plan for a person. Nothing the
intake gathered — how long, what triggers it — changes a word of it. And it
comes back in the note's own language, so someone who asked in Devanagari gets
Hinglish. Both are real downgrades, and both are enormously better than an
error page. Callers must log when they serve one, so a permanent silent
fallback cannot masquerade as a healthy service.
"""

from __future__ import annotations

from pathlib import Path

import config
from src.consult.sections import SECTION_LIBRARY

# Canonical heading -> the note headings that feed it, in order. Keyed off
# SECTION_LIBRARY so the six can never drift apart from what the prompt asks
# GraphRAG for and what the frontend parses.
_SOURCE_HEADINGS: dict[str, tuple[str, ...]] = {
    "root_cause": ("Root Cause",),
    "changes": ("Changes To Make", "Home Remedies"),
    "yoga": ("Yoga & Breathing",),
    "food": ("Food Chart",),
    "routine": ("Daily Routine",),
    "doctor": ("When To See A Doctor",),
}


def read_sections(filename: str) -> dict[str, str]:
    """`{heading: body}` for one note's `##` sections. Empty if unreadable."""
    path = Path(config.KNOWLEDGE_DIR) / filename
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as error:
        print(f"[offline] could not read {filename}: {error}")
        return {}

    sections: dict[str, list[str]] = {}
    heading = ""
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            sections.setdefault(heading, [])
        elif heading:
            sections[heading].append(line)
    return {name: "\n".join(body).strip() for name, body in sections.items()}


def offline_answer(filename: str) -> str:
    """The six sections of one note, rendered as the plan format.

    Returns "" when the note yields nothing usable, so the caller can tell the
    difference between "here is the degraded answer" and "there is nothing at
    all" rather than sending an empty plan.
    """
    sections = read_sections(filename)
    if not sections:
        return ""

    blocks: list[str] = []
    for key, (heading, _) in SECTION_LIBRARY.items():
        bodies = [
            sections[name].strip()
            for name in _SOURCE_HEADINGS.get(key, ())
            if sections.get(name, "").strip()
        ]
        if bodies:
            blocks.append(f"{heading}\n" + "\n".join(bodies))

    # "When To See A Doctor" is `sections.ALWAYS_INCLUDED`. A degraded answer
    # missing it is worse than no answer: it reads as a complete plan while
    # having dropped the one section that tells someone to stop self-treating.
    doctor_heading = SECTION_LIBRARY["doctor"][0]
    if not any(block.startswith(doctor_heading) for block in blocks):
        print(f"[offline] {filename} has no 'When To See A Doctor'; refusing to serve it")
        return ""

    return "\n\n".join(blocks)
