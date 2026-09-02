"""
PHASE-2 — the open problem representation.

persona.txt, `open_problem_representation.purpose`:

    "Maintain a disease-neutral view of the case until sufficient evidence
     supports a narrower assessment."

WHAT THIS FIXES, measured. "I have fever, back pain and also want to understand
my thyroid report" was answered with a single question about "the fever and
back pain, and clarity on your thyroid report" — three concerns flattened into
one complaint. Whichever the assistant then questioned about, the other two
were gone. `universal_acceptance_examples` requires three problem entries, the
acute one prioritised, and the report kept as a parallel concern.

THE RULES THIS SUITE ENFORCES are the four in `open_problem_representation`
that are easy to violate and expensive to violate quietly:

  - a problem does NOT require a disease name to exist;
  - several symptoms are NOT collapsed into one disease;
  - co-occurrence is NOT causality;
  - the differential is NEVER recited to the patient.

    python tests/test_phase2_problems.py
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
from src.clinical.problems import (  # noqa: E402
    PRIORITIES,
    PRIORITY_ORDER,
    PROBLEM_TYPES,
    STATUSES,
    OpenCase,
    build,
    classify_problem_type,
    from_episodes,
    rank_problem,
    render,
    split_concerns,
)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, str(detail)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


# ===========================================================================
# 0. FLAGGED OFF, and the schema matches the spec exactly
# ===========================================================================
check("0. PHASE-2 ships disabled by default",
      config.PHASE2_PROBLEM_MODEL is False, config.PHASE2_PROBLEM_MODEL)
check("0b. all 11 problem types from the spec", len(PROBLEM_TYPES) == 11, len(PROBLEM_TYPES))
check("0c. the four priority bands", set(PRIORITIES) ==
      {"critical", "high", "normal", "deferred"}, PRIORITIES)
check("0d. all 6 statuses from the spec", len(STATUSES) == 6, STATUSES)
check("0e. the 7 priority ranks from multi_problem_manager",
      len(PRIORITY_ORDER) == 7, len(PRIORITY_ORDER))
check("0f. the case serialises to the spec's schema keys",
      set(OpenCase().as_dict()) == {
          "consultation_id", "subject", "consultation_goal", "desired_depth",
          "problems", "known_facts", "important_unknowns", "contradictions",
          "active_safety_flags", "candidate_explanation_categories",
          "selected_next_action", "sufficiency_status"},
      sorted(OpenCase().as_dict()))


# ===========================================================================
# 1. ACCEPTANCE CASE — "fever, back pain and thyroid report"
#
# `universal_acceptance_examples`: "Create three problem entries. Check whether
# fever and back pain could be urgent. Prioritize the potentially acute
# concern. Keep the thyroid report as a deferred or parallel concern."
# Incorrect: "Forcing everything into one disease. Ignoring the fever because
# the thyroid report is structured."
# ===========================================================================
multi = build("I have fever, back pain and also want to understand my thyroid report.",
              goal="multiple_concerns", subject="self")
check("1a. THREE SEPARATE PROBLEMS, not one complaint",
      len(multi.problems) == 3, [p.patient_description for p in multi.problems])
check("1b. each keeps the person's own words",
      all(p.patient_description.strip() for p in multi.problems),
      [p.patient_description for p in multi.problems])
check("1c. the report is typed as a test, not as a symptom",
      any(p.problem_type == "abnormal_test" for p in multi.problems),
      [(p.patient_description[:24], p.problem_type) for p in multi.problems])
top = multi.priority_problem()
check("1d. THE ACUTE CONCERN IS PRIORITISED, not the structured report",
      top is not None and "fever" in top.patient_description.lower(),
      top.patient_description if top else None)
check("1e. ...for a recorded reason",
      top is not None and top.priority_reason == "acute_deterioration",
      top.priority_reason if top else None)
check("1f. the other concerns stay open, not discarded",
      len(multi.unresolved()) == 3, len(multi.unresolved()))
check("1g. THE STRUCTURED REPORT DOES NOT OUTRANK THE FEVER",
      top is not None and top.problem_type != "abnormal_test", top.problem_type if top else None)


# ===========================================================================
# 2. ACCEPTANCE CASE — "My eGFR is 50."
#
# It must be represented as an abnormal test, and the value must survive for
# the decision-critical questioning PHASE-3 will owe it.
# ===========================================================================
lab = build("My eGFR is 50.", goal="abnormal_lab_result", subject="self")
check("2a. one problem, typed as an abnormal test",
      len(lab.problems) == 1 and lab.problems[0].problem_type == "abnormal_test",
      [(p.patient_description, p.problem_type) for p in lab.problems])
check("2b. THE VALUE IS PRESERVED for later questioning",
      "50" in lab.problems[0].patient_description, lab.problems[0].patient_description)
check("2c. ...and so is the test name",
      "egfr" in lab.problems[0].patient_description.lower(), "")
check("2d. the goal and subject ride with the case",
      lab.consultation_goal == "abnormal_lab_result" and lab.subject == "self", "")
check("2e. no disease is named from one value",
      not lab.candidate_explanation_categories, lab.candidate_explanation_categories)


# ===========================================================================
# 3. THE FOUR RULES
# ===========================================================================
# "Do not require a disease name to create a problem."
vague = build("kuch theek nahi lag raha")
check("3a. a problem exists without any disease name",
      len(vague.problems) == 1, [p.patient_description for p in vague.problems])

# "Do not collapse several symptoms into one disease automatically."
check("3b. distinct concerns stay distinct",
      len(split_concerns("fever, back pain and thyroid report")) == 3,
      split_concerns("fever, back pain and thyroid report"))
check("3c. ...but one illness described twice is ONE problem",
      len(split_concerns("I have fever and fever since morning")) == 1,
      split_concerns("I have fever and fever since morning"))

# "Do not infer that two conditions are causally related merely because they
# co-occur." A relationship is a bare reference, never a direction or a cause.
rels = [p.possible_relationships for p in multi.problems]
check("3d. co-occurring problems are cross-referenced",
      all(len(r) == 2 for r in rels), rels)
check("3e. ...as bare ids, with NO causal claim recorded",
      all(all(isinstance(x, str) and " " not in x for x in r) for r in rels), rels)
check("3f. a lone problem claims no relationship",
      lab.problems[0].possible_relationships == [], lab.problems[0].possible_relationships)

# "Do not expose an overwhelming differential-diagnosis list to the patient."
block = render(multi)
check("3g. the prompt block names ONE priority concern",
      block.count("Priority concern:") == 1, block)
check("3h. ...and never recites a differential",
      "candidate" not in block.lower() and "differential" not in block.lower(), block)
check("3i. an empty case renders nothing", render(OpenCase()) == "")


# ===========================================================================
# 4. MULTI-PROBLEM MANAGER — the priority order, in the order the spec gives
#
# "Do not let a chronic condition distract from a new urgent symptom" is the
# one that matters most, and it is the one a naive sort gets wrong: the
# chronic problem is always the better described of the two.
# ===========================================================================
PRIORITY_CASES = [
    ("seene me tez dard aur saans nahi aa rahi", "critical", True),
    ("tez bukhar hai aur bahut kamzori", "critical", False),
    ("My eGFR is 50", "high", False),
    ("can I take ashwagandha with metformin", "high", False),
    ("which screening tests should I get", "deferred", False),
    ("ghutne me dard 3 saal se hai", "normal", False),
]
for text, want, flagged in PRIORITY_CASES:
    band, reason = rank_problem(text, safety_flagged=flagged)
    check(f"4. {want}: {text[:40]!r}", band == want, f"{band} ({reason})")

mixed = build("mujhe 5 saal se ghutne ka dard hai aur aaj tez bukhar aa gaya")
top_mixed = mixed.priority_problem()
check("4b. A NEW ACUTE SYMPTOM OUTRANKS A CHRONIC ONE",
      top_mixed is not None and "bukhar" in top_mixed.patient_description.lower(),
      top_mixed.patient_description if top_mixed else None)

preventive = build("which health tests should I get, and I have back pain")
check("4c. a preventive goal is deferred behind a live symptom",
      any(p.current_priority == "deferred" for p in preventive.problems),
      [(p.patient_description[:24], p.current_priority) for p in preventive.problems])
check("4d. ...and appears on the deferred list",
      len(preventive.deferred()) >= 1,
      [p.patient_description[:24] for p in preventive.deferred()])


# ===========================================================================
# 5. TYPING — disease-neutral, from the words used
# ===========================================================================
for text, want in [
    ("My creatinine is 2.1", "abnormal_test"),
    ("I feel hopeless", "mental_health"),
    ("I accidentally took too many tablets", "exposure"),
    ("can I take ashwagandha", "medicine_question"),
    ("which screening tests at my age", "preventive_goal"),
    ("mujhe pet dard hai", "symptom"),
]:
    check(f"5. type {want}: {text[:36]!r}", classify_problem_type(text) == want,
          classify_problem_type(text))


# ===========================================================================
# 6. THE BRIDGE FROM EPISODES
#
# Episodes stay the durable, client-persisted record; this is the working view.
# Building the view must not merge what episodes kept apart.
# ===========================================================================
from src.clinical import episodes as ep  # noqa: E402

eps, _acid, _ = ep.select([], "mujhe acidity hai", "Acidity")
eps, knee, _ = ep.select(eps, "ab ghutne me dard hai", "Knee Pain")
case = from_episodes(eps, active_episode_id=knee.episode_id, subject="self")
check("6a. every episode becomes its own problem",
      len(case.problems) == 2, [p.patient_description for p in case.problems])
check("6b. EPISODE SEPARATION SURVIVES the conversion",
      len({p.problem_id for p in case.problems}) == 2, "")
check("6c. episode ids are preserved, so the two records stay joinable",
      {p.problem_id for p in case.problems} == {e.episode_id for e in eps}, "")
check("6d. the active episode is never left deferred",
      case.get(knee.episode_id).current_priority != "deferred",
      case.get(knee.episode_id).current_priority)


# ===========================================================================
# 7. SAFETY IS UNTOUCHED. This phase describes the case; it must not be able
#    to soften what the safety layer says about it.
# ===========================================================================
from src import safety  # noqa: E402

for text in ["ulti me khoon aa raha hai",
             "I have severe chest pressure and sweating.",
             "seene me tez dard aur saans nahi aa rahi"]:
    case_s = build(text, safety_flags=["red_flag"])
    check(f"7. a flagged case is critical: {text[:34]!r}",
          case_s.priority_problem().current_priority == "critical",
          case_s.priority_problem().current_priority)
    check(f"7b. ...and the red flag itself still fires: {text[:28]!r}",
          bool(safety.scan(text)), "")


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== phase2 open problems: {passed}/{len(results)} passed =====")
if passed != len(results):
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name} :: {detail}")
    sys.exit(1)
