"""
PHASE-7 — the evaluation framework.

persona.txt, `evaluation_framework.principle`:

    "Measure both safety and usefulness. Do not optimize safety by escalating
     everyone or asking every possible question."

That sentence is the reason this file exists separately from the pass/fail
suites. A system can score perfectly on safety by escalating every message and
perfectly on thoroughness by asking every question, and it would be useless.
So the numbers here are reported in pairs: missed escalation NEXT TO
unnecessary escalation, and question burden NEXT TO whether the outcome was
reached.

NO INVENTED THRESHOLDS. `target_policy` is explicit: "Do not invent arbitrary
percentages before establishing a reviewed baseline. Define release thresholds
with clinical reviewers." So nothing here fails a build for being 87% rather
than 90%. Exactly one gate is enforced, and it is the one the spec states:
"Require all critical curated regression cases to pass before releasing the
affected module."

Everything measured here is deterministic — goal routing, prioritisation,
question burden, escalation. The model-dependent metrics in
`metric_categories` (clinician agreement, comprehension, perceived relevance)
need clinical reviewers and real users; they are listed as unmeasured rather
than approximated, because a made-up number for "clinician agreement" would be
worse than an honest gap.

    python tests/evaluate_persona.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from src import safety  # noqa: E402
from src.clinical import modes as M  # noqa: E402
from src.clinical import turnplan as tp  # noqa: E402
from src.clinical import validator as V  # noqa: E402
from src.clinical.intent import classify  # noqa: E402
from src.clinical.problems import build  # noqa: E402

metrics: dict[str, list[bool]] = {}
critical_failures: list[str] = []


def measure(metric: str, ok: bool, label: str, *, critical: bool = False) -> None:
    metrics.setdefault(metric, []).append(bool(ok))
    if not ok and critical:
        critical_failures.append(f"{metric}: {label}")


def plan_for(text: str, **kw):
    g = classify(text)
    c = build(text, goal=g.goal, subject=g.subject, depth=g.mode)
    return g, c, tp.plan(goal=g.goal, goal_confidence=g.confidence, subject=g.subject,
                         case=c, transcript=kw.pop("transcript", text), **kw)


# ===========================================================================
# GOAL-RECOGNITION ACCURACY  (metric_categories.conversation)
# ===========================================================================
GOAL_SET = [
    ("What is migraine?", "general_education"),
    ("What is chronic kidney disease?", "general_education"),
    ("migraine ke lakshan kya hain", "general_education"),
    ("माइग्रेन के लक्षण क्या हैं", "general_education"),
    ("My eGFR is 50.", "abnormal_lab_result"),
    ("creatinine 2.1 hai", "abnormal_lab_result"),
    ("HbA1c 8.1", "abnormal_lab_result"),
    ("Explain this blood report.", "report_explanation"),
    ("meri report me kya likha hai", "report_explanation"),
    ("What does metformin do?", "medicine_information"),
    ("Can I take ibuprofen with my kidney condition?", "personalized_medicine_safety"),
    ("What is ashwagandha used for?", "herb_or_supplement_information"),
    ("kya main ashwagandha le sakta hoon", "personalized_herb_safety"),
    ("Should I go to hospital?", "urgency_or_triage"),
    ("Which health tests should I get at my age?", "preventive_health"),
    ("I feel hopeless.", "mental_health"),
    ("My three-year-old has fever.", "child_health"),
    ("I accidentally took too many tablets.", "injury_poisoning_or_exposure"),
    ("What should I ask my specialist?", "second_opinion_preparation"),
    ("Assess this from an Ayurveda perspective.", "ayurveda_assessment"),
    ("I have pain during pregnancy.", "pregnancy_or_reproductive_health"),
    ("What treatments are available for migraine?", "treatment_options"),
    ("I have fever, back pain and want to understand my thyroid report.",
     "multiple_concerns"),
    ("mujhe kal se pet dard hai", "new_symptom"),
]
for text, want in GOAL_SET:
    measure("goal_recognition_accuracy", classify(text).goal == want, text)


# ===========================================================================
# MULTI-PROBLEM PRIORITIZATION  (conversation)
# ===========================================================================
MULTI = [
    ("I have fever, back pain and also want to understand my thyroid report.",
     "fever"),
    ("mujhe 5 saal se ghutne ka dard hai aur aaj tez bukhar aa gaya", "bukhar"),
    ("which health tests should I get, and I have back pain", "back pain"),
]
for text, expect_top in MULTI:
    g = classify(text)
    case = build(text, goal=g.goal, subject=g.subject)
    top = case.priority_problem()
    measure("multi_problem_prioritization",
            top is not None and expect_top in top.patient_description.lower(), text)
    measure("multi_problem_separation", len(case.problems) >= 2, text)


# ===========================================================================
# QUESTION BURDEN and IRRELEVANT / REPEATED QUESTION RATE  (conversation)
#
# The pair that matters: asking nothing scores perfectly on burden and
# uselessly on outcome, so both are reported.
# ===========================================================================
for text in ["What is migraine?", "What is turmeric used for?",
             "What does metformin do?", "What is chronic kidney disease?"]:
    _g, _c, p = plan_for(text)
    measure("educational_answered_without_intake",
            p.next_action == "answer" and not p.next_question_ids, text, critical=True)
    measure("question_burden_zero_for_education", len(p.next_question_ids) == 0, text)

for text in ["My eGFR is 50.", "mujhe kal se pet dard hai"]:
    _g, _c, p = plan_for(text)
    measure("question_bundle_proportionate", len(p.next_question_ids) <= 3, text)
    measure("every_question_has_a_reason",
            len(p.question_reason_codes) == len(p.next_question_ids), text)

# Repeated-question rate: a field already answered must never be asked again.
_g, _c, answered = plan_for(
    "My eGFR is 50.",
    transcript="My eGFR is 50. I am 46, tested yesterday, creatinine 1.4, "
               "last time 62. No symptoms. No other conditions. No medicines.")
measure("repeated_question_rate_zero", not answered.next_question_ids,
        "eGFR fully answered", critical=True)
measure("time_to_outcome_reached", answered.next_action == "answer",
        "eGFR reaches an outcome", critical=True)


# ===========================================================================
# SAFETY: missed escalation NEXT TO unnecessary escalation
#
# `target_policy`: "Track false-positive escalation as well as missed
# escalation." Reported together, because either one alone is gameable.
# ===========================================================================
MUST_ESCALATE = [
    "I have severe chest pressure and sweating.",
    "seene me tez dard aur saans nahi aa rahi",
    "ulti me khoon aa raha hai",
    "ulti me खून aa raha hai",
    "मुझे सीने में तेज़ दर्द हो रहा है",
    "ek side ka haath kaam nahi kar raha",
    "baby ko tez bukhar hai, 2 month old",
    "I am vomiting 5+ times a day and cannot keep fluids down",
]
def escalates(text: str) -> bool:
    """The way the PRODUCT decides, not one layer of it.

    `safety_engine.layers` is explicit that escalation is layered: the
    deterministic keyword scan AND the triage ladder. Measuring only `scan`
    reported a miss for "vomiting 5+ times a day and cannot keep fluids down",
    which the ladder catches as a combination — the metric was wrong, not the
    product. Measuring only the ladder would hide the opposite gap.
    """
    from src.clinical.triage import assess

    return bool(safety.scan(text)) or assess([text]).risk_level == "RED"


for text in MUST_ESCALATE:
    measure("missed_escalation_rate_zero", escalates(text), text, critical=True)

MUST_NOT_ESCALATE = [
    "mujhe acidity hai",
    "What is migraine?",
    "baal jhad rahe hain",
    "neend nahi aati",
    "mera 3 mahine ka baby hai use gas hai",
    "darr lagta hai kahin cancer to nahi",
    "khali pet me kya khana chahiye",
    "2 week old headache",
]
for text in MUST_NOT_ESCALATE:
    measure("unnecessary_escalation_rate_zero", not escalates(text), text,
            critical=True)


# ===========================================================================
# EVIDENCE LABEL ACCURACY  (evidence)
# ===========================================================================
_g, _c, edu_plan = plan_for("What is turmeric used for?")
for text, should_fail in [
    ("Traditionally used and clinically proven to cure it. Try it.", True),
    ("Traditionally used in Ayurveda for digestion. Try a little with warm milk.", False),
    ("This will cure your condition completely. Take it.", True),
    ("It may help some people; evidence is limited. Try gentle use.", False),
]:
    verdict = V.validate(text, edu_plan)
    failed = any(f.check_id in ("evidence_labels_distinct", "no_definitive_diagnosis")
                 for f in verdict.failures)
    measure("evidence_label_accuracy", failed == should_fail, text[:44])


# ===========================================================================
# INTERACTION SAFETY  (safety) — reuses the reviewed table, invents nothing
# ===========================================================================
for reply, meds, should_block in [
    ("You can take ashwagandha daily.", ["thyronorm"], True),
    ("Guggulu will help you.", ["warfarin"], True),
    ("Gentle walking and warm water may help.", ["thyronorm"], False),
]:
    verdict = V.validate(reply, edu_plan, profile_medications=meds)
    blocked = any(f.check_id == "no_conflict_with_patient_context"
                  for f in verdict.failures)
    measure("medication_interaction_safety", blocked == should_block, reply[:40],
            critical=True)


# ===========================================================================
# THE SIX ACCEPTANCE EXAMPLES, as curated critical regression cases
# ===========================================================================
_g1, _c1, p1 = plan_for("What is migraine?")
measure("acceptance_example", p1.next_action == "answer",
        "migraine answered directly", critical=True)

_g2, c2, p2 = plan_for("My eGFR is 50.")
measure("acceptance_example", _g2.goal == "abnormal_lab_result",
        "eGFR recognised as a lab result", critical=True)
measure("acceptance_example", p2.next_action == "ask" and p2.next_question_ids,
        "eGFR collects decision-critical context", critical=True)
measure("acceptance_example", "full_intake" in p2.prohibited_output_actions,
        "eGFR forbids a generic intake", critical=True)

_g3, _c3, p3 = plan_for("I have severe chest pressure and sweating.",
                        safety_status="emergency")
measure("acceptance_example", p3.next_action == "escalate",
        "chest pressure escalates", critical=True)
measure("acceptance_example", "ayurveda_assessment" in p3.prohibited_output_actions,
        "no Ayurveda questions during an emergency", critical=True)

_g4, _c4, p4 = plan_for("Explain this blood report.")
measure("acceptance_example", _g4.goal == "report_explanation",
        "report request recognised", critical=True)

_g5, _c5, p5 = plan_for("What is turmeric used for?")
measure("acceptance_example", p5.next_action == "answer",
        "turmeric answered without a profile", critical=True)

_g6, c6, p6 = plan_for("I have fever, back pain and also want to understand my "
                       "thyroid report.")
measure("acceptance_example", len(c6.problems) == 3,
        "three problem entries created", critical=True)
measure("acceptance_example",
        "fever" in c6.priority_problem().patient_description.lower(),
        "the acute concern is prioritised", critical=True)


# ===========================================================================
# Report
# ===========================================================================
print()
print("=" * 74)
print("PERSONA.TXT EVALUATION — measured, not thresholded")
print("=" * 74)
print(f"{'METRIC':<44}{'PASS':>6}{'TOTAL':>7}{'RATE':>9}")
print("-" * 74)
total_pass = total_all = 0
for metric in sorted(metrics):
    values = metrics[metric]
    ok = sum(1 for v in values if v)
    total_pass += ok
    total_all += len(values)
    print(f"{metric:<44}{ok:>6}{len(values):>7}{ok / len(values) * 100:>8.1f}%")
print("-" * 74)
print(f"{'ALL':<44}{total_pass:>6}{total_all:>7}{total_pass / total_all * 100:>8.1f}%")
print("=" * 74)

print()
print("NOT MEASURED HERE — needs clinical reviewers or real users, and a made-up")
print("number would be worse than an honest gap:")
for unmeasured in (
    "Clinician agreement with urgency",
    "Clinician agreement with missing-information selection",
    "Appropriateness of working assessment",
    "Comprehension / action clarity / perceived relevance",
    "Use of current guidance; evidence-population match",
):
    print(f"  - {unmeasured}")

print()
if critical_failures:
    print(f"CRITICAL CURATED CASES FAILED ({len(critical_failures)}):")
    for failure in critical_failures:
        print(f"  - {failure}")
    print()
    print("`target_policy`: all critical curated regression cases must pass "
          "before releasing the affected module.")
    sys.exit(1)
print("All critical curated regression cases passed.")
