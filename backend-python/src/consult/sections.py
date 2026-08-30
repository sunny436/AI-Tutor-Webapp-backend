"""
consult/sections.py
-------------------
What the user gets at the end, and how they choose it.

After the condition questions are answered we don't jump straight to a wall of
text. The user is asked two things: whether they want to add anything, and which
parts of the plan they actually want. Someone who only wants a food chart
shouldn't have to scroll past a yoga routine to find it.

These six sections are a fixed product decision, not something the model should
invent — the headings are a contract with the UI, which colour-codes each one
(`answer-sections.tsx`). So this plan is built in code, unlike the condition
questions, which are generated per problem.
"""

from __future__ import annotations

from src.consult.schema import IntakePlan, Option, Question

# The question id the delivery choices are collected under. Prefixed so it can't
# collide with a model-generated question id.
SECTIONS_QUESTION_ID = "_sections"
EXTRA_QUESTION_ID = "_anything_else"
COMPLETE_OPTION_ID = "complete"

# id -> (heading exactly as the prompt must emit it, what to write under it)
SECTION_LIBRARY: dict[str, tuple[str, str]] = {
    "root_cause": (
        "**Root Cause**",
        "Explain, in simple words, the likely lifestyle reason behind the problem.",
    ),
    "changes": (
        "**Changes To Make**",
        "Simple do's and don'ts the user should follow.",
    ),
    "yoga": (
        "**Yoga & Breathing**",
        "A few suitable yoga asanas and pranayama/breathing exercises. Mention if "
        "any should be avoided for their condition.",
    ),
    "food": (
        "**Food Chart**",
        "Foods to eat and foods to avoid, based on Ayurveda.",
    ),
    "routine": (
        "**Daily Routine**",
        "A simple morning-to-night routine to fix the problem naturally.",
    ),
    "doctor": (
        "**When To See A Doctor**",
        "Clearly say which warning signs mean they must consult a doctor.",
    ),
}

# Always emitted, whatever the user picked. This is a wellness product giving
# advice about symptoms: the "when this is beyond self-care" guidance is not an
# optional extra, so selecting it is really about acknowledging it, not enabling it.
ALWAYS_INCLUDED = ("doctor",)

DEFAULT_SECTIONS = tuple(SECTION_LIBRARY.keys())


def delivery_plan(condition: str = "") -> IntakePlan:
    """The 'anything else / what do you want' step shown after the questions."""
    return IntakePlan(
        condition=condition,
        note="Almost done. Anything else to add, and what would you like me to cover?",
        questions=[
            Question(
                id=EXTRA_QUESTION_ID,
                label="Anything else you'd like to tell me?",
                hint="Optional — or just leave it blank",
                type="text",
            ),
            Question(
                id=SECTIONS_QUESTION_ID,
                label="What would you like in your plan?",
                hint="Pick what you need, or choose Complete plan for everything",
                type="multi",
                display="cards",
                options=[
                    Option(id=COMPLETE_OPTION_ID, label="Complete plan (everything)", emoji="✨"),
                    Option(id="root_cause", label="Root cause", emoji="🔍"),
                    Option(id="changes", label="Changes to make", emoji="✅"),
                    Option(id="food", label="Food chart", emoji="🍎"),
                    Option(id="yoga", label="Yoga & breathing", emoji="🧘"),
                    Option(id="routine", label="Daily routine", emoji="☀️"),
                    Option(id="doctor", label="When to see a doctor", emoji="🩺"),
                ],
            ),
        ],
    )


def resolve_sections(selected: list[str] | None) -> list[str]:
    """Turn the user's picks into the ordered list of headings to generate.

    Nothing selected means they skipped the step, which should give them
    everything rather than nothing.
    """
    chosen = [s for s in (selected or []) if s in SECTION_LIBRARY]

    if not selected or COMPLETE_OPTION_ID in (selected or []) or not chosen:
        return list(DEFAULT_SECTIONS)

    for required in ALWAYS_INCLUDED:
        if required not in chosen:
            chosen.append(required)

    # Keep the canonical order so the plan always reads the same way.
    return [s for s in DEFAULT_SECTIONS if s in chosen]


def render_section_spec(sections: list[str]) -> str:
    """The '**Heading**\\n(what to write)' block the answer prompt asks for."""
    return "\n\n".join(
        f"{SECTION_LIBRARY[s][0]}\n({SECTION_LIBRARY[s][1]})"
        for s in sections
        if s in SECTION_LIBRARY
    )


# How many of the six headings must be present before text counts as a plan.
# Two rather than one: a single heading can appear inside ordinary prose ("the
# root cause here is..."), but a reply carrying two of these exact strings, each
# alone on its line, is the sectioned format and nothing else.
_PLAN_HEADING_QUORUM = 2


def looks_like_plan(text: str) -> bool:
    """Is this text the sectioned plan format, rather than prose?

    Used to decide `kind`, which decides how the client renders it. The frontend
    shows `kind="chat"` as one plain paragraph with NO markdown handling, so a
    reworked plan returned as chat puts literal `**Root Cause**` asterisks on the
    user's screen. That is a real, reported bug, and `FOLLOWUP_PROMPT` rule 6 is
    what causes it: it tells the model to KEEP the bold headings when reworking a
    previous answer, so "explain this in English" reliably produces exactly the
    text this function has to recognise.

    Deliberately matched on whole lines, the same way `answer-sections.tsx`
    splits them. Checking `heading in text` would count a heading quoted in the
    middle of a sentence, which is prose and must stay prose.
    """
    if not text:
        return False
    lines = {line.strip() for line in text.splitlines()}
    headings = {heading for heading, _ in SECTION_LIBRARY.values()}
    return len(lines & headings) >= _PLAN_HEADING_QUORUM
