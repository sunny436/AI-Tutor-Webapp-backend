"""
Safety layer. Deterministic — no server, no API key, no model.

    python tests/test_safety.py

Why these are unit tests and not live ones: the safety layer must behave the same
on the day the LLM is rate-limited, wrong, or unreachable. Anything that depends
on a model answering correctly is not a safety guarantee.

The negatives carry as much weight as the positives here. A red-flag list that
fires on "sir dard" would refuse every headache question, and a version of that
bug is already recorded in `safety.py`: a bare "pregnant" used to escalate, which
silently killed every PCOS, fertility and prenatal-yoga consultation.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src import safety  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


# --- emergencies MUST escalate ---------------------------------------------
EMERGENCIES = [
    "I have severe chest pain",
    "I can't breathe properly",
    "difficulty breathing since morning",
    "my father had a stroke",
    "there is severe bleeding",
    "I am vomiting blood",
    "he had a seizure",
    "loss of consciousness",
    "I am having suicidal thoughts",
    "possible overdose",
]
for text in EMERGENCIES:
    check(f"emergency detected: {text!r}", safety.is_emergency(text))


# --- ordinary wellness complaints MUST NOT escalate -------------------------
# These are the whole product. One false positive here refuses a real user.
NOT_EMERGENCIES = [
    "mujhe acidity hai",
    "pet mein gas ho rahi hai",
    "raat ko neend nahi aati",
    "khane ke baad bloating hoti hai",
    "I have mild headache sometimes",
    "sir dard rehta hai",
    "baal jhad rahe hain",
    "I want a diet chart for weight loss",
    "मुझे खाना खाने के बाद गैस होती है",
    # Documented regression: a bare mention of pregnancy must not escalate,
    # or every PCOS / fertility / prenatal-yoga question gets refused.
    "I am pregnant and want yoga advice",
    "pregnancy me kya khana chahiye",
]
for text in NOT_EMERGENCIES:
    check(f"not an emergency: {text!r}", not safety.is_emergency(text))


# --- genuine pregnancy warning signs SHOULD escalate ------------------------
for text in ["bleeding while pregnant", "my water broke", "labour pain started"]:
    check(f"pregnancy red flag: {text!r}", safety.is_emergency(text))


# --- diagnosed serious conditions: different path, not an emergency ---------
SERIOUS = [
    "I am on chemotherapy",
    "mujhe cancer hai",
    "he is on dialysis",
    "mujhe tv hai",
    "diagnosed with hepatitis",
    "I am HIV positive",
]
for text in SERIOUS:
    check(f"serious condition detected: {text!r}", safety.is_serious_condition(text))

for text in ["mujhe acidity hai", "neend nahi aati", "I feel bloated"]:
    check(
        f"ordinary complaint is not a serious condition: {text!r}",
        not safety.is_serious_condition(text),
    )


# --- scan() across fragments ------------------------------------------------
# The card intake means a red flag can arrive in a chip the user tapped while the
# typed problem looks harmless. scan() is what covers that.
check(
    "scan finds a red flag in a selected option, not the typed problem",
    safety.scan("I have acidity", "After meals", "Blood in stool"),
)
check(
    "scan stays quiet when every fragment is ordinary",
    not safety.scan("I have acidity", "After meals", "3 days"),
)
check("scan tolerates empty fragments", not safety.scan("", None or "", "   "))


# --- the messages themselves ------------------------------------------------
check(
    "escalation message tells the user to get medical help",
    "medical help" in safety.ESCALATION_MESSAGE.lower(),
)
check(
    "escalation message withholds wellness advice",
    "not giving wellness advice" in safety.ESCALATION_MESSAGE.lower(),
)
check(
    "serious-condition message does not tell them to stop treatment",
    "band ya kam mat" in safety.SERIOUS_CONDITION_MESSAGE,
)
check(
    "serious-condition message says Ayurveda is not a replacement",
    "jagah nahi le sakta" in safety.SERIOUS_CONDITION_MESSAGE,
)


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== safety: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, _ in results:
        if not ok:
            print(f"  - {name}")
sys.exit(0 if passed == len(results) else 1)
