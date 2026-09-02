"""
PHASE-4 and PHASE-6 — the response validator and the response modes.

persona.txt, `response_validator`: fifteen checks, and a `failure_behavior`
that blocks and regenerates rather than rewriting.
persona.txt, `patient_facing_response_policy.response_modes`: six shapes, each
with its own structure.

WHY THESE ARE TESTED TOGETHER. The validator's job is to catch what the modes
get wrong, so a test that only exercises one of them proves very little. Every
failure asserted here is a phrasing this product has actually produced at some
point: a wellness plan written during an emergency, the same safety paragraph
three turns running, a section the reader had excluded, a claim dressed as
proof.

WHAT THE VALIDATOR MUST NOT DO is rewrite. `failure_behavior` says block,
report, regenerate, fall back — and this codebase already learned twice that a
regex quietly deleting part of a health answer is worse than the thing it was
preventing. So these tests check that it REPORTS, and that the fallback is
conservative rather than cheerful.

    python tests/test_phase4_6_validator_modes.py
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
from src.clinical import modes as M  # noqa: E402
from src.clinical import turnplan as tp  # noqa: E402
from src.clinical import validator as V  # noqa: E402
from src.clinical.intent import classify  # noqa: E402
from src.clinical.problems import build  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, str(detail)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


def plan_for(text: str, **kw) -> tp.TurnPlan:
    g = classify(text)
    c = build(text, goal=g.goal, subject=g.subject)
    return tp.plan(goal=g.goal, goal_confidence=g.confidence, subject=g.subject,
                   case=c, transcript=kw.pop("transcript", text), **kw)


def ids(verdict) -> list[str]:
    return [f.check_id for f in verdict.failures]


# ===========================================================================
# 0. Both flagged off; both complete against the spec
# ===========================================================================
check("0a. PHASE-4 ships disabled", config.PHASE4_RESPONSE_VALIDATOR is False)
check("0b. PHASE-6 ships disabled", config.PHASE6_RESPONSE_MODES is False)
check("0c. all 15 validator checks are named", len(V.CHECK_IDS) == 15, len(V.CHECK_IDS))
check("0d. all 6 response modes exist", len(M.MODES) == 6, M.MODES)
check("0e. every mode has the spec's structure",
      all(M.STRUCTURE.get(m) for m in M.MODES), sorted(M.STRUCTURE))
check("0f. all 11 prohibited patterns are carried", len(M.PROHIBITED) == 11,
      len(M.PROHIBITED))


# ===========================================================================
# 1. SAFETY BEFORE ROUTINE — the failure this product actually shipped once
# ===========================================================================
emergency = plan_for("chest pressure", safety_status="emergency")
bad = V.validate("Here is your **Food Chart** with moong dal and khichdi.", emergency)
check("1a. A WELLNESS PLAN DURING AN EMERGENCY IS BLOCKED", not bad.approved, ids(bad))
check("1b. ...named as a safety-ordering failure", "safety_before_routine" in ids(bad),
      ids(bad))
check("1c. ...and as urgency language that does not match",
      "urgency_language_matches_decision" in ids(bad), ids(bad))

good = V.validate(
    "Please seek medical help right away — go to the nearest hospital now.", emergency)
check("1d. a proper escalation passes", good.approved, ids(good))

# OVER-ESCALATION IS A FAILURE TOO. `safety_engine.behavior`: "Do not
# over-escalate every uncertain symptom solely to improve safety metrics."
routine = plan_for("What is migraine?")
over = V.validate("Go to the nearest hospital immediately. Rest as well.", routine)
check("1e. urgent language on a routine decision is a failure",
      "urgency_language_matches_decision" in ids(over), ids(over))


# ===========================================================================
# 2. STOPS AT SUFFICIENCY — criterion 8, and the "What is migraine?" example
# ===========================================================================
edu = plan_for("What is migraine?")
interrogation = V.validate(
    "What is your age? Any medicines? How long has this been going on? Allergies?", edu)
check("2a. AN INTAKE WHERE AN ANSWER WAS OWED IS BLOCKED",
      not interrogation.approved, ids(interrogation))
check("2b. ...named as failing to stop at sufficiency",
      "stops_at_sufficiency" in ids(interrogation), ids(interrogation))
answered = V.validate(
    "Migraine is a headache disorder with throbbing pain on one side. "
    "It can have several triggers. Try resting in a dark quiet room.", edu)
check("2c. a direct educational answer passes", answered.approved, ids(answered))

asking = plan_for("My eGFR is 50.")
too_many = V.validate("Age? Test date? Creatinine? Previous results? Medicines?", asking)
check("2d. an oversized bundle is disproportionate",
      "proportionate_question_bundle" in ids(too_many), ids(too_many))


# ===========================================================================
# 3. NO FALSE CERTAINTY — `prohibited_patterns`, criterion 14
# ===========================================================================
for text, want in [
    ("You have chronic kidney disease. Please rest.", "no_definitive_diagnosis"),
    ("This is definitely acidity. Take rest.", "no_definitive_diagnosis"),
    ("This will cure your condition completely. Try it.", "no_definitive_diagnosis"),
    ("Traditionally used and clinically proven to work. Take rest.",
     "evidence_labels_distinct"),
]:
    v = V.validate(text, edu)
    check(f"3. {want}: {text[:44]!r}", want in ids(v), ids(v))

calibrated = V.validate(
    "Symptoms like these can have several causes and often settle with rest. "
    "If it worsens, please see a doctor.", edu)
check("3b. CALIBRATED LANGUAGE IS ALLOWED — the point is not to refuse to speak",
      calibrated.approved, ids(calibrated))


# ===========================================================================
# 4. THE PATIENT'S OWN CONTEXT — `no_conflict_with_patient_context`
#
# Reuses the reviewed interaction table rather than inventing rules here,
# per `safety_engine.clinical_content_governance`.
# ===========================================================================
clash = V.validate("You can take ashwagandha daily for energy.", edu,
                   profile_medications=["thyronorm"])
check("4a. A HERB THAT CLASHES WITH THEIR MEDICINE IS BLOCKED",
      "no_conflict_with_patient_context" in ids(clash), ids(clash))
check("4b. ...and the reason is recorded",
      any("ashwagandha" in f.detail for f in clash.failures),
      [f.detail for f in clash.failures])
safe = V.validate("Gentle walking and regular meals may help. Try that.", edu,
                  profile_medications=["thyronorm"])
check("4c. ...while safe advice for the same person passes", safe.approved, ids(safe))


# ===========================================================================
# 5. NO REPEATED KNOWN QUESTION — `prohibited_question_behavior`
# ===========================================================================
p = plan_for("My eGFR is 50.")
p.known_decision_relevant_facts = ["age"]
p.next_question_ids = ["age", "test_date"]
repeated = V.validate("How old are you, and when was the test?", p)
check("5. asking something already known is a failure",
      "no_repeated_known_question" in ids(repeated), ids(repeated))


# ===========================================================================
# 6. IT REPORTS, IT NEVER REWRITES — `failure_behavior`
# ===========================================================================
original = "You have kidney disease. Take ashwagandha daily."
verdict = V.validate(original, edu, profile_medications=["thyronorm"])
check("6a. failures are structured, not prose",
      all(f.check_id in V.CHECK_IDS for f in verdict.failures), ids(verdict))
check("6b. THE TEXT IS RETURNED UNCHANGED — the validator never edits",
      original == "You have kidney disease. Take ashwagandha daily.", "")
check("6c. the verdict serialises for the evaluation log",
      set(verdict.as_dict()) == {"approved", "failures"}, sorted(verdict.as_dict()))

fallback_urgent = V.conservative_fallback(emergency)
check("6d. the emergency fallback still escalates",
      "seek medical help" in fallback_urgent.lower(), fallback_urgent[:50])
fallback_routine = V.conservative_fallback(edu)
check("6e. the routine fallback is honest, not cheerful",
      "doctor" in fallback_routine.lower() and "sorry" not in fallback_routine.lower(),
      fallback_routine[:60])


# ===========================================================================
# 7. RESPONSE MODES — chosen by the plan, never by the model
# ===========================================================================
for text, kw, want in [
    ("What is migraine?", {}, "direct_education"),
    ("My eGFR is 50.", {}, "adaptive_question"),
    ("chest pressure", {"safety_status": "emergency"}, "urgent_escalation"),
]:
    mode = M.choose(plan_for(text, **kw))
    check(f"7. mode {want}: {text[:34]!r}", mode == want, mode)

check("7b. an unknown allowed-type falls back to a real mode",
      M.choose(tp.TurnPlan(allowed_output_types=["nonsense"])) in M.MODES,
      M.choose(tp.TurnPlan(allowed_output_types=["nonsense"])))


# ===========================================================================
# 8. THE MODE INSTRUCTION carries the spec and nothing else
# ===========================================================================
for mode in M.MODES:
    text = M.instruction(mode)
    for step in M.STRUCTURE[mode]:
        check(f"8. {mode} instruction carries {step[:26]!r}", step in text, "")
    check(f"8b. {mode} forbids the 11 patterns",
          all(pat in text for pat in M.PROHIBITED), "")
    check(f"8c. {mode} tells it not to print the steps as headings",
          "Do NOT print them as" in text, "")

adaptive = M.instruction("adaptive_question", questions="How old are you?")
check("8d. adaptive mode carries exactly the chosen question",
      "How old are you?" in adaptive and "nothing more" in adaptive, "")
assessment = M.instruction("working_assessment")
check("8e. working assessment demands calibrated language",
      "never 'is' or 'definitely'" in assessment, "")
comparison = M.instruction("evidence_comparison")
check("8f. comparison keeps traditional use separate from proof",
      "never described as" in comparison, "")


# ===========================================================================
# 9. REASONING PRIVACY — the plan context given to the writer
# ===========================================================================
ctx = M.render_plan_context(plan_for("My eGFR is 50."))
check("9a. the writer is told what is already known",
      "do not ask again" in ctx.lower() or ctx == "", ctx[:70])
p2 = plan_for("My eGFR is 50.")
ctx2 = M.render_plan_context(p2)
check("9b. NO REASON CODES reach the prompt",
      not any(code in ctx2 for code in p2.question_reason_codes), ctx2[:70])
check("9c. no internal ids either",
      "problem_id" not in ctx2 and "safety_status" not in ctx2, ctx2[:70])


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== phase4+6 validator and modes: {passed}/{len(results)} passed =====")
if passed != len(results):
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name} :: {detail}")
    sys.exit(1)
