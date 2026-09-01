"""
clinical/timeline.py
--------------------
What happened, when — and did anything we suggested actually help?

WHY A TIMELINE AND NOT THE TRANSCRIPT
`chat_history` is capped at 24 turns and is prose. To answer "has this been
getting worse?" from it, a model has to re-read and re-interpret a
conversation every turn, and it can only see the part that has not been
evicted. A timeline is a short list of typed events that survives eviction, is
cheap to render into a prompt, and can be reasoned over directly.

WHY OUTCOMES ARE HERE TOO
They are the same shape — a thing with a start, an end and a result — and they
answer the question that makes the second consultation better than the first:
DID IT HELP? Without it, somebody who tried the same advice three months ago
and got nowhere is offered it again, which is the clearest possible signal that
nobody was listening.

DEDUPLICATED ON RECORD. The same event arriving twice ("started metformin"
mentioned in three consecutive turns) must not become three events, or a
timeline stops being readable by the end of one consultation.
"""

from __future__ import annotations

import datetime as _dt

from src.consult.schema import Outcome, TimelineEvent

# Bounded like every other list that rides on the context and is persisted per
# user. Oldest first out — a timeline is most useful about the recent past.
MAX_EVENTS = 40
MAX_OUTCOMES = 20

EVENT_TYPES = (
    "symptom_started",
    "symptom_improved",
    "symptom_worsened",
    "symptom_resolved",
    "symptom_recurred",
    "diagnosis",
    "medication_started",
    "medication_stopped",
    "intervention_started",
    "intervention_stopped",
    "test_completed",
    "report_result",
    "surgery",
    "hospitalization",
    "lifestyle_change",
)

OUTCOME_RESPONSES = ("helped", "no_change", "worsened", "unknown")


def today() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")


def record(
    events: list[TimelineEvent],
    kind: str,
    detail: str,
    *,
    episode_id: str = "",
    occurred_at: str = "",
    source: str = "patient",
) -> tuple[list[TimelineEvent], bool]:
    """Add one event. Returns (events, added).

    IDEMPOTENT ON (kind, detail, episode). Somebody who mentions the same
    thing on three consecutive turns has had one event happen, not three, and
    a timeline that says otherwise is worse than none.
    """
    kind = kind if kind in EVENT_TYPES else "symptom_started"
    detail = (detail or "").strip()[:120]
    if not detail:
        return events, False

    for existing in events:
        if (
            existing.kind == kind
            and existing.detail.lower() == detail.lower()
            and existing.episode_id == episode_id
        ):
            return events, False

    events = [
        *events,
        TimelineEvent(
            kind=kind,
            detail=detail,
            episode_id=episode_id,
            occurred_at=occurred_at or today(),
            recorded_at=today(),
            source=source,
        ),
    ]
    return events[-MAX_EVENTS:], True


def for_episode(events: list[TimelineEvent], episode_id: str) -> list[TimelineEvent]:
    return [e for e in events if e.episode_id == episode_id]


def render(events: list[TimelineEvent], episode_id: str = "", limit: int = 8) -> str:
    """The recent history, as lines for a prompt. "" when there is nothing.

    Scoped to one episode when an id is given — the knee is not context for the
    acidity, and including it is how a prompt gets long enough to stop being
    read carefully.
    """
    relevant = for_episode(events, episode_id) if episode_id else list(events)
    if not relevant:
        return ""
    recent = relevant[-limit:]
    lines = [
        f"  {e.occurred_at}  {e.kind.replace('_', ' ')}: {e.detail}" for e in recent
    ]
    return "WHAT HAS HAPPENED SO FAR:\n" + "\n".join(lines)


# --------------------------------------------------------------------------
# Interventions and whether they worked
# --------------------------------------------------------------------------
def start_intervention(
    outcomes: list[Outcome],
    intervention: str,
    *,
    episode_id: str = "",
    target: str = "",
    baseline: str = "",
) -> tuple[list[Outcome], bool]:
    """Note that something was suggested and started.

    Re-suggesting something already running is not a new attempt, so an open
    entry for the same intervention on the same problem is left alone.
    """
    name = (intervention or "").strip()[:80]
    if not name:
        return outcomes, False
    for existing in outcomes:
        if (
            existing.intervention.lower() == name.lower()
            and existing.episode_id == episode_id
            and not existing.stopped_at
        ):
            return outcomes, False
    outcomes = [
        *outcomes,
        Outcome(
            intervention=name,
            episode_id=episode_id,
            target_problem=target,
            started_at=today(),
            baseline_status=baseline,
        ),
    ]
    return outcomes[-MAX_OUTCOMES:], True


def report_outcome(
    outcomes: list[Outcome],
    intervention: str,
    *,
    response: str = "unknown",
    follow_up_status: str = "",
    adverse: str = "",
    adherence: str = "",
    reason_stopped: str = "",
    stop: bool = False,
    confidence: float = 1.0,
) -> tuple[list[Outcome], bool]:
    """Record how an intervention went. Updates the most recent OPEN entry.

    Falls back to the most recent entry of any status, so "that ginger tea did
    nothing" still lands somewhere even if the entry was already closed.
    """
    name = (intervention or "").strip().lower()
    if not name:
        return outcomes, False
    candidates = [o for o in outcomes if o.intervention.lower() == name]
    if not candidates:
        return outcomes, False
    target = next((o for o in reversed(candidates) if not o.stopped_at), candidates[-1])

    target.patient_reported_effect = (
        response if response in OUTCOME_RESPONSES else "unknown"
    )
    target.follow_up_status = follow_up_status or target.follow_up_status
    target.adverse_effects = adverse or target.adverse_effects
    target.adherence = adherence or target.adherence
    target.confidence = confidence
    if stop or reason_stopped:
        target.stopped_at = target.stopped_at or today()
        target.reason_stopped = reason_stopped or target.reason_stopped
    return outcomes, True


def tried_before(outcomes: list[Outcome], intervention: str) -> Outcome | None:
    """Has this been tried, and what happened? The whole point of the module."""
    name = (intervention or "").strip().lower()
    return next(
        (o for o in reversed(outcomes) if o.intervention.lower() == name), None
    )


def unhelpful(outcomes: list[Outcome], episode_id: str = "") -> list[str]:
    """Things this person has already tried that did NOT help.

    Read before composing a plan: offering these again is the clearest signal a
    product can send that nobody was listening.
    """
    return [
        o.intervention
        for o in outcomes
        if o.patient_reported_effect in ("no_change", "worsened")
        and (not episode_id or o.episode_id == episode_id)
    ]


def render_outcomes(outcomes: list[Outcome], episode_id: str = "") -> str:
    """What has been tried and how it went, for a prompt. "" when nothing."""
    relevant = [o for o in outcomes if not episode_id or o.episode_id == episode_id]
    if not relevant:
        return ""
    words = {
        "helped": "helped",
        "no_change": "made no difference",
        "worsened": "made it worse",
        "unknown": "outcome not known yet",
    }
    lines = []
    for o in relevant[-6:]:
        state = words.get(o.patient_reported_effect, "outcome not known yet")
        extra = f", stopped: {o.reason_stopped}" if o.reason_stopped else ""
        adverse = f", side effect: {o.adverse_effects}" if o.adverse_effects else ""
        lines.append(f"  {o.intervention} — {state}{adverse}{extra}")
    return (
        "ALREADY TRIED BY THIS PERSON (do not re-offer what did not help, and "
        "never re-offer something that caused a side effect):\n" + "\n".join(lines)
    )
