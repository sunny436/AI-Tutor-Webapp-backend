"""
PHASE-3 — internal turn plan, question records and the sufficiency engine.

persona.txt, `internal_turn_plan.requirement`:

    "Generate structured control output before producing patient-facing text."

This is where the two reproduced failures are actually closed. PHASE-1 named
the exchange and PHASE-2 described the case; neither changed anything, because
nothing decided what to DO with them.

    "My eGFR is 50."  ->  must ASK age, test date, creatinine, previous
                          results — `universal_acceptance_examples` names
                          those four — and must not open an Ayurveda
                          consultation.

    "What is migraine?" -> must ANSWER. Criterion 2: "Simple educational
                          questions receive direct answers without a full
                          intake."

THE RULE THAT STOPS THE INTERROGATION is PRINCIPLE-005: every question must
carry a documented reason explaining what decision its answer could change. A
question with no recorded decision impact cannot be asked, so "asking to appear
thorough" is structurally impossible rather than discouraged.

    python tests/test_phase3_turnplan.py
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

import config  # noqa: E402
from src.clinical import turnplan as tp  # noqa: E402
from src.clinical.intent import classify  # noqa: E402
from src.clinical.problems import build  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, str(detail)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


def plan_for(text: str, **kw) -> tp.TurnPlan:
    goal = classify(text)
    case = build(text, goal=goal.goal, subject=goal.subject, depth=goal.mode,
                 safety_flags=kw.get("safety_flags") or [])
    return tp.plan(
        goal=goal.goal, goal_confidence=goal.confidence, subject=goal.subject,
        case=case, transcript=kw.get("transcript", text),
        safety_status=kw.get("safety_status", "routine"),
        mode=kw.get("mode", goal.mode), has_report=kw.get("has_report", False),
    )


# ===========================================================================
# 0. Flagged off; the schema matches `internal_turn_plan.schema`
# ===========================================================================
check("0. PHASE-3 ships disabled by default",
      config.PHASE3_TURN_PLAN is False, config.PHASE3_TURN_PLAN)
check("0b. the plan serialises to the spec's schema keys",
      set(tp.TurnPlan().as_dict()) == {
          "consultation_id", "current_goal", "goal_confidence", "subject",
          "active_problem_ids", "priority_problem_id", "safety_status",
          "triggered_safety_rule_ids", "known_decision_relevant_facts",
          "missing_decision_relevant_facts", "contradictions",
          "current_sufficiency", "next_action", "next_question_ids",
          "question_reason_codes", "evidence_query_plan", "allowed_output_types",
          "prohibited_output_actions", "requires_human_review",
          "human_review_reason"},
      sorted(tp.TurnPlan().as_dict()))
check("0c. all 6 sufficiency levels", len(tp.SUFFICIENCY) == 6, tp.SUFFICIENCY)
check("0d. all 8 next actions", len(tp.ACTIONS) == 8, tp.ACTIONS)
check("0e. all 8 decision-changed values", len(tp.DECISIONS) == 8, tp.DECISIONS)


# ===========================================================================
# 1. ACCEPTANCE — "My eGFR is 50."
# ===========================================================================
egfr = plan_for("My eGFR is 50.")
check("1a. THE eGFR CASE ASKS rather than lecturing", egfr.next_action == "ask",
      egfr.next_action)
check("1b. ...and knows it is not yet sufficient",
      egfr.current_sufficiency == "insufficient", egfr.current_sufficiency)

bank_ids = {q.question_id for q in tp.QUESTION_BANK["abnormal_lab_result"]}
for needed in ("age", "test_date", "previous_results", "related_values"):
    check(f"1c. the spec's named field is available to ask: {needed!r}",
          needed in bank_ids, sorted(bank_ids))

check("1d. THE SAFETY QUESTION IS ASKED FIRST, before interpretation",
      egfr.next_question_ids and egfr.next_question_ids[0] == "symptoms_now",
      egfr.next_question_ids)
check("1e. age is asked — the field the old reply never requested",
      "age" in egfr.next_question_ids, egfr.next_question_ids)
check("1f. AN AYURVEDA CONSULTATION IS FORBIDDEN on this turn",
      "full_intake" in egfr.prohibited_output_actions, egfr.prohibited_output_actions)
check("1g. the bundle stays compact, not a form",
      len(egfr.next_question_ids) <= 3, egfr.next_question_ids)
check("1h. every asked question carries a reason code",
      len(egfr.question_reason_codes) == len(egfr.next_question_ids),
      egfr.question_reason_codes)

# ...and once those facts are in the transcript, they are not asked again.
# `question_record.skip_if_known`, and `prohibited_question_behavior`:
# "Repeating information already available."
answered = plan_for(
    "My eGFR is 50.",
    # Every decision-relevant field for this goal, answered — including the
    # ones answered with a "no", which count exactly as much as a "yes".
    transcript="My eGFR is 50. I am 46 years old, tested yesterday, "
               "creatinine 1.4, last time it was 62. No symptoms. "
               "No other conditions. No medicines.",
)
check("1i. KNOWN FACTS ARE NOT ASKED AGAIN",
      "age" not in answered.next_question_ids, answered.next_question_ids)
check("1j. ...and the plan records what it already knows",
      "age" in answered.known_decision_relevant_facts,
      answered.known_decision_relevant_facts)
check("1k. once enough is known it stops asking and answers",
      answered.next_action == "answer", answered.next_action)


# ===========================================================================
# 2. ACCEPTANCE — educational questions are answered, not investigated
#
# Criterion 2, and the "What is migraine?" example: "Do not demand age,
# complete history or medicine list."
# ===========================================================================
for text in ["What is migraine?", "What is turmeric used for?",
             "What does metformin do?", "What treatments are available for migraine?",
             "Which health tests should I get at my age?"]:
    p = plan_for(text)
    check(f"2. answered without an intake: {text[:40]!r}",
          p.next_action == "answer" and not p.next_question_ids,
          f"{p.next_action} {p.next_question_ids}")
    check(f"2b. ...and a full intake is forbidden: {text[:32]!r}",
          "full_intake" in p.prohibited_output_actions, p.prohibited_output_actions)

check("2c. education is sufficient the moment it is understood",
      plan_for("What is migraine?").current_sufficiency == "sufficient_for_education")


# ===========================================================================
# 3. SAFETY INTERRUPTS EVERY MODE — PRINCIPLE-002, criterion 10
# ===========================================================================
for goal_text in ["What is migraine?", "My eGFR is 50.", "mujhe acidity hai"]:
    p = plan_for(goal_text, safety_status="emergency")
    check(f"3. emergency overrides the goal: {goal_text[:32]!r}",
          p.next_action == "escalate", p.next_action)
    check(f"3b. ...and forbids wellness output: {goal_text[:28]!r}",
          "wellness_plan" in p.prohibited_output_actions
          and "ayurveda_assessment" in p.prohibited_output_actions,
          p.prohibited_output_actions)
    check(f"3c. ...and asks no routine history: {goal_text[:28]!r}",
          not p.next_question_ids, p.next_question_ids)

urgent = plan_for("mujhe pet dard hai", safety_status="urgent")
check("3d. an urgent case asks only disposition-relevant questions",
      all(tp.QUESTION_BANK["new_symptom"] and
          next(q.rank for q in tp.QUESTION_BANK["new_symptom"] if q.question_id == qid) == 1
          for qid in urgent.next_question_ids) or not urgent.next_question_ids,
      urgent.next_question_ids)


# ===========================================================================
# 4. EVERY QUESTION HAS A DOCUMENTED PURPOSE — PRINCIPLE-005, criterion 6
# ===========================================================================
for goal, bank in tp.QUESTION_BANK.items():
    for q in bank:
        check(f"4. {goal}/{q.question_id} declares what it changes",
              bool(q.decision_changed) and all(d in tp.DECISIONS for d in q.decision_changed),
              q.decision_changed)
        check(f"4b. {goal}/{q.question_id} carries a reason code",
              q.reason_code in tp._RANK_REASON.values(), q.reason_code)


# ===========================================================================
# 5. BUNDLE POLICY — `adaptive_question_policy.question_bundle_policy`
#
# "Do not display a long intake form merely because many optional fields are
# unknown" is the prohibition; these are the shapes it allows.
# ===========================================================================
quick = plan_for("My eGFR is 50.", mode="quick")
check("5a. quick mode asks ONE question", len(quick.next_question_ids) == 1,
      quick.next_question_ids)
standard = plan_for("My eGFR is 50.", mode="standard")
check("5b. standard asks a compact bundle (2-5)",
      2 <= len(standard.next_question_ids) <= 5, standard.next_question_ids)
detailed = plan_for("My eGFR is 50.", mode="detailed")
check("5c. even detailed never becomes a form",
      len(detailed.next_question_ids) <= 5, detailed.next_question_ids)
check("5d. NO PLAN EVER ASKS THE WHOLE BANK",
      len(detailed.next_question_ids) < len(tp.QUESTION_BANK["abnormal_lab_result"]),
      len(detailed.next_question_ids))


# ===========================================================================
# 6. SUFFICIENCY — `consultation_sufficiency_engine`
# ===========================================================================
check("6a. education needs only understanding",
      tp.decide_sufficiency("general_education", ["age"]) == "sufficient_for_education")
check("6b. a report needs the report",
      tp.decide_sufficiency("report_explanation", [], has_report=False) == "insufficient")
check("6c. ...and is sufficient once it is there",
      tp.decide_sufficiency("report_explanation", [], has_report=True)
      == "sufficient_for_report_explanation")
check("6d. an emergency is sufficient for triage immediately",
      tp.decide_sufficiency("new_symptom", ["onset", "severity"],
                            safety_status="emergency") == "sufficient_for_triage")
check("6e. nothing missing means a working assessment is owed",
      tp.decide_sufficiency("new_symptom", []) == "sufficient_for_working_assessment")


# ===========================================================================
# 7. MULTI-PROBLEM — the plan follows the priority problem, not the last words
# ===========================================================================
multi_goal = classify("I have fever, back pain and also want to understand my thyroid report.")
multi_case = build("I have fever, back pain and also want to understand my thyroid report.",
                   goal=multi_goal.goal, subject=multi_goal.subject)
multi_plan = tp.plan(goal=multi_goal.goal, goal_confidence=multi_goal.confidence,
                     subject=multi_goal.subject, case=multi_case, transcript="")
check("7a. all three problems are carried on the plan",
      len(multi_plan.active_problem_ids) == 3, multi_plan.active_problem_ids)
check("7b. THE PLAN TARGETS THE ACUTE PROBLEM, not the report",
      multi_plan.priority_problem_id == multi_case.priority_problem().problem_id, "")
check("7c. ...and that problem is the fever",
      "fever" in multi_case.get(multi_plan.priority_problem_id).patient_description.lower(),
      multi_case.get(multi_plan.priority_problem_id).patient_description)


# ===========================================================================
# 8. REASONING PRIVACY — `internal_turn_plan.reasoning_privacy`
#
# "Do not expose hidden chain-of-thought. Store concise decision reasons, rule
# IDs, evidence IDs and question-purpose codes."
# ===========================================================================
sample = plan_for("My eGFR is 50.")
check("8a. reasons are short codes, never prose",
      all("_" in r and len(r) < 48 and " " not in r for r in sample.question_reason_codes),
      sample.question_reason_codes)
rendered = tp.render_questions(sample)
check("8b. only patient-facing text is rendered",
      rendered and not any(code in rendered for code in sample.question_reason_codes),
      rendered[:80])
check("8c. ...and no internal ids leak into it",
      not any(qid in rendered for qid in ("symptoms_now", "test_date")), rendered[:80])


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== phase3 turn plan: {passed}/{len(results)} passed =====")
if passed != len(results):
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name} :: {detail}")
    sys.exit(1)
