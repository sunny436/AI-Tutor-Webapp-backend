"""
Conversation-engine tests.  Run with the backend up:

    python tests/test_conversation.py

The bug these exist for:

    User: "hii kya ha"                            -> greeting
    User: "mujhe madad nahi chahiye, bas text kiya tha"
    Bot:  "Aapko kis tarah ki madad chahiye?"     <- WRONG

The assistant had no memory, so every message looked like the first one. These
tests drive multi-turn conversations through the real API and assert the
assistant follows on rather than restarting.
"""

import json
import re
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
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read())


def pick_safe(question: dict) -> str | None:
    """First option that is NOT a red flag.

    Blindly taking options[0] made these tests flaky: the planner legitimately
    generates entries like "Blood in stool" marked `red_flag`, selecting one
    escalates the consultation (correctly), and the rest of the flow never runs.
    A test simulating an ordinary user must not tick the emergency box.
    """
    for option in question.get("options", []):
        if not option.get("red_flag"):
            return option["id"]
    return None


def answer_all(questions: list[dict]) -> dict:
    """Answer every tappable question the way an ordinary user would."""
    answers: dict = {}
    for question in questions:
        if question["type"] == "text":
            continue
        choice = pick_safe(question)
        if choice:
            answers[question["id"]] = {"options": [choice]}
    return answers


class Conversation:
    """A single chat session — carries context forward exactly like the browser."""

    def __init__(self) -> None:
        self.context: dict | None = None

    def say(self, text: str) -> dict:
        consulting = (self.context or {}).get("phase") in {"collecting", "choosing"}
        payload = (
            {"context": self.context, "freeText": text}
            if consulting
            else {"problem": text, "context": self.context}
        )
        result = post(payload)
        self.context = result["context"]
        return result

    def tap(self, answers: dict) -> dict:
        result = post({"context": self.context, "answers": answers})
        self.context = result["context"]
        return result


ASKS_FOR_HELP = re.compile(
    r"(kya|kis|kaun|what).{0,30}(madad|help|samasya|problem|concern|troubl)",
    re.IGNORECASE,
)


# =========================================================================
# 1. THE REPORTED BUG — refusal after a greeting
# =========================================================================
chat = Conversation()
greeting = chat.say("hii kya ha")
check(
    "greeting gets a conversational reply, no cards",
    greeting["kind"] == "chat" and greeting.get("intake") is None,
    f"kind={greeting['kind']}",
)
check(
    "greeting sets the greeted flag",
    chat.context.get("greeted") is True,
    f"greeted={chat.context.get('greeted')}, phase={chat.context.get('phase')}",
)

refusal = chat.say("mujhe madad nahi chahiye, bas text kiya tha")
refusal_reply = refusal.get("answer", "")
check(
    "refusal is answered conversationally",
    refusal["kind"] == "chat" and len(refusal_reply) > 5,
    refusal_reply[:100],
)
check(
    "THE BUG: does not ask 'what help do you need' after a refusal",
    not ASKS_FOR_HELP.search(refusal_reply),
    refusal_reply[:120],
)
check(
    "does not repeat the greeting word-for-word",
    refusal_reply.strip().lower() != greeting["answer"].strip().lower(),
)
check(
    "conversation memory is carried between turns",
    len(chat.context.get("chat_history") or []) >= 4,
    f"{len(chat.context.get('chat_history') or [])} remembered turns",
)

# =========================================================================
# 2. CASUAL CHAT must not trigger the consultation
# =========================================================================
for message in ["bas aise hi", "kuch nahi", "timepass", "kya kar rahe ho"]:
    casual = Conversation()
    casual.say("hi")
    reply = casual.say(message)
    check(
        f"casual '{message}' stays conversational",
        reply["kind"] == "chat" and reply.get("intake") is None,
        (reply.get("answer") or "")[:70],
    )

# =========================================================================
# 3. THANKS / GOODBYE
# =========================================================================
polite = Conversation()
polite.say("hello")
thanks = polite.say("thank you bhai")
check("thanks handled without cards", thanks["kind"] == "chat", (thanks.get("answer") or "")[:70])
bye = polite.say("ok bye, good night")
check("goodbye handled without cards", bye["kind"] == "chat", (bye.get("answer") or "")[:70])
check(
    "goodbye does not beg for a consultation",
    not ASKS_FOR_HELP.search(bye.get("answer", "")),
    (bye.get("answer") or "")[:100],
)

