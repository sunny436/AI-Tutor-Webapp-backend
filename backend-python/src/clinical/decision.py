"""
clinical/decision.py
--------------------
Do we know enough yet, and if not, what is worth asking?

TWO THINGS THIS PRODUCT COULD NOT SAY BEFORE
  1. "I do not yet know enough to advise you safely." The flow had `ready`,
     a boolean the gathering model set, and nothing that could hold back a
     personalised recommendation for a reason other than "not enough rounds".
  2. "This question is worth asking and that one is not." `missing_info` was a
     list the model produced and the model consumed, so a field being empty was
     reason enough to ask about it — which is how a consultation becomes a form.

`decide()` grades the first. `rank_questions()` orders the second by what the
answer would actually change, and returns the one or two that earn their place.

DETERMINISTIC. Both take the state that already exists — triage, profile,
episode — and return a verdict with its reasons. No model call, so the gate
cannot be talked out of its conclusion by a confident sentence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.clinical.triage import rank

# Weakest commitment to strongest.
STATES = (
    "URGENT_ESCALATION",
    "SUGGEST_CLINICIAN_REVIEW",
    "ASK_MORE",
    "ANSWER_EDUCATION_ONLY",
    "GIVE_LOW_RISK_GUIDANCE",
    "GIVE_PERSONALIZED_GUIDANCE",
)


@dataclass
class Decision:
    state: str = "ASK_MORE"
    reasons: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"state": self.state, "reasons": list(self.reasons), "missing": list(self.missing)}


# What a question is worth. Higher is asked first. These are the priority
# dimensions the spec names, given numbers so they can be compared.
VALUE = {
    "emergency": 100,        # would change whether this is an emergency
    "interaction": 80,       # would change whether something is safe to suggest
    "contraindication": 78,
    "diagnostic": 60,        # would change what this probably is
    "differential": 55,      # would separate two real possibilities
    "treatment": 40,         # would change what is advised
    "personalisation": 20,   # would make the same advice fit better
    "record": 0,             # would fill a field and change nothing
}

# Baseline facts, and what asking for them is actually worth. Anything not
# listed is `record` — worth nothing on its own, which is the default that
# stops the profile schema driving the conversation.
_FACT_VALUE = {
    "medications": "interaction",
    "allergies": "contraindication",
    "conditions": "diagnostic",
    "age": "personalisation",
    "sex": "personalisation",
    "reproductive": "contraindication",
}

_FACT_QUESTION = {
    "medications": "whether they are taking any regular medicine",
    "allergies": "whether they have any allergies",
    "conditions": "whether they have any diagnosed condition",
    "age": "their age",
    "sex": "their sex",
    "reproductive": "whether they might be pregnant",
}


@dataclass
class Question:
    topic: str
    asks: str
    value: int
    why: str
    resolves: str = ""

    def as_dict(self) -> dict:
        return {"topic": self.topic, "asks": self.asks, "value": self.value,
                "why": self.why, "resolves": self.resolves}


def _already_known(item: str, profile, episode) -> bool:
    """Is this piece of safety information already on file?

    Matched loosely on the words triage uses, because those strings are its
    own prose ("how long this has been going on"), not identifiers.
    """
    text = (item or "").lower()
    if "age" in text:
        return bool(getattr(profile, "age", ""))
    if "medicine" in text or "medication" in text:
        # `active`, not every medicine ever recorded — but a person who has
        # told us they take nothing has still answered the question, and the
        # profile cannot express that yet, so any recorded medicine counts.
        return bool(getattr(profile, "medications", []))
    if "allerg" in text:
        return bool(getattr(profile, "allergies", []))
    if "pregnan" in text:
        return bool(getattr(profile, "reproductive", ""))
    if "how long" in text or "duration" in text:
        return bool(getattr(episode, "duration", "") or getattr(episode, "onset", ""))
    return False


def rank_questions(
    *,
    profile,
    episode=None,
    triage=None,
    already_asked: list[str] | None = None,
    proposed_interventions: list[str] | None = None,
) -> list[Question]:
    """The questions worth asking now, best first.

    NEVER ASKED BECAUSE A FIELD IS EMPTY. A fact earns a question only when
    knowing it would change something: safety, what this probably is, or what
    may be suggested. `age` is worth little on its own and a great deal once an
    intervention is on the table, and that is the difference between a
    consultation and an intake form.
    """
    asked = {a.lower() for a in (already_asked or [])}
    out: list[Question] = []

    # Anything the triage step could not complete outranks everything else —
    # BUT ONLY IF WE DO NOT ALREADY KNOW IT.
    #
    # `triage.missing_safety_information` is derived from the TEXT of this
    # conversation, so it reports "age" for a returning patient whose age has
    # been on file for months. Asking anyway is the single most obvious way to
    # tell somebody they were not remembered, and it outranks every other
    # question, so it would be the FIRST thing said. Checked against the
    # profile here, which is the only place that knows.
    for missing in (triage.missing_safety_information if triage else []):
        if _already_known(missing, profile, episode):
            continue
        out.append(Question(
            topic=missing, asks=missing, value=VALUE["emergency"],
            why="the safety assessment cannot be completed without it",
            resolves="safety",
        ))

    # An intervention being considered makes interaction facts urgent — this is
    # the "unknown important interaction information can itself block" rule
    # turned into a question rather than a refusal.
    considering = bool(proposed_interventions)
    for key, kind in _FACT_VALUE.items():
        known = bool(getattr(profile, key, None))
        if isinstance(getattr(profile, key, None), list):
            known = bool(profile.active(key)) if hasattr(profile, "active") else known
        if known:
            continue
        question = _FACT_QUESTION[key]
        if question.lower() in asked:
            continue
        value = VALUE[kind]
        if considering and kind in ("interaction", "contraindication"):
            value += 15  # about to suggest something; this now matters most
        elif not considering and kind == "personalisation":
            value = VALUE["record"]  # nothing turns on it yet
        if value <= VALUE["record"]:
            continue
        out.append(Question(
            topic=key, asks=question, value=value,
            why=f"it changes {kind}",
            resolves=kind,
        ))

    # What the episode itself still does not know.
    for unknown in (episode.important_unknowns if episode else [])[:4]:
        if unknown.lower() in asked:
            continue
        out.append(Question(
            topic=unknown, asks=unknown, value=VALUE["diagnostic"],
            why="it is the gap the last turn identified",
            resolves="diagnostic",
        ))

    out.sort(key=lambda q: q.value, reverse=True)
    return out


def next_questions(ranked: list[Question], limit: int = 2) -> list[Question]:
    """One or two, never a battery.

    Two only when the second is worth nearly as much as the first; otherwise
    one. Batching a high-value and a low-value question is how a reasonable
    pair turns into a form.
    """
    if not ranked:
        return []
    top = ranked[:limit]
    if len(top) == 2 and top[1].value < top[0].value * 0.6:
        return top[:1]
    return top


def decide(
    *,
    triage,
    profile,
    episode=None,
    has_evidence: bool = True,
    proposed_interventions: list[str] | None = None,
    rounds: int = 0,
    max_rounds: int = 4,
) -> Decision:
    """How far may this turn go?

    Ordered by severity: the first rule that fires wins, so a RED triage can
    never be overtaken by "we have plenty of information".
    """
    reasons: list[str] = []

    if triage and triage.risk_level == "RED":
        return Decision("URGENT_ESCALATION", ["emergency features present"], [])

    ranked = rank_questions(
        profile=profile, episode=episode, triage=triage,
        proposed_interventions=proposed_interventions,
    )
    blocking = [q for q in ranked if q.value >= VALUE["interaction"]]

    if triage and triage.risk_level == "ORANGE":
        reasons.append("a prompt clinical review is warranted")
        return Decision("SUGGEST_CLINICIAN_REVIEW", reasons, [q.asks for q in ranked[:2]])

    # SOMETHING IS ABOUT TO BE SUGGESTED AND A SAFETY FACT IS MISSING. This is
    # the case the spec singles out: not knowing is itself a reason to stop.
    if proposed_interventions and blocking:
        reasons.append(
            "an intervention is on the table and "
            + ", ".join(q.asks for q in blocking[:2])
            + " is not known"
        )
        return Decision("ASK_MORE", reasons, [q.asks for q in blocking[:2]])

    # The intake has run long enough; answering with what we have beats asking
    # forever. Mirrors MAX_GATHERING_ROUNDS rather than competing with it.
    if rounds >= max_rounds:
        reasons.append("the intake has reached its ceiling")
        return Decision(
            "GIVE_PERSONALIZED_GUIDANCE" if not blocking else "GIVE_LOW_RISK_GUIDANCE",
            reasons, [],
        )

    if ranked and ranked[0].value >= VALUE["diagnostic"]:
        reasons.append(f"the most useful unknown is {ranked[0].asks}")
        return Decision("ASK_MORE", reasons, [q.asks for q in next_questions(ranked)])

    if not has_evidence:
        reasons.append("no supporting material was retrieved")
        return Decision("ANSWER_EDUCATION_ONLY", reasons, [])

    if triage and triage.risk_level == "YELLOW":
        reasons.append("a long-term condition or medication is involved")
        return Decision("GIVE_LOW_RISK_GUIDANCE", reasons, [])

    reasons.append("enough is known and nothing raises concern")
    return Decision("GIVE_PERSONALIZED_GUIDANCE", reasons, [])
