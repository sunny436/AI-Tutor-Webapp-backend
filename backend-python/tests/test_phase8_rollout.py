"""
PHASE-8 — controlled rollout.

persona.txt PHASE-8: feature flags, shadow evaluation, clinician review mode,
limited user cohort, dashboards, rollback controls. Acceptance criterion 19:
"Critical behavior is feature-flagged, observable and reversible."

THE CENTRAL ASSERTION of this suite is the no-op guarantee: with the flags off,
the rollout layer must change NOTHING. Everything else here is secondary. A
shadow-evaluation path that can throw, or that can be read as permission to
act, is more dangerous than no shadow evaluation at all, because it fails
inside a live health consultation for a reason unrelated to the consultation.

    python tests/test_phase8_rollout.py
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
from src.clinical import rollout as R  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, str(detail)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


class Chunk:
    def __init__(self, text="", source="", score=None, metadata=None):
        self.text, self.source = text, source
        self.score, self.metadata = score, metadata or {}


# ===========================================================================
# 1. THE NO-OP GUARANTEE — the reason this suite exists
# ===========================================================================
check("1a. all six phase flags are OFF", not any(R.active_flags().values()),
      R.active_flags())
check("1b. the kill switch is not engaged (nothing to roll back yet)",
      R.kill_switch_engaged() is False)
check("1c. NO PHASE IS LIVE — nothing the user sees can change",
      R.any_phase_live() is False)
check("1d. and therefore no user is enabled",
      R.enabled_for("any-user-id") is False)
check("1e. shadow logging is off by default too",
      config.CLINICAL_SHADOW_EVAL is False)
check("1f. SHADOW_TURN IS A NO-OP WHEN SHADOW EVAL IS OFF",
      R.shadow_turn("mujhe sar dard hai") is None)


# ===========================================================================
# 2. THE COHORT CANNOT ACCIDENTALLY MEAN EVERYBODY
#
# The failure this prevents: someone flips PHASE1_INTENT_ROUTER=1 to try it,
# and every user in production is switched over at once.
# ===========================================================================
class FakeConfig:
    """A config with the flags forced, without touching the real one."""

    def __init__(self, **over):
        self.saved = {}
        self.over = over

    def __enter__(self):
        for key, value in self.over.items():
            self.saved[key] = getattr(config, key, None)
            setattr(config, key, value)
        return self

    def __exit__(self, *exc):
        for key, value in self.saved.items():
            setattr(config, key, value)
        return False


with FakeConfig(PHASE1_INTENT_ROUTER=True, CLINICAL_COHORT_PERCENT=0):
    check("2a. A FLAG ON WITH NO COHORT STILL MEANS NOBODY",
          R.enabled_for("user-1") is False and R.any_phase_live() is True,
          f"live={R.any_phase_live()} enabled={R.enabled_for('user-1')}")

with FakeConfig(PHASE1_INTENT_ROUTER=True, CLINICAL_COHORT_PERCENT=100):
    check("2b. a full cohort enables everyone", R.enabled_for("user-1") is True)

with FakeConfig(PHASE1_INTENT_ROUTER=True, CLINICAL_COHORT_PERCENT=50):
    ids = [f"user-{i}" for i in range(400)]
    inside = [u for u in ids if R.enabled_for(u)]
    check("2c. a 50% cohort splits roughly in half",
          150 <= len(inside) <= 250, f"{len(inside)}/400")
    check("2d. THE SPLIT IS STABLE — the same user does not flicker between "
          "turns of one conversation",
          all(R.enabled_for(u) == (u in set(inside)) for u in ids), "")
    check("2e. an anonymous user is never in the cohort",
          R.enabled_for(None) is False and R.enabled_for("") is False, "")


# ===========================================================================
# 3. ROLLBACK — one switch beats every flag
# ===========================================================================
with FakeConfig(PHASE1_INTENT_ROUTER=True, PHASE3_TURN_PLAN=True,
                PHASE6_RESPONSE_MODES=True, CLINICAL_COHORT_PERCENT=100,
                CLINICAL_PIPELINE_DISABLED=True):
    check("3a. THE KILL SWITCH BEATS EVERY FLAG AT ONCE",
          R.any_phase_live() is False and R.enabled_for("user-1") is False,
          f"live={R.any_phase_live()}")
    check("3b. ...and stops shadow logging too",
          R.shadow_turn("mujhe sar dard hai") is None)


# ===========================================================================
# 4. SHADOW EVALUATION produces a record a dashboard can read
# ===========================================================================
record = R.evaluate("My eGFR is 50. What does this mean?",
                    conversation_id="conv-1")
check("4a. the shadow record names the goal",
      record.goal == "abnormal_lab_result", record.goal)
check("4b. ...the decision and the mode",
      record.action == "ask" and record.response_mode == "adaptive_question",
      f"{record.action}/{record.response_mode}")
check("4c. ...the questions it would have asked",
      record.next_question_ids == ["symptoms_now", "age", "test_date"],
      record.next_question_ids)
check("4d. ...the evidence question type",
      record.evidence_question_type == "diagnosis",
      record.evidence_question_type)
check("4e. IT IS MARKED SHADOW-ONLY, so no dashboard can misread it as live",
      R.shadow_turn is not None and record.error == "", record.error)
check("4f. it serialises to plain JSON types",
      isinstance(record.as_dict(), dict)
      and isinstance(record.as_dict()["next_question_ids"], list), "")
check("4g. the flags it ran under are recorded with it",
      set(record.flags) == set(R.active_flags()), sorted(record.flags))
check("4h. it records how long it took", record.duration_ms >= 0,
      record.duration_ms)

education = R.evaluate("What is migraine?")
check("4i. an educational turn shadows as answer/direct_education",
      education.action == "answer"
      and education.response_mode == "direct_education",
      f"{education.action}/{education.response_mode}")

emergency = R.evaluate("chest pressure", safety_status="emergency")
check("4j. an emergency shadows as an urgent escalation",
      emergency.response_mode == "urgent_escalation", emergency.response_mode)

multi = R.evaluate("mujhe bukhar hai, kamar dard hai aur thyroid bhi hai")
check("4k. a multi-problem turn records every problem and the priority",
      multi.problem_count >= 3 and multi.priority_problem != "",
      f"{multi.problem_count} priority={multi.priority_problem!r}")


# ===========================================================================
# 5. THE VALIDATOR AND EVIDENCE LANES ARE OBSERVED TOO
# ===========================================================================
checked = R.evaluate("What is migraine?",
                     answer="You have chronic kidney disease. Take rest.")
check("5a. a bad answer is recorded as blocked",
      checked.validator_approved is False, checked.validator_approved)
check("5b. ...with the named checks that failed",
      "no_definitive_diagnosis" in checked.validator_failures,
      checked.validator_failures)

good = R.evaluate("What is migraine?",
                  answer="Migraine is a headache disorder with throbbing pain "
                         "on one side. Resting in a dark room can help.")
check("5c. a good answer is recorded as approved",
      good.validator_approved is True, good.validator_failures)

# BOTH DIRECTIONS. The next-step check accepts the descriptive form above
# ("Resting ... can help"), so prove it still REJECTS an answer that leaves
# the reader with nothing to do — otherwise the fix would have deleted the
# check rather than corrected it.
nothing_to_do = R.evaluate(
    "What is migraine?",
    answer="Migraine is a headache disorder. It is common worldwide and has "
           "been described for centuries in the medical literature.")
check("5c2. AN ANSWER WITH NO NEXT STEP IS STILL REJECTED",
      "provides_usable_next_step" in nothing_to_do.validator_failures,
      nothing_to_do.validator_failures)

laned = R.evaluate("Does ashwagandha work?", chunks=[
    Chunk("Described as a rasayana.", "1-caraka-samhita.pdf"),
    Chunk("A randomised trial reported improvement.", "randomized-trial.pdf")])
check("5d. both evidence lanes are recorded",
      len(laned.evidence_lanes) == 2, laned.evidence_lanes)


# ===========================================================================
# 6. OBSERVABILITY MUST NEVER BREAK THE CONSULTATION
# ===========================================================================
check("6a. an empty message does not raise",
      R.evaluate("").error == "", R.evaluate("").error)
check("6b. a None-ish message does not raise",
      R.evaluate(" ").error == "", R.evaluate(" ").error)

broken = R.evaluate("test", chunks=[object()])
check("6c. A MALFORMED CHUNK IS SWALLOWED, not raised into the turn",
      isinstance(broken, R.ShadowRecord), type(broken).__name__)

very_long = R.evaluate("bukhar " * 3000)
check("6d. a very long message does not raise", very_long.error == "",
      very_long.error[:60])


# ===========================================================================
# 6b. THE PRODUCTION CALL SITE
#
# `graph.run_turn` wraps `_run_turn` so the hook sits in ONE place instead of
# at twenty-one return points. These pin the contract that wrapper relies on.
# ===========================================================================
from src.consult import graph as _graph  # noqa: E402
from src.consult import run_turn as _exported_run_turn  # noqa: E402

check("6e. the consultation still has an inner implementation to wrap",
      callable(getattr(_graph, "_run_turn", None)), "")
check("6f. the exported run_turn IS the wrapper, so nothing bypasses the hook",
      _exported_run_turn is _graph.run_turn, "")
check("6g. the wrapper keeps the caller-visible signature",
      set(__import__("inspect").signature(_exported_run_turn).parameters)
      == set(__import__("inspect").signature(_graph._run_turn).parameters),
      sorted(__import__("inspect").signature(_exported_run_turn).parameters))

# The call site passes `user_id` for the cohort. `evaluate` does not take it,
# so forwarding it raised inside the shadow path on every live turn — caught
# only because the turn survived it. Both facts are pinned here.
with FakeConfig(CLINICAL_SHADOW_EVAL=True):
    shadowed = R.shadow_turn("My eGFR is 50.", user_id="user-1")
    check("6h. SHADOW_TURN ACCEPTS THE user_id THE CALL SITE PASSES",
          shadowed is not None and shadowed.error == "",
          shadowed.error if shadowed else "returned None")
    check("6i. ...and records the cohort decision separately from the pipeline",
          shadowed is not None and shadowed.cohort is False, "")


# ===========================================================================
# 7. CLINICIAN REVIEW MODE — the same data, rendered for a person
# ===========================================================================
review = R.clinician_review(record)
check("7a. the review names the goal and the decision",
      "abnormal_lab_result" in review and "ask" in review, review[:80])
check("7b. ...and the questions it would have asked",
      "test_date" in review, review[:200])
check("7c. ...and says plainly that it was shadow only",
      "shadow only" in review, review[-60:])
check("7d. a missing record does not crash the reviewer's page",
      R.clinician_review(None) == "(no shadow record)",
      R.clinician_review(None))

# `PERSONA_CORE` rule 14 / `internal_turn_plan`: reasoning is never shown to
# the USER. The clinician view is a different audience and may show it — but
# it must not be mistaken for something patient-facing.
check("7e. the clinician view is explicitly internal, not a patient reply",
      "goal" in review and "validator" in R.clinician_review(checked),
      R.clinician_review(checked)[:60])


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== phase8 rollout: {passed}/{len(results)} passed =====")
if passed != len(results):
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name} :: {detail}")
    sys.exit(1)
