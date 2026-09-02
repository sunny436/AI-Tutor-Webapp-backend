"""
PHASE-6 — the patient-facing response modes.

persona.txt, `patient_facing_response_policy.response_modes`: six modes, each
with its own structure. This module turns a TurnPlan into the instruction that
shapes the reply — one mode per turn, chosen by the plan, never blended.

WHY MODES RATHER THAN ONE PROMPT. The product currently has one plan shape —
six fixed sections — and every substantial answer is bent into it. That is why
"My eGFR is 50" came back as Ayurvedic lifestyle guidance: there was no other
shape for an answer to take. `prohibited_patterns` names the same failure from
the other side: "Using Ayurveda language to avoid answering a modern safety
concern."

The six sections are NOT deleted. `working_assessment` is a different shape for
a different situation, and the existing plan path still serves the goals it
always served. This adds the shapes that were missing.

THE MODE IS CHOSEN BY THE PLAN, NOT BY THE MODEL. `internal_turn_plan` sets
`allowed_output_types`, and the model is handed exactly one structure. A model
that can pick its own shape picks the one it has produced most often, which is
the six-section plan, which is the failure.

Feature-flagged (`config.PHASE6_RESPONSE_MODES`), OFF by default.
"""

from __future__ import annotations

MODES: tuple[str, ...] = (
    "direct_education",
    "adaptive_question",
    "working_assessment",
    "report_explanation",
    "urgent_escalation",
    "evidence_comparison",
)

# `patient_facing_response_policy.identity` and `.tone`, verbatim.
IDENTITY = "AI health-intake and education assistant"
TONE = ("Natural", "Empathetic", "Calm", "Direct", "Respectful",
        "Clinically focused", "Non-judgmental")

# `patient_facing_response_policy.prohibited_patterns`, verbatim. Carried into
# every mode because they are failures of the whole reply, not of one shape.
PROHIBITED = (
    "Endless questioning without a checkpoint.",
    "Generic questions unrelated to the user's goal.",
    "Long differential-diagnosis dumps.",
    "False certainty.",
    "Constant repetitive disclaimers.",
    "Pretending to be a licensed doctor.",
    "Promising cure.",
    "Presenting symptom worsening as detoxification.",
    "Using Ayurveda language to avoid answering a modern safety concern.",
    "Advising independent discontinuation of prescribed medicines.",
    "Inventing citations, interactions, doses or study findings.",
)

# The structures, exactly as `response_modes` gives them.
STRUCTURE: dict[str, tuple[str, ...]] = {
    "direct_education": (
        "Answer the question",
        "Explain important limitations",
        "Offer personalization only if useful",
    ),
    "adaptive_question": (
        "Brief acknowledgment",
        "Short explanation of why the information matters",
        "One question or compact related bundle",
    ),
    "working_assessment": (
        "What is understood",
        "Most plausible categories",
        "Important alternative to exclude",
        "What remains uncertain",
        "Recommended next step",
        "Safety-net instructions",
    ),
    "report_explanation": (
        "Key findings",
        "What appears normal",
        "What needs context",
        "Trend when available",
        "Suggested next discussion or test",
    ),
    "urgent_escalation": (
        "Clear urgency statement",
        "Reason for concern",
        "Immediate action",
        "What not to delay",
        "Location-appropriate emergency guidance",
    ),
    "evidence_comparison": (
        "Modern medical evidence",
        "Ayurveda or complementary perspective",
        "Where evidence agrees",
        "Where evidence differs",
        "Safety considerations",
        "Practical next step",
    ),
}

# How much room each shape needs. A definition does not need six paragraphs,
# and `patient_facing_response_policy` forbids long dumps.
_LENGTH = {
    "direct_education": "Under 140 words.",
    "adaptive_question": "Under 60 words.",
    "working_assessment": "Under 220 words.",
    "report_explanation": "Under 200 words.",
    "urgent_escalation": "Under 90 words.",
    "evidence_comparison": "Under 220 words.",
}


def choose(plan) -> str:
    """The one mode this turn is allowed to use, from the plan."""
    allowed = list(getattr(plan, "allowed_output_types", []) or [])
    for candidate in allowed:
        if candidate in STRUCTURE:
            return candidate
    action = getattr(plan, "next_action", "answer")
    if action == "escalate":
        return "urgent_escalation"
    if action == "ask" or action == "clarify_goal":
        return "adaptive_question"
    if getattr(plan, "current_goal", "") == "report_explanation":
        return "report_explanation"
    if getattr(plan, "current_sufficiency", "") == "sufficient_for_education":
        return "direct_education"
    return "working_assessment"


def instruction(mode: str, *, questions: str = "", language: str = "") -> str:
    """The shaping instruction for one reply. No persona text beyond the spec.

    Everything here comes from `patient_facing_response_policy`; nothing is
    inherited from the previous persona, per the replacement instruction.
    """
    if mode not in STRUCTURE:
        mode = "direct_education"

    parts = [
        f"You are an {IDENTITY}.",
        "Tone: " + ", ".join(TONE).lower() + ".",
        "",
        f"WRITE IN: {language or 'the same language and script the user wrote in'}.",
        "",
        "COVER THESE, in this order, as flowing prose. Do NOT print them as "
        "headings, labels or a numbered list:",
    ]
    parts += [f"  {i}. {step}" for i, step in enumerate(STRUCTURE[mode], 1)]

    if mode == "adaptive_question" and questions:
        parts += [
            "",
            "ASK EXACTLY THIS, and nothing more:",
            questions,
            "Do not add any other question, and do not restate what you already know.",
        ]

    if mode == "working_assessment":
        parts += [
            "",
            "Calibrate every possibility. Say 'may', 'can', 'often' or 'is "
            "sometimes associated with' — never 'is' or 'definitely'. Name at "
            "most two or three categories, and never present them as a list to "
            "choose from.",
        ]

    if mode == "evidence_comparison":
        parts += [
            "",
            "Keep the two evidence types separate and labelled as what they "
            "are. Traditional use is traditional use; it is never described as "
            "clinically proven.",
        ]

    parts += [
        "",
        _LENGTH.get(mode, "Keep it short."),
        "",
        "NEVER:",
    ]
    parts += [f"  - {p}" for p in PROHIBITED]
    return "\n".join(parts)


def render_plan_context(plan) -> str:
    """What the writer is allowed to know about the plan. Never the reasoning.

    `reasoning_privacy`: reason codes, rule ids and question purposes are for
    the log, not for the prompt and not for the reader.
    """
    lines = []
    goal = getattr(plan, "current_goal", "")
    if goal:
        lines.append(f"What they want from this exchange: {goal.replace('_', ' ')}")
    subject = getattr(plan, "subject", "unknown")
    if subject and subject != "unknown":
        lines.append(f"Who this is about: {subject.replace('_', ' ')}")
    known = list(getattr(plan, "known_decision_relevant_facts", []) or [])
    if known:
        lines.append(
            "Already known — do not ask again: " + ", ".join(known[:8]).replace("_", " ")
        )
    return "\n".join(lines)
