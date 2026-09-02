# The clinical pipeline (persona.txt PHASES 1–8)

`backend-python/persona.txt` is the specification. This document is the map
from that specification to the code, for two audiences: the developer who has
to change it, and the clinical reviewer who has to sign off on what it does.

**Nothing here is live yet.** Every phase ships behind a flag that defaults to
off. With the flags off, the product behaves exactly as it did before this work
landed. See [Rollout](#rollout-phase-8).

---

## Where each phase lives

| Phase | Module | What it decides |
|---|---|---|
| 1 — Intent and goal routing | `src/clinical/intent.py` | Which of the 21 goals this message is, who it is about, and how much detail is wanted |
| 2 — Open problem representation | `src/clinical/problems.py` | The set of distinct problems, their type, priority and status |
| 3 — Adaptive consultation controller | `src/clinical/turnplan.py` | What is already known, what is still missing, whether to ask or answer, and which questions |
| 4 — Layered safety | `src/clinical/validator.py` | Whether a drafted answer may be sent, against 15 named checks |
| 5 — Evidence orchestration | `src/clinical/evidence.py` | Which evidence answers *this* question, in which lane, and where the lanes disagree |
| 6 — Universal response behaviour | `src/clinical/modes.py` | Which of the 6 response shapes to write in |
| 7 — Simulation and evaluation | `tests/evaluate_persona.py` | Whether any of the above is actually working |
| 8 — Controlled rollout | `src/clinical/rollout.py` | Who, if anyone, is affected — and how to turn it off |

Existing modules the new ones build on rather than replace:
`src/safety.py` (deterministic red flags), `src/clinical/triage.py` (the
urgency ladder), `src/clinical/interactions.py` (the reviewed herb/medicine
table), `src/clinical/evidence_class.py` (what a source *is*).

---

## For developers

### The shape of a turn

`src/consult/graph.py` still runs the consultation. `run_turn` is now a thin
wrapper around `_run_turn`; the wrapper exists so the PHASE-8 shadow hook sits
in one place instead of at each of the twenty-one return points inside.

```
run_turn ──> _run_turn (unchanged consultation) ──> ConsultResult
         └─> rollout.shadow_turn(...)  # observes, never modifies
```

`shadow_turn` returns `None` unless `CLINICAL_SHADOW_EVAL=1`, swallows its own
exceptions, and is wrapped again at the call site. It cannot change or break a
turn. That property is asserted in `tests/test_phase8_rollout.py` §1 and §6, and
it is the one thing to re-check after touching any of this.

### Running one message through the pipeline

```python
from src.clinical import rollout
record = rollout.evaluate("My eGFR is 50. What does this mean?")
print(rollout.clinician_review(record))
```

`evaluate` is pure — it reads no global state and writes nothing.

### Adding a question to the bank

`turnplan.QUESTION_BANK` is keyed by goal. Two rules, both from
`safety_engine.clinical_content_governance`:

1. **Do not invent clinical rules.** Only add a question whose field
   persona.txt itself names, or that an already-reviewed module supplies.
2. **A question must be able to change the answer.** If both possible replies
   lead to the same advice, it is burden, not information — see
   `adaptive_question_policy`.

Negative answers count as known. "No, no other symptoms" must mark the fact
known, or the engine asks forever; this is `_DENIED` in `turnplan.py`.

### Tests

Each phase has its own suite and they run standalone, not under pytest:

```
python tests/test_phase1_intent.py          # 64
python tests/test_phase2_problems.py        # 52
python tests/test_phase3_turnplan.py        # 109
python tests/test_phase4_6_validator_modes.py  # 79
python tests/test_phase5_evidence.py        # 53
python tests/test_phase8_rollout.py         # 43
python tests/evaluate_persona.py            # the acceptance measurement
python tests/test_e2e_conversations.py      # live model, whole conversations
```

`test_e2e_conversations.py` and several older suites call the real model. A
provider outage shows up as `kind=error`; those are reported as **blocked**,
never as passes.

---

## For clinical reviewers

### What the system decides on its own, and what it does not

**Deterministic, not the model's choice:** whether a message contains a red
flag (`safety.py`), the triage colour (`triage.py`), whether a herb clashes
with a medicine the person is taking (`interactions.py`), which questions may
be asked, and which response shape is used. The model writes prose inside a
decision that has already been made.

**The model's judgement:** the wording, and the clinical explanation within the
material retrieved for it.

### The six response modes

`direct_education`, `adaptive_question`, `working_assessment`,
`report_explanation`, `urgent_escalation`, `evidence_comparison`. The structure
of each is copied verbatim from persona.txt and is in `modes.STRUCTURE`.

### Evidence is ranked by the question, not by one hierarchy

This is the change most worth a reviewer's attention. Asked *what Ayurveda
traditionally says* about a herb, an authenticated classical source ranks
first. Asked *whether it works*, the same classical source ranks below a trial.
Both orderings come from `evidence_system.evidence_question_types`.

Lanes are kept apart (`modern_medicine`, `ayurveda`,
`nutrition_and_lifestyle`, `psychological_and_behavioral`,
`physical_rehabilitation_and_yoga`) and disagreement between them is
**reported, never averaged** — `cross_lane_rules` rule 3.

A classical text is dated `timeless`, not `outdated`. Calling the Caraka
Samhita stale would be a category error.

### The 15 response checks

`validator.CHECK_IDS`. The validator **reports and blocks; it never rewrites.**
A regex quietly deleting part of a health answer is worse than the thing it was
preventing, and this codebase has learned that twice. On failure the turn is
regenerated, or falls back to `validator.conservative_fallback`.

### Reviewing shadow output

```python
print(rollout.clinician_review(record))
```

renders one turn as goal, subject, problems, the decision, the questions it
*would* have asked, the evidence lanes, and the validator verdict. This is the
same data the rollout decision is made from — deliberately, so that what is
signed off is what is measured.

### What is NOT measured automatically

`evaluate_persona.py` prints these as an explicit gap rather than inventing a
number: clinician agreement with urgency, clinician agreement with
missing-information selection, appropriateness of the working assessment,
comprehension and perceived relevance, and use of current guidance. These need
reviewers or real users.

---

## Rollout (PHASE-8)

| Variable | Default | Effect |
|---|---|---|
| `PHASE1_INTENT_ROUTER` … `PHASE6_RESPONSE_MODES` | `0` | Each phase's effect on what the user sees |
| `CLINICAL_SHADOW_EVAL` | `0` | Run the new pipeline on real traffic and log what it *would* have done |
| `CLINICAL_COHORT_PERCENT` | `0` | Which share of users a live phase may affect |
| `CLINICAL_PIPELINE_DISABLED` | `0` | Rollback: beats every flag above |

Two safeguards worth knowing:

- **A flag on with the cohort at 0 still means nobody.** Turning a phase on
  must never silently mean "everybody".
- **Cohort membership is stable per user**, so a person does not flicker
  between behaviours mid-conversation.

### Suggested order

1. `CLINICAL_SHADOW_EVAL=1` alone. Read `clinical_shadow_turn` records; nothing
   user-facing changes.
2. Review a sample with `clinician_review`.
3. Enable one phase with `CLINICAL_COHORT_PERCENT` small.
4. Widen only against the PHASE-7 measurements.

Rollback at any point: `CLINICAL_PIPELINE_DISABLED=1`, restart.
