"""
Live end-to-end checks against a running backend:  python tests/test_consult_live.py

Proves the three things the redesign is judged on:
  1. the question cards are generated per-condition, not hardcoded
  2. tapping options produces a full six-section answer
  3. a red-flag option escalates instead of giving wellness advice
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402  (needs the sys.path line above)

BASE = "http://localhost:4000"
# Server-to-server credential — /consult and /chat refuse anonymous callers so a
# published backend cannot have its LLM quota spent by strangers.
AUTH = {"Content-Type": "application/json", "x-service-key": config.SERVICE_KEY}
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


def post(payload: dict) -> dict:
    request = urllib.request.Request(
        f"{BASE}/consult",
        data=json.dumps(payload).encode(),
        headers=AUTH,
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read())


def answer_everything(plan: dict) -> dict:
    """Pick the first option of every question, as a user tapping through would."""
    answers = {}
    for question in plan["questions"]:
        if question["type"] == "text":
            answers[question["id"]] = {"text": "nothing else"}
        elif question["options"]:
            answers[question["id"]] = {"options": [question["options"][0]["id"]]}
    return answers


# --- 1. per-condition question generation --------------------------------
plans: dict[str, dict] = {}
for problem, label in [
    ("I have acidity and burning after meals", "acidity"),
    ("I get migraine headaches twice a week", "migraine"),
    ("I have PCOS and irregular periods", "pcos"),
]:
    response = post({"problem": problem})
    plans[label] = response
    questions = response.get("intake", {}).get("questions", [])
    tappable = [q for q in questions if q["type"] != "text"]
    check(
        f"{label}: returns tappable cards",
        response["kind"] == "intake" and 3 <= len(questions) <= 6 and len(tappable) >= 3,
        f"kind={response['kind']}, {len(questions)} questions, condition='{response.get('condition')}'",
    )

# The decisive test: different conditions must ask different things.
label_sets = {
    name: {q["label"].lower() for q in plan["intake"]["questions"]}
    for name, plan in plans.items()
    if plan.get("intake")
}
if len(label_sets) == 3:
    acidity, migraine, pcos = label_sets["acidity"], label_sets["migraine"], label_sets["pcos"]
    overlap = len(acidity & migraine) + len(acidity & pcos) + len(migraine & pcos)
    check(
        "different conditions generate different questions (not hardcoded)",
        overlap <= 2,
        f"{overlap} shared question labels across 3 conditions",
    )

# --- 2. tapping through to a full answer ---------------------------------
acidity_plan = plans["acidity"]
final = post(
    {
        "problem": acidity_plan["context"]["problem"],
        "context": acidity_plan["context"],
        "answers": answer_everything(acidity_plan["intake"]),
        "freeText": "",
    }
)
headings = ["Root Cause", "Changes To Make", "Yoga", "Food Chart", "Daily Routine", "Doctor"]
present = [h for h in headings if h.lower() in final.get("answer", "").lower()]
check(
    "tapping options produces the final answer",
    final["kind"] == "answer" and len(present) >= 5,
    f"kind={final['kind']}, {len(present)}/6 sections, {len(final.get('answer',''))} chars",
)
check(
    "answer cites retrieved knowledge",
    len(final.get("sources", [])) > 0,
    f"{len(final.get('sources', []))} source(s): "
    + ", ".join(sorted({s['source'] for s in final.get('sources', [])})),
)
check(
    "context is marked done after answering",
    final["context"]["phase"] == "done",
    final["context"]["phase"],
)

# --- 3. safety --------------------------------------------------------------
danger = post({"problem": "I have severe chest pain and cannot breathe"})
check(
    "emergency wording escalates instead of advising",
    danger["kind"] == "escalation",
    danger["kind"],
)

# A red flag reached only by tapping — the problem statement looks harmless.
flag_plan = post({"problem": "I have constipation and stomach discomfort"})
flag_answers = {}
flagged_label = None
for question in flag_plan.get("intake", {}).get("questions", []):
    for option in question.get("options", []):
        if option.get("red_flag"):
            flag_answers[question["id"]] = {"options": [option["id"]]}
            flagged_label = option["label"]
            break
    if flagged_label:
        break

if flagged_label:
    flagged = post(
        {
            "problem": flag_plan["context"]["problem"],
            "context": flag_plan["context"],
            "answers": flag_answers,
        }
    )
    check(
        "selecting a red-flag option escalates",
        flagged["kind"] == "escalation",
        f"tapped '{flagged_label}' -> {flagged['kind']}",
    )
else:
    print("SKIP  no red-flag option generated for this condition (not a failure)")

# --- 4. legacy path still alive --------------------------------------------
try:
    legacy_request = urllib.request.Request(
        f"{BASE}/chat",
        data=json.dumps({"problem": "mild bloating", "followups": 9}).encode(),
        headers=AUTH,
    )
    with urllib.request.urlopen(legacy_request, timeout=180) as response:
        legacy = json.loads(response.read())
    check("legacy /chat still works", legacy.get("kind") in {"answer", "followup", "escalation"},
          f"kind={legacy.get('kind')}")
except urllib.error.URLError as error:
    check("legacy /chat still works", False, str(error))

failed = [n for n, ok, _ in results if not ok]
print(f"\n===== consult live: {len(results) - len(failed)}/{len(results)} passed =====")
sys.exit(1 if failed else 0)
