"""
Live check of the conversation router and the new choice step.
Run with the backend up:  python tests/test_router_live.py

The bug this covers: every message used to be treated as a health complaint, so
"hi kaise ho" answered with five symptom cards. Small talk, capability questions
and off-topic messages must now get a real reply — and every one of those replies
has to end by asking what's troubling the user, so the conversation still leads
into a consultation.
"""

import json
import sys
import urllib.request

BASE = "http://localhost:4000"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


def post(payload: dict) -> dict:
    request = urllib.request.Request(
        f"{BASE}/consult",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read())


ASKS_PROBLEM = ("problem", "trouble", "help", "pareshan", "concern", "bother", "kya")


def asks_what_is_wrong(text: str) -> bool:
    lowered = text.lower()
    return "?" in text and any(word in lowered for word in ASKS_PROBLEM)


# --- 1. small talk must not become a consultation --------------------------
for message, label in [
    ("hi kaise ho", "hinglish greeting"),
    ("hello", "english greeting"),
    ("what can you do?", "capability question"),
    ("who won the world cup?", "off-topic"),
]:
    response = post({"problem": message})
    reply = response.get("answer", "")
    check(
        f"{label}: replies conversationally, no cards",
        response["kind"] == "chat" and response.get("intake") is None and len(reply) > 10,
        f"kind={response['kind']} -> {reply[:90]!r}",
    )
    check(f"{label}: ends by asking what's wrong", asks_what_is_wrong(reply))

# Hinglish in -> Hinglish out is the one that proves it isn't a canned string.
hinglish = post({"problem": "hi kaise ho"})["answer"]
english = post({"problem": "hello there"})["answer"]
check(
    "replies differ per message (not one fixed response)",
    hinglish.strip() != english.strip(),
    f"{hinglish[:45]!r} vs {english[:45]!r}",
)

# --- 2. general questions get a direct answer, still no cards --------------
knowledge = post({"problem": "what is ashwagandha?"})
check(
    "general question answered directly without an intake form",
    knowledge["kind"] == "chat" and knowledge.get("intake") is None
    and len(knowledge.get("answer", "")) > 80,
    f"kind={knowledge['kind']}, {len(knowledge.get('answer',''))} chars",
)

# --- 3. a real complaint still starts the cards ----------------------------
consult = post({"problem": "I have acidity and burning after meals"})
check(
    "a health complaint starts the question cards",
    consult["kind"] == "intake" and len(consult["intake"]["questions"]) >= 3,
    f"condition='{consult.get('condition')}', {len(consult.get('intake',{}).get('questions',[]))} questions",
)

# --- 4. the new "anything else / what do you want" step --------------------
answers = {
    q["id"]: {"options": [q["options"][0]["id"]]}
    for q in consult["intake"]["questions"]
    if q["type"] != "text" and q["options"]
}
choice = post({"context": consult["context"], "answers": answers})
option_ids = [
    o["id"]
    for q in choice.get("intake", {}).get("questions", [])
    for o in q.get("options", [])
]
check(
    "after the questions, it asks what the user wants",
    choice["kind"] == "intake"
    and choice["context"]["phase"] == "choose"
    and "complete" in option_ids,
    f"phase={choice['context']['phase']}, options={option_ids}",
)
check(
    "the choice step offers a free-text 'anything else' field",
    any(q["type"] == "text" for q in choice.get("intake", {}).get("questions", [])),
)

# --- 5. only the chosen section is generated -------------------------------
only_food = post(
    {
        "context": choice["context"],
        "answers": {"_sections": {"options": ["food"]}},
    }
)
answer = only_food.get("answer", "")
check(
    "choosing only Food chart returns just that section (plus the doctor note)",
    only_food["kind"] == "answer"
    and "Food Chart" in answer
    and "Daily Routine" not in answer
    and "Yoga" not in answer,
    f"{len(answer)} chars; has Food={('Food Chart' in answer)}, "
    f"Routine={('Daily Routine' in answer)}, Yoga={('Yoga' in answer)}",
)
check(
    "the doctor guidance is always included",
    "Doctor" in answer,
)

failed = [n for n, ok, _ in results if not ok]
print(f"\n===== router + choice: {len(results) - len(failed)}/{len(results)} passed =====")
sys.exit(1 if failed else 0)
