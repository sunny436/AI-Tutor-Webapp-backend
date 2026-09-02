"""
PHASE-4 — the response validator.

persona.txt, `response_validator`: fifteen checks, and a `failure_behavior`
that blocks the candidate, returns structured failures, regenerates against the
approved action and evidence set, and falls back conservatively.

WHY A VALIDATOR RATHER THAN MORE PROMPT TEXT. Everything this checks is already
instructed somewhere in a prompt, and every one of them has still been produced
at least once in this product's history: a plan written for a chemotherapy
patient, the same safety paragraph three turns running, a section the reader
explicitly excluded, "my notes do not cover that" said out loud. Instructions
are a request; this is the part that reads the output.

WHAT IT DOES NOT DO. It never rewrites. `failure_behavior` says block and
regenerate, and this product already learned that a regex quietly deleting part
of a health answer is worse than the thing it prevented — `evidence.py` and
`safety.names_medicine` both say so. So every check reports, the caller
regenerates once, and a conservative fallback is used if that fails too.

The checks are grouped by what they read, because that is what decides which
can run deterministically:
  - the PLAN vs the TEXT (did it do what it was told to do)
  - the TEXT alone (did it say something it must never say)
  - the TEXT vs the PATIENT (is this safe for this person)

Feature-flagged (`config.PHASE4_RESPONSE_VALIDATOR`), OFF by default.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# `response_validator.checks`, in the spec's own order. The ids are stable so
# failures can be counted per check in PHASE-7's evaluation.
CHECK_IDS: tuple[str, ...] = (
    "addresses_goal",
    "safety_before_routine",
    "no_irrelevant_information_requested",
    "proportionate_question_bundle",
    "no_repeated_known_question",
    "no_assumption_as_fact",
    "no_definitive_diagnosis",
    "calibrated_working_assessment_allowed",
    "stops_at_sufficiency",
    "claims_grounded_in_evidence",
    "citations_support_claims",
    "evidence_labels_distinct",
    "no_conflict_with_patient_context",
    "urgency_language_matches_decision",
    "provides_usable_next_step",
)


@dataclass
class Failure:
    check_id: str
    detail: str = ""

    def as_dict(self) -> dict:
        return {"check_id": self.check_id, "detail": self.detail}


@dataclass
class Verdict:
    approved: bool = True
    failures: list[Failure] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "approved": self.approved,
            "failures": [f.as_dict() for f in self.failures],
        }


# ---------------------------------------------------------------------------
# Text signatures. Each one is a phrasing that has actually been produced.
# ---------------------------------------------------------------------------

# `no_definitive_diagnosis`. Hedges are deliberately NOT accepted as cover:
# prompts.py already records that "ho sakta hai" in front of a claim does not
# stop the reader hearing the claim.
_DEFINITIVE = re.compile(
    r"\byou\s+(definitely\s+)?have\b(?!\s+(any|no|not))"
    r"|\baapko\s+(pakka|definitely|zaroor)\s+\w+\s+hai\b"
    r"|\bthis\s+is\s+(definitely|certainly|clearly)\s+\w+"
    r"|\bdiagnosed\s+with\b|\byou\s+are\s+suffering\s+from\b"
    r"|\bit\s+is\s+confirmed\b",
    re.IGNORECASE,
)

# `no_assumption_as_fact` — stating something about the person that was never
# said. Narrow on purpose: only the shapes that assert, not those that ask.
_ASSUMED = re.compile(
    r"\bsince\s+you\s+(are|have)\s+(?!not\b)"
    r"|\bas\s+you\s+mentioned\s+(?!earlier)"
    r"|\bbecause\s+you\s+(are|have)\s+(?!not\b)",
    re.IGNORECASE,
)

# `provides_usable_next_step`
#
# Imperatives AND the descriptive form. "Try resting in a dark room" and
# "resting in a dark room can help" leave the reader with exactly the same
# thing to do, and only the first has a command verb. Since a failure here
# BLOCKS the answer and forces a regeneration, a false failure costs the
# reader a worse answer than the one they would have had — so the plain
# action words are listed too. Kept to unambiguous actions: a generic verb
# like "use" would match almost any prose and quietly stop this check from
# catching an answer that really does leave the reader with nothing to do.
_NEXT_STEP = re.compile(
    r"\b(try|start|avoid|take|do|practice|kar(ein|iye|o)|lijiye|khaiye|"
    r"consult|see|contact|visit|monitor|watch|check|dikhaiye|poochiye|"
    r"call|go\s+to|repeat|recheck|rest|resting|sleep|drink|eat|apply|"
    r"reduce|limit|walk|walking)\b",
    re.IGNORECASE,
)

# `urgency_language_matches_decision`
_URGENT_LANGUAGE = re.compile(
    r"\b(right\s+away|immediately|urgent\w*|emergency|turant|abhi|"
    r"nearest\s+hospital|seek\s+medical\s+help)\b",
    re.IGNORECASE,
)
_ROUTINE_LANGUAGE = re.compile(
    r"\b(food\s+chart|daily\s+routine|dinacharya|recipe|long[\s-]term|"
    r"lifestyle\s+plan)\b",
    re.IGNORECASE,
)

# `evidence_labels_distinct` — traditional use must not be dressed as proof.
# `acceptance_criteria` 14: "Traditional use is never presented as established
# clinical effectiveness."
_TRADITION_AS_PROOF = re.compile(
    r"\b(traditionally|classical\w*|ayurveda\s+says|ancient)\b[^.?!\n]{0,60}"
    r"\b(proven|clinically\s+proven|scientifically\s+proven|evidence\s+shows|"
    r"studies\s+prove|guaranteed)\b"
    r"|\b(proven|scientifically\s+proven)\b[^.?!\n]{0,40}\b(ayurved|traditional)\w*",
    re.IGNORECASE,
)

_CURE_CLAIM = re.compile(
    r"\b(will\s+cure|completely\s+cures?|guaranteed\s+cure|permanent(ly)?\s+cure|"
    r"theek\s+ho\s+jayega\s+pakka|100%)\b",
    re.IGNORECASE,
)


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def validate(
    reply: str,
    plan,
    *,
    transcript: str = "",
    profile_conditions: list[str] | None = None,
    profile_medications: list[str] | None = None,
    has_evidence: bool = False,
    cited_sources: list[str] | None = None,
) -> Verdict:
    """Run the fifteen checks. Reports; never rewrites."""
    body = reply or ""
    verdict = Verdict()

    def fail(check_id: str, detail: str = "") -> None:
        verdict.approved = False
        verdict.failures.append(Failure(check_id, detail[:160]))

    action = getattr(plan, "next_action", "answer")
    prohibited = set(getattr(plan, "prohibited_output_actions", []) or [])
    safety_status = getattr(plan, "safety_status", "routine")
    sufficiency = getattr(plan, "current_sufficiency", "insufficient")
    asked_ids = list(getattr(plan, "next_question_ids", []) or [])
    known = set(getattr(plan, "known_decision_relevant_facts", []) or [])

    # --- the plan versus the text -----------------------------------------
    if not body.strip():
        fail("addresses_goal", "empty response")
        return verdict

    # `safety_before_routine` and `urgency_language_matches_decision`.
    if safety_status == "emergency":
        if not _URGENT_LANGUAGE.search(body):
            fail("urgency_language_matches_decision",
                 "emergency decided but the reply reads as routine")
        if _ROUTINE_LANGUAGE.search(body):
            fail("safety_before_routine",
                 (_ROUTINE_LANGUAGE.search(body) or [""])[0])
    elif safety_status in ("routine", "no_current_signal") and _URGENT_LANGUAGE.search(body):
        # Over-escalation is a tracked failure too — `safety_engine.behavior`:
        # "Do not over-escalate every uncertain symptom solely to improve
        # safety metrics."
        fail("urgency_language_matches_decision",
             "urgent language on a routine decision")

    # `stops_at_sufficiency` — an answer was owed, a question was returned.
    question_count = body.count("?")
    if action == "answer" and question_count > 1:
        fail("stops_at_sufficiency", f"{question_count} questions when an answer was due")
    if sufficiency == "sufficient_for_education" and question_count > 1:
        fail("no_irrelevant_information_requested",
             "education is sufficient, yet information was requested")

    # `proportionate_question_bundle`
    if action == "ask" and question_count > 3:
        fail("proportionate_question_bundle", f"{question_count} questions in one turn")

    # `no_repeated_known_question`
    for field_name in known:
        if field_name in asked_ids:
            fail("no_repeated_known_question", field_name)

    # --- the text alone ----------------------------------------------------
    if _DEFINITIVE.search(body):
        fail("no_definitive_diagnosis", (_DEFINITIVE.search(body) or [""])[0])
    if _CURE_CLAIM.search(body):
        fail("no_definitive_diagnosis", (_CURE_CLAIM.search(body) or [""])[0])
    if _TRADITION_AS_PROOF.search(body):
        fail("evidence_labels_distinct", (_TRADITION_AS_PROOF.search(body) or [""])[0])
    if _ASSUMED.search(body) and not transcript:
        fail("no_assumption_as_fact", (_ASSUMED.search(body) or [""])[0])

    # `claims_grounded_in_evidence` / `citations_support_claims`. A citation
    # with nothing retrieved behind it is the failure; the reverse is fine.
    if cited_sources and not has_evidence:
        fail("citations_support_claims", "cited a source with no retrieval behind it")

    # `provides_usable_next_step` — only owed when something was answered.
    if action in ("answer", "escalate") and not _NEXT_STEP.search(body):
        fail("provides_usable_next_step", "no actionable step offered")

    # Prohibited output actions the plan set, checked as text.
    if "wellness_plan" in prohibited and re.search(
        r"\*\*(Root Cause|Food Chart|Daily Routine|Changes To Make)\*\*", body, re.I
    ):
        fail("no_conflict_with_patient_context", "wellness plan issued despite prohibition")
    if "full_intake" in prohibited and question_count > 3:
        fail("no_irrelevant_information_requested", "intake issued despite prohibition")

    # --- the text versus the patient ---------------------------------------
    # `no_conflict_with_patient_context`. Reuses the reviewed interaction table
    # rather than inventing rules here — `clinical_content_governance`.
    if profile_conditions or profile_medications:
        from src.clinical import interactions

        for v in interactions.screen_text(
            body,
            medications=list(profile_medications or []),
            conditions=list(profile_conditions or []),
        ):
            if v.blocked:
                fail("no_conflict_with_patient_context",
                     f"{v.intervention}: {'; '.join(v.reasons)}")

    return verdict


def conservative_fallback(plan, language: str = "") -> str:
    """`failure_behavior`: "Use a conservative fallback if regeneration fails."

    Deliberately not a cheerful apology. It says what is true — that a careful
    answer could not be produced this turn — and keeps the safety instruction
    if one was owed, because that is the part that must survive a failure.
    """
    if getattr(plan, "safety_status", "routine") == "emergency":
        from src import safety

        return safety.ESCALATION_MESSAGE
    return (
        "Main is baare mein abhi theek se jawab nahi de pa raha. "
        "Thoda dobara bataiye ki aap kya jaanna chahte hain, ya apne doctor se "
        "ek baar zaroor poochh lijiye."
    )
