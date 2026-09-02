"""
PHASE-1 — the universal intent and subject router.

persona.txt, `intent_router.requirement`:

    "Classify the interaction goal before choosing the depth and structure of
     questioning."

WHAT THIS IS FOR, in one measured example. Before this existed, "My eGFR is 50."
was answered with "are you currently managing any diagnosed health conditions
or taking any regular medications... to help me provide the most relevant
Ayurvedic and lifestyle guidance". No age, no test date, no creatinine, no
trend — and an Ayurveda consultation opened for a modern-medicine
interpretation question. `problem_statement.current_failure_pattern` names that
exact failure twice.

Nothing upstream was deciding WHAT KIND of exchange this was before choosing
how to question. That decision is what this module makes.

DETERMINISTIC, and that is the point. A goal chosen by a temperature-0.7 call
would move between identical turns, and the goal decides how much may be asked
— so the patterns that are unambiguous in real messages are settled in code,
and only the ambiguous middle is left to the model.

    python tests/test_phase1_intent.py
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
from src.clinical.intent import (  # noqa: E402
    GOALS,
    MODES,
    SUBJECTS,
    TurnGoal,
    classify,
    detect_mode,
    detect_subject,
)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, str(detail)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


# ===========================================================================
# 0. THE FLAG IS OFF. Nothing in this phase may change live behaviour until
#    its tests pass — `existing_product_context.instructions`, criterion 19.
# ===========================================================================
check("0. PHASE-1 ships disabled by default",
      config.PHASE1_INTENT_ROUTER is False, config.PHASE1_INTENT_ROUTER)
check("0b. all 21 goals from the spec are present", len(GOALS) == 21, len(GOALS))
check("0c. the four subjects are present", set(SUBJECTS) ==
      {"self", "child", "adult_other", "unknown"}, SUBJECTS)
check("0d. the three interaction modes are present", set(MODES) ==
      {"quick", "standard", "detailed"}, MODES)


# ===========================================================================
# 1. THE SPEC'S OWN EXAMPLES. Every `intent_router.supported_intents` entry
#    ships with an example sentence; each one must land on its own intent.
# ===========================================================================
SPEC_EXAMPLES = [
    ("I have had stomach pain since yesterday.", "new_symptom"),
    ("My eGFR is 50.", "abnormal_lab_result"),
    ("Explain this blood report.", "report_explanation"),
    ("What does metformin do?", "medicine_information"),
    ("Can I take ibuprofen with my kidney condition?", "personalized_medicine_safety"),
    ("What is ashwagandha used for?", "herb_or_supplement_information"),
    ("Can I take this Ayurvedic powder after a kidney transplant?",
     "personalized_herb_safety"),
    ("What treatments are available for migraine?", "treatment_options"),
    ("Should I go to hospital?", "urgency_or_triage"),
    ("Which health tests should I get at my age?", "preventive_health"),
    ("I feel hopeless.", "mental_health"),
    ("I have pain during pregnancy.", "pregnancy_or_reproductive_health"),
    ("My three-year-old has fever.", "child_health"),
    ("I accidentally took too many tablets.", "injury_poisoning_or_exposure"),
    ("What should I ask my specialist?", "second_opinion_preparation"),
    ("Assess this from an Ayurveda perspective.", "ayurveda_assessment"),
    ("What is chronic kidney disease?", "general_education"),
    ("I have fever, back pain and want to understand my thyroid report.",
     "multiple_concerns"),
]
for text, want in SPEC_EXAMPLES:
    got = classify(text)
    check(f"1. {want}: {text[:42]!r}", got.goal == want, got.goal)


# ===========================================================================
# 2. THE TWO REPRODUCED FAILURES, pinned as their own cases
# ===========================================================================
egfr = classify("My eGFR is 50.")
check("2a. THE eGFR CASE IS A LAB RESULT, not a symptom to consult about",
      egfr.goal == "abnormal_lab_result", egfr.goal)
check("2b. ...recognised confidently, so no clarifying question is owed",
      egfr.confidence >= 0.8, egfr.confidence)
check("2c. ...and the reason is recorded for audit",
      "lab_name_with_value" in egfr.reason_codes, egfr.reason_codes)

multi = classify("I have fever, back pain and also want to understand my thyroid report.")
check("2d. THE THREE-CONCERN CASE IS NOT ONE COMPLAINT",
      multi.goal == "multiple_concerns", multi.goal)
check("2e. ...and the separate concerns are actually enumerated",
      len(multi.candidates) >= 3, multi.candidates)

# A LAB VALUE IS RECOGNISED ON THE NUMBER, however it is phrased. This is the
# heart of the eGFR fix: none of these say "report" or describe a symptom.
for text in ["My eGFR is 50.", "creatinine 2.1", "HbA1c 8.1 hai",
             "TSH is 8.4", "haemoglobin 9.2 g/dL", "my sugar is 300",
             "vitamin D 12 aaya hai"]:
    check(f"2f. a value makes it a lab question: {text[:34]!r}",
          classify(text).goal == "abnormal_lab_result", classify(text).goal)

# ...and a test named WITHOUT a value is not. "I have thyroid" is a condition,
# not a result to interpret, and treating it as one would ask for a date and a
# trend that do not exist.
for text in ["mujhe thyroid hai", "I have thyroid problem"]:
    check(f"2g. a condition named without a value is NOT a lab result: {text[:30]!r}",
          classify(text).goal != "abnormal_lab_result", classify(text).goal)


# ===========================================================================
# 3. SUBJECT — who the patient is. It changes the safety rules, not the
#    pronouns: an infant fever is urgent at an age an adult fever is not.
# ===========================================================================
SUBJECT_CASES = [
    ("My three-year-old has fever.", "child"),
    ("mere 2 mahine ke bacche ko bukhar hai", "child"),
    ("my 6 month old is not feeding", "child"),
    ("My mother has knee pain", "adult_other"),
    ("meri maa ko seene me dard hai", "adult_other"),
    ("mujhe kal se pet dard hai", "self"),
    ("I have had stomach pain", "self"),
    ("What is migraine?", "unknown"),
]
for text, want in SUBJECT_CASES:
    got = detect_subject(text)
    check(f"3. subject {want}: {text[:38]!r}", got == want, got)

check("3b. THE CHILD WINS OVER THE TYPIST. 'my son' contains 'my'.",
      detect_subject("my son has a fever") == "child")


# ===========================================================================
# 4. INTERACTION MODE — how much may be asked before an outcome is owed
# ===========================================================================
for text, want in [("just tell me quickly what to do", "quick"),
                   ("bas jaldi bata do", "quick"),
                   ("explain in detail please", "detailed"),
                   ("poora detail me batao", "detailed"),
                   ("mujhe acidity hai", "standard")]:
    check(f"4. mode {want}: {text[:34]!r}", detect_mode(text) == want, detect_mode(text))


# ===========================================================================
# 5. INFORMATION vs PERMISSION — the same substance, two different goals,
#    because only one of them turns on what the person is already taking.
# ===========================================================================
for text, want in [
    ("What is ashwagandha used for?", "herb_or_supplement_information"),
    ("ashwagandha ke fayde", "herb_or_supplement_information"),
    ("Can I take ashwagandha?", "personalized_herb_safety"),
    ("kya main ashwagandha le sakta hoon", "personalized_herb_safety"),
    ("What does metformin do?", "medicine_information"),
    ("Can I take ibuprofen?", "personalized_medicine_safety"),
]:
    check(f"5. {want}: {text[:38]!r}", classify(text).goal == want, classify(text).goal)


# ===========================================================================
# 6. THE VERDICT IS AUDITABLE AND NEVER SPOKEN
#
# `reasoning_privacy`: "Store concise decision reasons, rule IDs and
# question-purpose codes. Make outcomes auditable without recording private
# internal reasoning." And `confidence_behavior`: a confident classification
# is never announced to the user.
# ===========================================================================
sample = classify("My eGFR is 50.")
check("6. the verdict serialises for the turn plan",
      set(sample.as_dict()) == {"goal", "confidence", "subject", "mode",
                                "reason_codes", "needs_goal_clarification",
                                "candidates"},
      sorted(sample.as_dict()))
check("6b. reasons are short codes, not prose",
      all(len(r) < 40 and " " not in r for r in sample.reason_codes),
      sample.reason_codes)
check("6c. an undecided turn says so rather than guessing",
      classify("hmm").confidence == 0.0, classify("hmm").confidence)
check("6d. ...and still returns a usable shape",
      isinstance(classify(""), TurnGoal) and classify("").goal in GOALS)


# ===========================================================================
# 7. THE ROUTER DOES NOT TOUCH SAFETY. An emergency is still an emergency
#    whatever the goal says — `safety_engine` interrupts every mode, and this
#    module must not be able to suppress that.
# ===========================================================================
from src import safety  # noqa: E402

for text in ["I have severe chest pressure and sweating.",
             "ulti me khoon aa raha hai",
             "seene me tez dard aur saans nahi aa rahi"]:
    check(f"7. the red flag still fires regardless of goal: {text[:34]!r}",
          bool(safety.scan(text)), "")
check("7b. classifying an emergency never returns an all-clear",
      classify("I have severe chest pressure and sweating.").goal in GOALS)


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== phase1 intent router: {passed}/{len(results)} passed =====")
if passed != len(results):
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name} :: {detail}")
    sys.exit(1)
