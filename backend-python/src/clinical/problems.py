"""
PHASE-2 — the open problem representation.

persona.txt, `open_problem_representation.purpose`:

    "Maintain a disease-neutral view of the case until sufficient evidence
     supports a narrower assessment."

WHAT THIS FIXES, measured. Asked "I have fever, back pain and also want to
understand my thyroid report", the system replied with ONE question about "the
fever and back pain, and clarity on your thyroid report" — three concerns
flattened into a single complaint, so whichever one it questioned about, the
other two were lost. `universal_acceptance_examples` requires three problem
entries, the acute one prioritised, and the report kept as a parallel concern.

WHY A NEW MODULE RATHER THAN A WIDER `Episode`.
`clinical/episodes.py` already separates concerns and survives topic switches,
and it is persisted inside `ConsultContext` and round-tripped through the
browser on every turn. The spec's schema is much richer — problem_type,
priority, onset/course/severity, candidate explanation categories with
confidence bands — and forcing all of that into the persisted episode would
change a structure that production clients are already storing.

So this is a VIEW, built from episodes plus the turn's message, and it is what
PHASE-3's turn plan reads. Episodes stay the durable record; this is the
working representation of the case. `from_episodes` is the bridge.

DISEASE-NEUTRAL, which is the whole point. `rules` forbids requiring a disease
name to create a problem, collapsing symptoms into one disease, and inferring
causality from co-occurrence. So a problem is created from what the person
SAID, and any relationship between two problems is recorded as "possibly
related" with no direction and no mechanism.

Feature-flagged (`config.PHASE2_PROBLEM_MODEL`), OFF by default.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

# `open_problem_representation.schema.problems[].problem_type`
PROBLEM_TYPES: tuple[str, ...] = (
    "symptom",
    "sign",
    "abnormal_test",
    "known_condition",
    "medicine_question",
    "treatment_question",
    "preventive_goal",
    "mental_health",
    "injury",
    "exposure",
    "other",
)

PRIORITIES: tuple[str, ...] = ("critical", "high", "normal", "deferred")

STATUSES: tuple[str, ...] = (
    "open",
    "sufficiently_assessed",
    "escalated",
    "answered",
    "monitoring",
    "closed",
)

# `multi_problem_manager.priority_order`, most urgent first. The index is the
# rank, so a problem's band is decided by the first rule it matches.
PRIORITY_ORDER: tuple[str, ...] = (
    "immediate_safety",
    "acute_deterioration",
    "potentially_serious_untreated",
    "medication_or_interaction_risk",
    "user_stated_priority",
    "chronic_symptom_affecting_function",
    "preventive_or_wellness",
)

# Which band each rank falls into. Deliberately conservative at the top: the
# first three are the ones that must not wait behind a thyroid report.
_BAND_FOR_RANK = {
    "immediate_safety": "critical",
    "acute_deterioration": "critical",
    "potentially_serious_untreated": "high",
    "medication_or_interaction_risk": "high",
    "user_stated_priority": "normal",
    "chronic_symptom_affecting_function": "normal",
    "preventive_or_wellness": "deferred",
}


@dataclass
class Problem:
    """One concern, described the way the person described it."""

    problem_id: str
    patient_description: str
    problem_type: str = "symptom"
    onset: str | None = None
    course: str | None = None
    severity: str | None = None
    functional_impact: str | None = None
    associated_features: list[str] = field(default_factory=list)
    # "possible_relationships" — a REFERENCE, never a causal claim. `rules`:
    # "Do not infer that two conditions are causally related merely because
    # they co-occur."
    possible_relationships: list[str] = field(default_factory=list)
    current_priority: str = "normal"
    status: str = "open"
    priority_reason: str = ""

    def as_dict(self) -> dict:
        return {
            "problem_id": self.problem_id,
            "patient_description": self.patient_description,
            "problem_type": self.problem_type,
            "onset": self.onset,
            "course": self.course,
            "severity": self.severity,
            "functional_impact": self.functional_impact,
            "associated_features": list(self.associated_features),
            "possible_relationships": list(self.possible_relationships),
            "current_priority": self.current_priority,
            "status": self.status,
            "priority_reason": self.priority_reason,
        }


@dataclass
class CandidateCategory:
    """`candidate_explanation_categories` — never shown as a list to the reader.

    `rules`: "Do not expose an overwhelming differential-diagnosis list to the
    patient. Use the internal categories to choose questions and produce a
    concise patient-facing explanation."
    """

    category: str
    supporting_fact_ids: list[str] = field(default_factory=list)
    conflicting_fact_ids: list[str] = field(default_factory=list)
    confidence_band: str = "low"
    status: str = "possible"

    def as_dict(self) -> dict:
        return {
            "category": self.category,
            "supporting_fact_ids": list(self.supporting_fact_ids),
            "conflicting_fact_ids": list(self.conflicting_fact_ids),
            "confidence_band": self.confidence_band,
            "status": self.status,
        }


@dataclass
class OpenCase:
    """The whole case, disease-neutral. `open_problem_representation.schema`."""

    consultation_id: str = ""
    subject: str = "unknown"
    consultation_goal: str = "new_symptom"
    desired_depth: str = "standard"
    problems: list[Problem] = field(default_factory=list)
    known_facts: list[str] = field(default_factory=list)
    important_unknowns: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    active_safety_flags: list[str] = field(default_factory=list)
    candidate_explanation_categories: list[CandidateCategory] = field(default_factory=list)
    selected_next_action: str = ""
    sufficiency_status: str = "insufficient"

    # ---- multi_problem_manager -------------------------------------------
    def priority_problem(self) -> Problem | None:
        """The highest-risk problem. "Identify the highest-risk problem first."

        A chronic condition must never outrank a new urgent symptom, so the
        sort is by band and then by the order the person raised them — not by
        how much is known about each, which would favour the well-described
        chronic one.
        """
        live = [p for p in self.problems if p.status in ("open", "monitoring")]
        if not live:
            return None
        rank = {band: i for i, band in enumerate(PRIORITIES)}
        return sorted(live, key=lambda p: rank.get(p.current_priority, 99))[0]

    def deferred(self) -> list[Problem]:
        """"Maintain a deferred-problem list." """
        return [p for p in self.problems if p.current_priority == "deferred"
                and p.status in ("open", "monitoring")]

    def unresolved(self) -> list[Problem]:
        return [p for p in self.problems if p.status in ("open", "monitoring")]

    def get(self, problem_id: str) -> Problem | None:
        return next((p for p in self.problems if p.problem_id == problem_id), None)

    def as_dict(self) -> dict:
        return {
            "consultation_id": self.consultation_id,
            "subject": self.subject,
            "consultation_goal": self.consultation_goal,
            "desired_depth": self.desired_depth,
            "problems": [p.as_dict() for p in self.problems],
            "known_facts": list(self.known_facts),
            "important_unknowns": list(self.important_unknowns),
            "contradictions": list(self.contradictions),
            "active_safety_flags": list(self.active_safety_flags),
            "candidate_explanation_categories": [
                c.as_dict() for c in self.candidate_explanation_categories
            ],
            "selected_next_action": self.selected_next_action,
            "sufficiency_status": self.sufficiency_status,
        }


def _pid(text: str) -> str:
    return hashlib.sha1((text or "").strip().lower().encode("utf-8")).hexdigest()[:10]


# ---------------------------------------------------------------------------
# Typing a concern from the words used. Disease-neutral: none of this needs a
# diagnosis, and none of it asserts one.
# ---------------------------------------------------------------------------
_TYPE_SIGNALS: tuple[tuple[str, str], ...] = (
    ("abnormal_test", r"\b(egfr|gfr|creatinine|hba1c|tsh|t3|t4|haemoglobin|hemoglobin|hb|"
                      r"platelet|wbc|esr|crp|cholesterol|ldl|hdl|sgpt|sgot|bilirubin|"
                      r"vitamin\s*[bd]|ferritin|psa|inr|report|sugar\s+(is|level))\b"),
    ("mental_health", r"\b(hopeless|depress\w*|anxious|anxiety|panic|suicidal|udaas|"
                      r"ghabrahat|bechaini|tanav)\b"),
    ("injury", r"\b(fell|fracture|burn|cut|wound|injur\w*|accident|bite|chot|jal\s*gaya)\b"),
    ("exposure", r"\b(overdose|poison|zahar|too\s+many\s+(tablets|pills)|exposure|"
                 r"accidentally\s+(took|ate|drank))\b"),
    ("medicine_question", r"\b(metformin|ibuprofen|paracetamol|tablet|capsule|syrup|"
                          r"medicine|dawa|dawai|ashwagandha|turmeric|haldi|triphala|"
                          r"churna|herb|supplement)\b"),
    # "which health tests should I get" names no test and reports no value, so
    # the abnormal_test rule above correctly ignores it — but nothing else
    # claimed it either, and it fell through to `symptom` and a normal
    # priority. A screening question is a preventive goal and belongs behind a
    # live complaint.
    ("preventive_goal", r"\b(screening|check\s*up|checkup|preventive|prevent|avoid\s+"
                        r"getting)\b"
                        r"|\b(which|what|kaunse|kaun\s*se)\b[^.?!\n]{0,24}\btests?\b"),
    ("known_condition", r"\b(diagnosed|i\s+have\s+(diabetes|hypertension|thyroid|asthma|"
                        r"cancer|ckd)|mujhe\s+(diabetes|thyroid|bp)\s+hai)\b"),
    ("treatment_question", r"\b(treatment\s+options?|what\s+treatments|ilaj\s+ke\s+"
                           r"(options|tarike))\b"),
)

# `multi_problem_manager.priority_order` rank 1-2: what must not wait.
_ACUTE = re.compile(
    r"\b(fever|bukhar|severe|tez|sudden|achanak|acute|bleeding|khoon|vomit\w*|ulti|"
    r"breathless|saans|chest|seene|unconscious|behosh|fits|daura|worsening|badh\s+rah)\b",
    re.IGNORECASE,
)
_CHRONIC = re.compile(
    r"\b(months?|mahine|years?|saal|chronic|purana|always|hamesha|long\s+time)\b",
    re.IGNORECASE,
)


def classify_problem_type(text: str) -> str:
    body = text or ""
    for problem_type, pattern in _TYPE_SIGNALS:
        if re.search(pattern, body, re.IGNORECASE):
            return problem_type
    return "symptom"


def rank_problem(text: str, *, safety_flagged: bool = False,
                 user_prioritised: bool = False) -> tuple[str, str]:
    """(priority_band, rank_reason) from `multi_problem_manager.priority_order`."""
    body = text or ""
    if safety_flagged:
        return _BAND_FOR_RANK["immediate_safety"], "immediate_safety"
    if _ACUTE.search(body) and not _CHRONIC.search(body):
        return _BAND_FOR_RANK["acute_deterioration"], "acute_deterioration"
    kind = classify_problem_type(body)
    if kind == "abnormal_test":
        return _BAND_FOR_RANK["potentially_serious_untreated"], "potentially_serious_untreated"
    if kind in ("medicine_question", "exposure"):
        return (_BAND_FOR_RANK["medication_or_interaction_risk"],
                "medication_or_interaction_risk")
    if user_prioritised:
        return _BAND_FOR_RANK["user_stated_priority"], "user_stated_priority"
    if kind == "preventive_goal":
        return _BAND_FOR_RANK["preventive_or_wellness"], "preventive_or_wellness"
    if _CHRONIC.search(body):
        return (_BAND_FOR_RANK["chronic_symptom_affecting_function"],
                "chronic_symptom_affecting_function")
    return "normal", "user_stated_priority"


# How a multi-concern sentence is cut into separate problems. The split is on
# the connectors people actually use, and each piece keeps its own words —
# `rules`: "Do not collapse several symptoms into one disease automatically."
_SPLIT = re.compile(
    r",|\band\s+also\b|\band\b|\baur\s+bhi\b|\baur\b|\bplus\b|\biske\s+alawa\b|"
    r"\bsaath\s+hi\b|;",
    re.IGNORECASE,
)
_CONCERN_WORD = re.compile(
    r"\b(fever|bukhar|pain|dard|report|cough|khansi|cold|sardi|headache|"
    r"acidity|gas|constipation|kabz|diarrh\w*|dast|vomit|ulti|nausea|rash|itch|"
    r"khujli|swelling|sujan|weakness|kamzori|thakan|fatigue|sleep|neend|anxiety|"
    r"stress|sugar|bp|thyroid|weight|periods?|egfr|creatinine|hba1c|tsh|"
    # A preventive goal is a concern too. Without these, "which health tests
    # should I get, and I have back pain" dropped the screening half and
    # collapsed to a single problem — the exact merging this phase prevents.
    r"tests?|screening|check\s*up|checkup)\b",
    re.IGNORECASE,
)


def split_concerns(text: str) -> list[str]:
    """The distinct concerns in one message, each keeping its own wording."""
    pieces = [p.strip() for p in _SPLIT.split(text or "") if p and p.strip()]
    out: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        found = _CONCERN_WORD.search(piece)
        if not found:
            continue
        key = found.group(0).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(piece)
    return out


def build(text: str, *, goal: str = "new_symptom", subject: str = "unknown",
          depth: str = "standard", safety_flags: list[str] | None = None,
          consultation_id: str = "") -> OpenCase:
    """The open case for one message. Disease-neutral by construction."""
    flags = list(safety_flags or [])
    case = OpenCase(
        consultation_id=consultation_id,
        subject=subject,
        consultation_goal=goal,
        desired_depth=depth,
        active_safety_flags=flags,
    )

    concerns = split_concerns(text)
    # One concern, or none recognised: the message itself is the problem. A
    # problem never requires a disease name — `rules` line 1.
    if len(concerns) < 2:
        concerns = [(text or "").strip()] if (text or "").strip() else []

    for piece in concerns:
        band, reason = rank_problem(piece, safety_flagged=bool(flags))
        case.problems.append(
            Problem(
                problem_id=_pid(piece),
                patient_description=piece,
                problem_type=classify_problem_type(piece),
                current_priority=band,
                priority_reason=reason,
            )
        )

    # Problems raised in the same breath MAY be related. Recorded as a bare
    # reference in both directions, with no cause and no direction — the rule
    # forbids inferring causality from co-occurrence.
    if len(case.problems) > 1:
        ids = [p.problem_id for p in case.problems]
        for problem in case.problems:
            problem.possible_relationships = [i for i in ids if i != problem.problem_id]

    return case


def from_episodes(episodes, active_episode_id: str = "", **kw) -> OpenCase:
    """Bridge: the durable episode record -> the working representation.

    Episodes remain the persisted truth; this is the view PHASE-3 reasons over.
    """
    case = OpenCase(**kw)
    for episode in episodes or []:
        band, reason = rank_problem(episode.problem_name)
        if episode.episode_id == active_episode_id and band == "deferred":
            band, reason = "normal", "user_stated_priority"
        case.problems.append(
            Problem(
                problem_id=episode.episode_id,
                patient_description=episode.problem_name,
                problem_type=classify_problem_type(episode.problem_name),
                associated_features=list(getattr(episode, "associated_symptoms", []) or []),
                current_priority=band,
                priority_reason=reason,
                status="open" if getattr(episode, "status", "active") == "active" else "closed",
            )
        )
    return case


def render(case: OpenCase) -> str:
    """One short block for a prompt. Never a differential list for the reader.

    `rules`: the categories exist to choose questions and to write a concise
    explanation — not to be recited. So only the priority problem and the count
    of other open ones are named.
    """
    live = case.unresolved()
    if not live:
        return ""
    top = case.priority_problem()
    lines = []
    if top:
        lines.append(f"Priority concern: {top.patient_description} ({top.problem_type})")
    others = [p for p in live if not top or p.problem_id != top.problem_id]
    if others:
        lines.append(
            "Also open, not the current focus: "
            + "; ".join(p.patient_description for p in others[:4])
        )
    return "\n".join(lines)