# =========================================================================
# 4. HEALTH still starts the consultation, even mid-conversation
# =========================================================================
health_chat = Conversation()
health_chat.say("hi")
health_chat.say("bas aise hi")
started = health_chat.say("waise mujhe acidity hai")
check(
    # How many questions the planner asks is the model's call (the prompt asks
    # for 4-6, the repair layer caps at 6). Assert a usable form was produced,
    # not an exact count that varies with the model in use.
    "a health concern after small talk starts the cards",
    started["kind"] == "intake" and len(started.get("intake", {}).get("questions", [])) >= 2,
    f"kind={started['kind']}, {len(started.get('intake',{}).get('questions',[]))} questions, "
    f"phase={health_chat.context.get('phase')}",
)
check(
    "starting a consultation keeps the earlier conversation",
    health_chat.context.get("greeted") is True
    and len(health_chat.context.get("chat_history") or []) > 0,
    f"greeted={health_chat.context.get('greeted')}",
)

for message, label in [
    ("mujhe acidity hai", "acidity"),
    ("pet me gas hai", "gas"),
    ("sir dard ho raha hai", "headache"),
    ("sleep problem hai", "sleep"),
]:
    convo = Conversation()
    result = convo.say(message)
    check(
        f"health: '{message}' starts consultation",
        result["kind"] == "intake",
        f"condition='{result.get('condition')}'",
    )

# =========================================================================
# 5. SELECTED OPTIONS ARE REMEMBERED through to the plan
# =========================================================================
flow = Conversation()
cards = flow.say("mujhe acidity hai")
questions = cards["intake"]["questions"]
picked = answer_all(questions)
picked_labels = [
    next(o["label"] for o in q["options"] if o["id"] == picked[q["id"]]["options"][0])
    for q in questions
    if q["id"] in picked
]
choice = flow.tap(picked)
check(
    "after answering, it asks what the user wants",
    choice["kind"] == "intake" and flow.context["phase"] == "choosing",
    f"phase={flow.context['phase']}",
)
check(
    "selected options are remembered in the context",
    len(flow.context.get("answers") or {}) == len(picked),
    f"{len(flow.context.get('answers') or {})}/{len(picked)} kept",
)

final = flow.tap({"_sections": {"options": ["complete"]}})
headings = re.findall(r"(?m)^\s*\*\*(.+?)\*\*\s*$", final.get("answer", ""))
check(
    "the final plan is generated",
    final["kind"] == "answer" and len(headings) >= 5,
    f"{len(headings)} sections, phase={flow.context['phase']}",
)
check(
    "the plan reflects what was actually selected",
    any(label.split()[0].lower() in final["answer"].lower() for label in picked_labels[:3]),
    f"picked: {picked_labels[:3]}",
)

# =========================================================================
# 6. EDGE CASES
# =========================================================================
edge = Conversation()
edge.say("hi")
empty = edge.say("")
check("empty message does not crash or start a consultation", empty["kind"] == "chat")

emoji = Conversation()
emoji.say("hello")
emoji_reply = emoji.say("😀😀")
check("emoji-only message stays conversational", emoji_reply["kind"] == "chat",
      (emoji_reply.get("answer") or "")[:60])

repeat = Conversation()
first = repeat.say("hi")
second = repeat.say("hi")
check(
    "REGRESSION: a second greeting is not the same welcome message",
    second.get("answer", "").strip().lower() != first.get("answer", "").strip().lower(),
    f"1st: {first.get('answer','')[:45]!r} | 2nd: {second.get('answer','')[:45]!r}",
)

rude = Conversation()
rude_reply = rude.say("you are useless stupid bot")
check("abusive text is handled without crashing", rude_reply["kind"] in {"chat", "intake"},
      f"kind={rude_reply['kind']}")

unrelated = Conversation()
off = unrelated.say("who won the world cup 2024?")
check("unrelated question is declined politely, no cards",
      off["kind"] == "chat" and off.get("intake") is None,
      (off.get("answer") or "")[:70])

# =========================================================================
# 7. SAFETY
# =========================================================================
emergency = Conversation()
danger = emergency.say("I have severe chest pain and cannot breathe")
check(
    "emergency wording escalates instead of advising",
    danger["kind"] == "escalation",
    f"kind={danger['kind']}",
)
check(
    "escalation never names a medicine",
    not re.search(r"\b(tablet|mg\b|syrup|capsule|dose)\b", danger.get("answer", ""), re.I),
)

failed = [n for n, ok, _ in results if not ok]
print(f"\n===== conversation: {len(results) - len(failed)}/{len(results)} passed =====")
if failed:
    print("\nFailing:")
    for name in failed:
        print(f"  - {name}")
sys.exit(1 if failed else 0)
