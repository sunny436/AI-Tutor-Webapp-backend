"""
Repair-layer checks — run with:  python tests/test_repair.py

The intake planner is the one place where a model slip becomes a blank screen, so
these exercise the shapes Llama actually produces when it goes wrong: prose around
the JSON, code fences, trailing commas, duplicate ids, runaway question counts,
and choice questions with nothing to choose from.

No pytest dependency; plain asserts so it runs anywhere the backend runs.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.consult.fallback import baseline_plan
from src.consult.repair import parse_plan, repair_plan
from src.consult.schema import MAX_QUESTIONS

checks: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    checks.append((name, condition, detail))
    print(f"{'PASS' if condition else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


# 1. Prose + code fence + trailing comma + a repeated option.
messy = (
    "Sure! Here's the form:\n```json\n"
    '{"condition":"Acidity","questions":[{"id":"a","label":"What did you eat?",'
    '"type":"multi","options":[{"label":"Oily"},{"label":"Spicy"},{"label":"oily"}]},]}'
    "\n```\nHope that helps!"
)
plan = parse_plan(messy)
check(
    "fenced JSON with prose, trailing comma and duplicate option",
    len(plan.questions) == 1 and len(plan.questions[0].options) == 2,
    f"{len(plan.questions)} question(s), {len(plan.questions[0].options) if plan.questions else 0} option(s)",
)

# 2. Runaway question count, every id identical.
plan = repair_plan(
    {"questions": [
        {"id": "x", "label": f"Question {i}", "options": [{"label": "A"}, {"label": "B"}]}
        for i in range(20)
    ]}
)
check(
    "20 questions with colliding ids are capped and made unique",
    len(plan.questions) == MAX_QUESTIONS and len({q.id for q in plan.questions}) == MAX_QUESTIONS,
    f"kept {len(plan.questions)}, {len({q.id for q in plan.questions})} unique ids",
)

# 3. A choice question with one option cannot be rendered as chips.
plan = repair_plan({"questions": [{"label": "Only one", "type": "single", "options": [{"label": "A"}]}]})
check(
    "single-option choice degrades to a text field",
    plan.questions[0].type == "text",
    plan.questions[0].type,
)

# 4. The planner must not regress towards free text.
plan = repair_plan({"questions": [{"label": f"T{i}", "type": "text"} for i in range(3)]})
check("at most one text question survives", len(plan.questions) == 1, f"{len(plan.questions)} kept")

# 5. Unknown enum values fall back instead of raising.
plan = repair_plan(
    {"questions": [{"label": "Q", "type": "dropdown", "display": "wheel",
                    "options": [{"label": "A"}, {"label": "B"}]}]}
)
check(
    "unknown type/display coerced to valid values",
    plan.questions[0].type in {"single", "multi"} and plan.questions[0].display == "chips",
    f"{plan.questions[0].type}/{plan.questions[0].display}",
)

# 6. Refusals and total garbage must not raise.
check("non-JSON reply yields no questions rather than an exception",
      len(parse_plan("I'm sorry, I can't help with that.").questions) == 0)
check("empty reply yields no questions", len(parse_plan("").questions) == 0)

# 7. red_flag survives repair — escalation depends on it.
plan = repair_plan(
    {"questions": [{"label": "Symptoms", "type": "multi", "options": [
        {"label": "Bloating"}, {"label": "Blood in stool", "red_flag": True}]}]}
)
check(
    "red_flag markers are preserved",
    any(o.red_flag for o in plan.questions[0].options),
)

# 8. Options given as bare strings (a common model shortcut).
plan = repair_plan({"questions": [{"label": "Sleep", "options": ["Poor", "Average", "Good"]}]})
check(
    "bare string options are accepted",
    len(plan.questions) == 1 and len(plan.questions[0].options) == 3,
    f"{len(plan.questions[0].options) if plan.questions else 0} options",
)

# 9. The round-1 safety net must always be renderable.
fallback = baseline_plan()
check(
    "baseline fallback plan is renderable",
    len(fallback.questions) >= 4
    and all(q.type == "text" or len(q.options) >= 2 for q in fallback.questions),
    f"{len(fallback.questions)} questions",
)

failed = [name for name, ok, _ in checks if not ok]
print(f"\n===== repair: {len(checks) - len(failed)}/{len(checks)} passed =====")
sys.exit(1 if failed else 0)
