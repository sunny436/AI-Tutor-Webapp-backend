"""
PHASE-3 — the internal turn plan, question records and sufficiency engine.

persona.txt, `internal_turn_plan.requirement`:

    "Generate structured control output before producing patient-facing text."

This is the piece the whole specification turns on. PHASE-1 decided WHAT the
exchange is; PHASE-2 described the case. Neither changes anything on its own,
because nothing was deciding what to DO with them. That decision — ask or
answer, which question, and when to stop — is made here, once, in a structured
object that the response layer then renders.

THE TWO FAILURES THIS CLOSES

  "My eGFR is 50."   The reply asked "any other health conditions or
                     medications?" and offered Ayurvedic guidance. Nothing
                     asked the age, the test date, the creatinine or the
                     trend, which are the four things that decide what an
                     eGFR of 50 means. `universal_acceptance_examples` names
                     them explicitly.

  "fever, back pain  One blended question about all three, so whichever was
   + thyroid report" answered, the other two were lost.

WHERE THE QUESTIONS COME FROM, and where they do not.
`safety_engine.clinical_content_governance` is explicit: "Do not let the coding
agent invent comprehensive medical red-flag rules from model memory. Implement
the framework and seed only reviewed rules available in the existing product."

So this module implements the FRAMEWORK — reason codes, decision impact,
priority, sufficiency thresholds — and seeds it ONLY from:
  - the question fields persona.txt itself lists in
    `information_collection_policy.ask_when_decision_relevant`, and
  - the specific fields its own acceptance example names for the eGFR case.
Nothing here is a clinical rule invented from model memory. Adding a domain
means adding reviewed entries to `QUESTION_BANK`, not editing logic.

EVERY QUESTION CARRIES ITS REASON. `adaptive_question_policy.question_record`
requires a reason code and the decision it could change; PRINCIPLE-005 requires
that every question have a documented reason. A question with no recorded
decision impact cannot be asked, which is what stops the interrogation.

Feature-flagged (`config.PHASE3_TURN_PLAN`), OFF by default.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# `internal_turn_plan.schema.safety_status`
SAFETY_STATUS: tuple[str, ...] = (
    "emergency", "urgent", "prompt_review", "routine", "no_current_signal", "undetermined",
)

# `internal_turn_plan.schema.current_sufficiency` and
# `consultation_sufficiency_engine.sufficiency_levels`
SUFFICIENCY: tuple[str, ...] = (
    "insufficient",
    "sufficient_for_education",
    "sufficient_for_report_explanation",
    "sufficient_for_triage",
    "sufficient_for_working_assessment",
    "requires_examination_or_testing",
)

# `internal_turn_plan.schema.next_action`
ACTIONS: tuple[str, ...] = (
    "ask", "answer", "clarify_goal", "retrieve", "escalate", "summarize",
    "wait_for_report", "close",
)

# `adaptive_question_policy.question_record.decision_changed`
DECISIONS: tuple[str, ...] = (
    "urgency", "interpretation", "safety", "explanation_category",
    "investigation", "referral", "monitoring", "personalization",
)

# `adaptive_question_policy.question_priority`, rank 1 (highest) to 8.
_RANK_REASON = {
    1: "could_change_immediate_safety",
    2: "clarifies_patient_or_outcome",
    3: "could_radically_change_urgency",
    4: "required_to_interpret",
    5: "required_for_treatment_safety",
    6: "separates_explanation_categories",
    7: "changes_investigation_or_referral",
    8: "optional_personalization",
}


@dataclass
class QuestionRecord:
    """`adaptive_question_policy.question_record`, field for field.

    `required_for_current_goal` is what makes the bank goal-aware rather than a
    questionnaire: the same field is essential for one goal and noise for
    another. Age decides what an eGFR of 50 means; it decides nothing about
    what turmeric is traditionally used for.
    """

    question_id: str
    patient_facing_text: str
    reason_code: str
    decision_changed: list[str] = field(default_factory=list)
    required_for_current_goal: bool = True
    skip_if_known: bool = True
    sensitivity: str = "normal"
    rank: int = 8

    def as_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "patient_facing_text": self.patient_facing_text,
            "reason_code": self.reason_code,
            "decision_changed": list(self.decision_changed),
            "required_for_current_goal": self.required_for_current_goal,
            "skip_if_known": self.skip_if_known,
            "sensitivity": self.sensitivity,
            "rank": self.rank,
        }


def _q(qid, text, rank, *decisions, sensitivity="normal") -> QuestionRecord:
    return QuestionRecord(
        question_id=qid,
        patient_facing_text=text,
        reason_code=_RANK_REASON[rank],
        decision_changed=list(decisions),
        rank=rank,
        sensitivity=sensitivity,
    )


# ---------------------------------------------------------------------------
# THE QUESTION BANK, keyed by goal.
#
# Seeded only from fields persona.txt names. The eGFR set is taken verbatim
# from its acceptance example: "Ask for decision-relevant age context, test
# date, creatinine, previous results and applicable kidney-risk context."
# ---------------------------------------------------------------------------
QUESTION_BANK: dict[str, list[QuestionRecord]] = {
    "abnormal_lab_result": [
        _q("age", "Can I ask your age? It changes what this value means.",
           4, "interpretation"),
        _q("test_date", "When was this test done?", 4, "interpretation"),
        _q("previous_results", "Have you had this tested before, and what was it then?",
           4, "interpretation", "monitoring"),
        _q("related_values", "Does the report also show creatinine, or any other "
                             "related value?", 4, "interpretation"),
        _q("known_conditions", "Do you have any diagnosed conditions such as diabetes "
                               "or high blood pressure?", 5, "interpretation", "safety"),
        _q("current_medicines", "Are you taking any regular medicines?",
           5, "safety", "interpretation"),
        _q("symptoms_now", "Are you having any symptoms at the moment — swelling, "
                           "very reduced urine, breathlessness?", 1, "urgency", "safety"),
    ],
    "new_symptom": [
        _q("onset", "When did this start?", 4, "interpretation", "urgency"),
        _q("severity", "How bad is it right now?", 3, "urgency"),
        _q("course", "Is it getting better, worse, or staying the same?",
           3, "urgency", "monitoring"),
        _q("associated", "Is anything else happening along with it?",
           6, "explanation_category"),
        _q("functional_impact", "Is it stopping you doing your normal things?",
           7, "referral"),
    ],
    "personalized_medicine_safety": [
        _q("exact_medicine", "Which medicine exactly, and what strength if you know it?",
           5, "safety"),
        _q("current_medicines", "What else are you taking regularly?", 5, "safety"),
        _q("conditions", "Any conditions I should keep in mind — kidney, liver, "
                         "stomach, or pregnancy?", 5, "safety"),
        _q("allergies", "Any known allergies?", 5, "safety"),
    ],
    "personalized_herb_safety": [
        _q("exact_product", "What exactly is the product, and does it list its "
                            "ingredients?", 5, "safety"),
        _q("current_medicines", "What medicines are you on right now?", 5, "safety"),
        _q("conditions", "Any conditions I should keep in mind — transplant, kidney, "
                         "liver, or pregnancy?", 5, "safety"),
    ],
    "report_explanation": [
        _q("report_subject", "Is this report yours?", 2, "interpretation"),
        _q("report_date", "What date is on the report?", 4, "interpretation"),
    ],
    "child_health": [
        _q("child_age", "How old is your child?", 1, "urgency", "safety"),
        _q("child_feeding", "Are they feeding and drinking normally?", 1, "urgency"),
        _q("child_alertness", "Are they alert, or unusually drowsy?", 1, "urgency"),
    ],
    "urgency_or_triage": [
        _q("symptoms_now", "What exactly are you feeling right now?", 1, "urgency"),
        _q("onset", "When did it start?", 1, "urgency"),
    ],
    "follow_up": [
        _q("change", "What has changed since we last spoke?", 4, "monitoring"),
    ],
}

# Which question bank a problem TYPE draws on, when the goal itself names a
# shape rather than a subject. `multiple_concerns` is the case that needs it.
_GOAL_FOR_PROBLEM_TYPE: dict[str, str] = {
    "symptom": "new_symptom",
    "sign": "new_symptom",
    "abnormal_test": "abnormal_lab_result",
    "known_condition": "new_symptom",
    "medicine_question": "personalized_medicine_safety",
    "treatment_question": "new_symptom",
    "preventive_goal": "new_symptom",
    "mental_health": "urgency_or_triage",
    "injury": "urgency_or_triage",
    "exposure": "urgency_or_triage",
    "other": "new_symptom",
}

# Goals that owe an ANSWER, not an interview. `acceptance_criteria` 2:
# "Simple educational questions receive direct answers without a full intake."
EDUCATIONAL_GOALS: frozenset[str] = frozenset({
    "general_education",
    "medicine_information",
    "herb_or_supplement_information",
    "treatment_options",
    "preventive_health",
    "second_opinion_preparation",
})


@dataclass
class TurnPlan:
    """`internal_turn_plan.schema` — the control output for one turn."""

    consultation_id: str = ""
    current_goal: str = "new_symptom"
    goal_confidence: float = 0.0
    subject: str = "unknown"
    active_problem_ids: list[str] = field(default_factory=list)
    priority_problem_id: str | None = None
    safety_status: str = "undetermined"
    triggered_safety_rule_ids: list[str] = field(default_factory=list)
    known_decision_relevant_facts: list[str] = field(default_factory=list)
    missing_decision_relevant_facts: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    current_sufficiency: str = "insufficient"
    next_action: str = "ask"
    next_question_ids: list[str] = field(default_factory=list)
    question_reason_codes: list[str] = field(default_factory=list)
    evidence_query_plan: list[dict] = field(default_factory=list)
    allowed_output_types: list[str] = field(default_factory=list)
    prohibited_output_actions: list[str] = field(default_factory=list)
    requires_human_review: bool = False
    human_review_reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "consultation_id": self.consultation_id,
            "current_goal": self.current_goal,
            "goal_confidence": round(self.goal_confidence, 2),
            "subject": self.subject,
            "active_problem_ids": list(self.active_problem_ids),
            "priority_problem_id": self.priority_problem_id,
            "safety_status": self.safety_status,
            "triggered_safety_rule_ids": list(self.triggered_safety_rule_ids),
            "known_decision_relevant_facts": list(self.known_decision_relevant_facts),
            "missing_decision_relevant_facts": list(self.missing_decision_relevant_facts),
            "contradictions": list(self.contradictions),
            "current_sufficiency": self.current_sufficiency,
            "next_action": self.next_action,
            "next_question_ids": list(self.next_question_ids),
            "question_reason_codes": list(self.question_reason_codes),
            "evidence_query_plan": list(self.evidence_query_plan),
            "allowed_output_types": list(self.allowed_output_types),
            "prohibited_output_actions": list(self.prohibited_output_actions),
            "requires_human_review": self.requires_human_review,
            "human_review_reason": self.human_review_reason,
        }


# ---------------------------------------------------------------------------
# What is already known. `question_record.skip_if_known` and
# `prohibited_question_behavior`: "Repeating information already available."
# ---------------------------------------------------------------------------
_KNOWN_PATTERNS: dict[str, str] = {
    "age": r"\b(i\s+am|i'm|main|meri\s+age|umar)\s*\d{1,3}\b|\b\d{1,3}\s*(saal|years?\s+old)\b",
    "test_date": r"\b(today|yesterday|kal|aaj|last\s+(week|month)|\d{1,2}\s*(day|week|month|din|hafte|mahine))\b",
    "previous_results": r"\b(last\s+time|pehle|previously|before\s+it\s+was|earlier\s+it)\b",
    "related_values": r"\bcreatinine|urea|bun\b",
    "known_conditions": r"\b(diabetes|hypertension|bp|thyroid|kidney|liver|asthma|cancer)\b",
    "current_medicines": r"\b(metformin|insulin|thyronorm|amlodipine|tablet|dawa|medicine|taking)\b",
    "allergies": r"\ballerg\w*\b",
    "onset": r"\b(since|from|kab\s+se|se\s+ho\s+raha|yesterday|kal|\d+\s*(day|week|month|din|hafte|mahine))\b",
    "severity": r"\b(mild|moderate|severe|tez|halka|bahut|unbearable|\d\s*/\s*10)\b",
    "course": r"\b(better|worse|same|badh\s+rah|kam\s+ho|improving|worsening)\b",
    "child_age": r"\b\d{1,2}\s*(year|saal|month|mahine|week|hafte)\b|\b(one|two|three|four|five)[\s-]*year",
    "report_subject": r"\b(my|mera|meri|mine)\b",
    "exact_medicine": r"\b(metformin|ibuprofen|paracetamol|thyronorm|insulin|aspirin)\b",
    "exact_product": r"\b(churna|powder|tablet|capsule|syrup)\b",
    "symptoms_now": r"\bno\s+symptoms?\b|\bfeeling\s+(fine|ok|okay|normal)\b"
                    r"|\b(swelling|breathless|reduced\s+urine|peshab)\b"
                    r"|\bkoi\s+(takleef|lakshan|dikkat)\s+nahi\b",
}

# A "NO" IS AN ANSWER. Without these, "no symptoms", "koi dawa nahi leta" and
# "no other conditions" all read as still-unknown, so the same questions came
# back forever — `problem_statement.current_failure_pattern`: "It may continue
# asking questions without reaching a useful conclusion." A sufficiency engine
# cannot reach a threshold it can never observe being met.
_DENIED: dict[str, str] = {
    "known_conditions": r"\bno\s+(other\s+)?(conditions?|illness|disease)\b"
                        r"|\bkoi\s+(bimari|beemari|problem)\s+nahi\b"
                        r"|\bnothing\s+else\b",
    "current_medicines": r"\bno\s+(medicines?|medication|tablets?)\b"
                         r"|\bkoi\s+dawa\s+nahi\b|\bnot\s+taking\s+any\b",
    "allergies": r"\bno\s+allerg\w*|\bkoi\s+allergy\s+nahi\b",
    "previous_results": r"\b(first\s+time|pehli\s+baar|never\s+tested)\b",
}


def known_facts(transcript: str) -> list[str]:
    """Which decision-relevant fields the conversation already contains."""
    body = transcript or ""
    found = [
        field_name
        for field_name, pattern in _KNOWN_PATTERNS.items()
        if re.search(pattern, body, re.IGNORECASE)
    ]
    # An explicit "no" answers the question as completely as a "yes" does.
    found += [
        field_name
        for field_name, pattern in _DENIED.items()
        if field_name not in found and re.search(pattern, body, re.IGNORECASE)
    ]
    return found


def decide_sufficiency(goal: str, missing: list[str], *,
                       safety_status: str = "routine",
                       has_report: bool = False) -> str:
    """`consultation_sufficiency_engine` — the level reached, not a score.

    "Stop collecting routine history when the user's requested outcome can be
    delivered safely." The threshold depends on what was ASKED FOR, which is
    why an educational question is sufficient the moment it is understood.
    """
    if safety_status in ("emergency", "urgent"):
        # Triage only needs enough to act. `stop_rules`: do not delay
        # emergency care with speculative questions.
        return "sufficient_for_triage"
    if goal in EDUCATIONAL_GOALS:
        return "sufficient_for_education"
    if goal == "report_explanation":
        return "sufficient_for_report_explanation" if has_report else "insufficient"
    if not missing:
        return "sufficient_for_working_assessment"
    return "insufficient"


def _bundle(candidates: list[QuestionRecord], mode: str,
            safety_status: str) -> list[QuestionRecord]:
    """`adaptive_question_policy.question_bundle_policy`.

    Emergency asks only what changes disposition. Quick mode asks one. Standard
    asks a compact bundle of closely related fields. Nothing ever asks a long
    form, whatever remains unknown — that is the explicit prohibition.
    """
    if safety_status in ("emergency", "urgent"):
        return [q for q in candidates if q.rank == 1][:2]
    if mode == "quick":
        return candidates[:1]
    if mode == "detailed":
        return candidates[:5]
    return candidates[:3]


def plan(
    *,
    goal: str,
    goal_confidence: float,
    subject: str,
    case,
    transcript: str = "",
    safety_status: str = "routine",
    safety_rule_ids: list[str] | None = None,
    mode: str = "standard",
    has_report: bool = False,
    consultation_id: str = "",
) -> TurnPlan:
    """The control decision for one turn. Pure — no model, no I/O."""
    tp = TurnPlan(
        consultation_id=consultation_id,
        current_goal=goal,
        goal_confidence=goal_confidence,
        subject=subject,
        safety_status=safety_status,
        triggered_safety_rule_ids=list(safety_rule_ids or []),
    )

    live = case.unresolved() if case else []
    tp.active_problem_ids = [p.problem_id for p in live]
    top = case.priority_problem() if case else None
    tp.priority_problem_id = top.problem_id if top else None

    # 1. SAFETY INTERRUPTS EVERYTHING. `universal_conversation_flow.stages`
    #    STAGE-02, PRINCIPLE-002, criterion 10. Decided before the goal is
    #    even consulted, so no goal can suppress it.
    if safety_status == "emergency":
        tp.next_action = "escalate"
        tp.current_sufficiency = "sufficient_for_triage"
        tp.allowed_output_types = ["urgent_escalation"]
        tp.prohibited_output_actions = [
            "routine_history", "wellness_plan", "ayurveda_assessment", "herb_suggestion",
        ]
        return tp

    known = known_facts(transcript)
    tp.known_decision_relevant_facts = known

    # A MULTI-CONCERN TURN QUESTIONS THE PRIORITY PROBLEM, not the mixture.
    #
    # `multiple_concerns` is a goal about the SHAPE of the message, not about
    # what to ask — there is no such thing as a question set for "three
    # things at once". Without this the bank was empty, the turn looked
    # sufficient, and "fever, back pain and my thyroid report" was answered
    # with no questions at all while the fever went unexamined.
    # `multi_problem_manager`: "Ask targeted questions based on the active
    # problem." So the priority problem's TYPE chooses the bank.
    bank_goal = goal
    if goal == "multiple_concerns" and top is not None:
        bank_goal = _GOAL_FOR_PROBLEM_TYPE.get(top.problem_type, "new_symptom")

    bank = QUESTION_BANK.get(bank_goal, [])
    missing = [q for q in bank if not (q.skip_if_known and q.question_id in known)]
    tp.missing_decision_relevant_facts = [q.question_id for q in missing]

    tp.current_sufficiency = decide_sufficiency(
        goal, tp.missing_decision_relevant_facts,
        safety_status=safety_status, has_report=has_report,
    )

    # 2. AN EDUCATIONAL QUESTION IS OWED AN ANSWER. Criterion 2, and the
    #    "What is migraine?" acceptance example: no intake, no history demand.
    if tp.current_sufficiency in (
        "sufficient_for_education", "sufficient_for_report_explanation",
    ):
        tp.next_action = "answer"
        tp.allowed_output_types = ["direct_education"]
        tp.prohibited_output_actions = ["routine_history", "full_intake"]
        return tp

    # 3. Goal genuinely unclear and the two readings need different questions.
    #    `confidence_behavior`: ask which outcome matters most.
    if goal_confidence and goal_confidence < 0.4:
        tp.next_action = "clarify_goal"
        tp.allowed_output_types = ["adaptive_question"]
        return tp

    # 4. Otherwise ask the smallest useful set, ranked by decision impact.
    ordered = sorted(missing, key=lambda q: q.rank)
    chosen = _bundle(ordered, mode, safety_status)
    if chosen:
        tp.next_action = "ask"
        tp.next_question_ids = [q.question_id for q in chosen]
        tp.question_reason_codes = [q.reason_code for q in chosen]
        tp.allowed_output_types = ["adaptive_question"]
        tp.prohibited_output_actions = ["full_intake", "definitive_diagnosis"]
    else:
        tp.next_action = "answer"
        tp.allowed_output_types = ["working_assessment"]
        tp.prohibited_output_actions = ["definitive_diagnosis"]

    # 5. Evidence lanes for whatever comes next. `graphrag_requirements` keeps
    #    GraphRAG as the evidence layer only; this says what to fetch, never
    #    what to conclude.
    tp.evidence_query_plan = [{
        "question_type": goal,
        "evidence_lane": "ayurveda" if goal == "ayurveda_assessment" else "general",
        "patient_context_filters": known[:5],
    }]
    return tp


def questions_for(plan_obj: TurnPlan) -> list[QuestionRecord]:
    """The actual question records this plan selected, in rank order."""
    bank = {q.question_id: q for q in QUESTION_BANK.get(plan_obj.current_goal, [])}
    return [bank[qid] for qid in plan_obj.next_question_ids if qid in bank]


def render_questions(plan_obj: TurnPlan) -> str:
    """The chosen questions as text for the writer. Never the reason codes."""
    return "\n".join(q.patient_facing_text for q in questions_for(plan_obj))
