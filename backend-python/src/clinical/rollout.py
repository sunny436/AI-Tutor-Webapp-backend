"""
clinical/rollout.py
-------------------
PHASE-8 — controlled rollout.

persona.txt, `implementation_phases` PHASE-8 deliverables: feature flags,
shadow evaluation, clinician review mode, limited user cohort, dashboards,
rollback controls. Acceptance criterion 19: "Critical behavior is
feature-flagged, observable and reversible."

WHY THIS EXISTS AS A MODULE. PHASES 1-6 built a second decision pipeline that
currently decides nothing: the flags are off, and off means off. That is the
right default and also a trap — a pipeline nobody can observe is a pipeline
nobody can ever gain the confidence to enable, so it stays off forever and the
work is wasted. Shadow evaluation is the way out. With the flags off the new
pipeline still RUNS, on real traffic, and writes down what it WOULD have done;
what the user sees is produced entirely by the existing code, untouched.

THE ONE RULE THIS MODULE MUST NEVER BREAK: when the flags are off, the bytes
the user receives must be identical to what they would have been if this
module did not exist. Every entry point below is therefore wrapped so that a
failure inside the shadow pipeline is swallowed and logged, never raised. A
crash in an observability path that takes down a health consultation would be
a far worse bug than the one it was added to find.

    from src.clinical import rollout
    rollout.shadow_turn(text="...", context=..., principal=...)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field

import config

from . import evidence as ev
from . import intent as it
from . import modes as md
from . import problems as pr
from . import turnplan as tp
from . import validator as va

log = logging.getLogger("clinical.rollout")

# The name every shadow record is logged under, so a dashboard can select on
# one string rather than parsing free text.
SHADOW_EVENT = "clinical_shadow_turn"


# ===========================================================================
# Rollback control
#
# ONE switch that beats every other switch. If the new pipeline ever has to be
# taken out of production in a hurry, the person doing it at 3am should not
# have to reason about six independent flags and their interactions.
# ===========================================================================
def kill_switch_engaged() -> bool:
    """True when CLINICAL_PIPELINE_DISABLED is set, whatever the flags say."""
    return bool(getattr(config, "CLINICAL_PIPELINE_DISABLED", False))


def active_flags() -> dict[str, bool]:
    """Every phase flag and its live value — the thing a dashboard shows."""
    return {
        "PHASE1_INTENT_ROUTER": config.PHASE1_INTENT_ROUTER,
        "PHASE2_PROBLEM_MODEL": config.PHASE2_PROBLEM_MODEL,
        "PHASE3_TURN_PLAN": config.PHASE3_TURN_PLAN,
        "PHASE4_RESPONSE_VALIDATOR": config.PHASE4_RESPONSE_VALIDATOR,
        "PHASE5_EVIDENCE_ORCHESTRATION": config.PHASE5_EVIDENCE_ORCHESTRATION,
        "PHASE6_RESPONSE_MODES": config.PHASE6_RESPONSE_MODES,
    }


def any_phase_live() -> bool:
    """Is the new pipeline allowed to change ANYTHING the user sees?"""
    return (not kill_switch_engaged()) and any(active_flags().values())


# ===========================================================================
# Limited user cohort
#
# Deterministic on the user id, so a person's experience does not flicker
# between turns of the same conversation — which would be both confusing and
# useless to measure.
# ===========================================================================
def in_cohort(user_id: str | None) -> bool:
    """Is this user inside the rollout percentage?"""
    percent = int(getattr(config, "CLINICAL_COHORT_PERCENT", 0) or 0)
    if percent <= 0:
        return False
    if percent >= 100:
        return True
    if not user_id:
        return False
    # Stable bucket. `hash()` is salted per process and would move a user
    # between cohorts on every restart, so it must not be used here.
    digest = 0
    for ch in str(user_id):
        digest = (digest * 31 + ord(ch)) & 0xFFFFFFFF
    return (digest % 100) < percent


def enabled_for(user_id: str | None = None) -> bool:
    """The single question every caller should ask before changing behaviour."""
    if not any_phase_live():
        return False
    percent = int(getattr(config, "CLINICAL_COHORT_PERCENT", 0) or 0)
    if percent <= 0:
        # Flags on but no cohort configured: still nobody. Turning a flag on
        # must not silently mean "everybody" — that is the accident this
        # function exists to make impossible.
        return False
    return in_cohort(user_id)


# ===========================================================================
# The shadow record — what a dashboard reads
# ===========================================================================
@dataclass
class ShadowRecord:
    """What the new pipeline WOULD have done, for one turn."""

    conversation_id: str = ""
    goal: str = ""
    goal_confidence: float = 0.0
    subject: str = "unknown"
    interaction_mode: str = "standard"
    reason_codes: list[str] = field(default_factory=list)
    problem_count: int = 0
    priority_problem: str = ""
    action: str = ""
    response_mode: str = ""
    next_question_ids: list[str] = field(default_factory=list)
    known_facts: list[str] = field(default_factory=list)
    evidence_question_type: str = ""
    evidence_lanes: list[str] = field(default_factory=list)
    evidence_conflicts: int = 0
    validator_approved: bool | None = None
    validator_failures: list[str] = field(default_factory=list)
    flags: dict = field(default_factory=dict)
    cohort: bool = False
    shadow_only: bool = True
    duration_ms: int = 0
    error: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _safe(value, default=""):
    return value if value is not None else default


def evaluate(text: str, *, transcript: str = "", safety_status: str = "none",
             chunks=None, answer: str = "", profile_medications=None,
             conversation_id: str = "") -> ShadowRecord:
    """Run the whole PHASE-1..6 pipeline and report what it decided.

    Pure: reads nothing global, writes nothing, changes nothing. The caller
    decides whether to log it, act on it, or throw it away.
    """
    started = time.monotonic()
    record = ShadowRecord(conversation_id=conversation_id,
                          flags=active_flags())
    try:
        goal = it.classify(text)
        record.goal = goal.goal
        record.goal_confidence = float(goal.confidence)
        record.subject = goal.subject
        record.interaction_mode = it.detect_mode(text)
        record.reason_codes = list(goal.reason_codes)

        case = pr.build(text, goal=goal.goal, subject=goal.subject)
        record.problem_count = len(case.problems)
        if case.problems:
            record.priority_problem = _safe(case.problems[0].patient_description)

        plan = tp.plan(goal=goal.goal, goal_confidence=goal.confidence,
                       subject=goal.subject, case=case,
                       transcript=transcript or text,
                       safety_status=safety_status)
        record.action = _safe(plan.next_action)
        record.next_question_ids = list(plan.next_question_ids)
        record.known_facts = list(plan.known_decision_relevant_facts)
        record.response_mode = md.choose(plan)

        evidence_set = ev.orchestrate(chunks or [], goal=goal.goal, text=text)
        record.evidence_question_type = evidence_set.question_type
        record.evidence_lanes = list(evidence_set.lanes_present)
        record.evidence_conflicts = len(evidence_set.conflicts)

        if answer:
            verdict = va.validate(answer, plan,
                                  profile_medications=profile_medications or [])
            record.validator_approved = verdict.approved
            record.validator_failures = [f.check_id for f in verdict.failures]
    except Exception as exc:  # noqa: BLE001
        # Observability must never be the thing that breaks the consultation.
        record.error = f"{type(exc).__name__}: {exc}"
    record.duration_ms = int((time.monotonic() - started) * 1000)
    return record


def shadow_turn(text: str, **kw) -> ShadowRecord | None:
    """Evaluate and LOG, changing nothing. The production entry point.

    Returns the record so a test can assert on it; production ignores it.
    """
    if not getattr(config, "CLINICAL_SHADOW_EVAL", False):
        return None
    if kill_switch_engaged():
        return None
    try:
        # `user_id` is the cohort's business, not the pipeline's — it must not
        # be forwarded into `evaluate`, which does not take it.
        user_id = kw.pop("user_id", None)
        record = evaluate(text, **kw)
        record.cohort = in_cohort(user_id)
        record.shadow_only = not any_phase_live()
        log.info("%s %s", SHADOW_EVENT,
                 json.dumps(record.as_dict(), ensure_ascii=False,
                            default=str))
        return record
    except Exception as exc:  # noqa: BLE001
        log.warning("%s failed: %s", SHADOW_EVENT, exc)
        return None


# ===========================================================================
# Clinician review mode
#
# The same record, rendered for a person rather than a dashboard. Kept here so
# that what a reviewer signs off on is provably the same data the rollout
# decision is made from.
# ===========================================================================
def clinician_review(record: ShadowRecord) -> str:
    """A readable summary of one shadowed turn, for clinical sign-off."""
    if record is None:
        return "(no shadow record)"
    lines = [
        f"goal            : {record.goal} (confidence {record.goal_confidence:.2f})",
        f"subject         : {record.subject}",
        f"interaction     : {record.interaction_mode}",
        f"problems        : {record.problem_count}"
        + (f", priority: {record.priority_problem}" if record.priority_problem else ""),
        f"decision        : {record.action} -> {record.response_mode}",
        f"would ask       : {', '.join(record.next_question_ids) or '(nothing)'}",
        f"already known   : {', '.join(record.known_facts) or '(nothing)'}",
        f"evidence        : {record.evidence_question_type}"
        f" across {', '.join(record.evidence_lanes) or 'no lanes'}"
        + (f"; {record.evidence_conflicts} conflict(s)"
           if record.evidence_conflicts else ""),
    ]
    if record.validator_approved is not None:
        verdict = "approved" if record.validator_approved else "BLOCKED"
        lines.append(f"validator       : {verdict}"
                     + (f" ({', '.join(record.validator_failures)})"
                        if record.validator_failures else ""))
    if record.error:
        lines.append(f"ERROR           : {record.error}")
    lines.append(f"shadow only     : {record.shadow_only}")
    return "\n".join(lines)
