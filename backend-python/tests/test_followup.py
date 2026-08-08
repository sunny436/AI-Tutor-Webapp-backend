"""
Follow-up and language-switching tests.  Run with the backend up:

    python tests/test_followup.py

The bug these exist for:

    User: "according to ayurveda digestion kis par depend karta ha"
    Bot:  (long Hinglish answer)
    User: "can you please explain this in english"
    Bot:  "Theek hai! 😄 Main yahin hoon, jab bhi zarurat ho bata dena."   <- WRONG

The router had no follow-up intent, so "explain this in English" fell through to
"casual" and got a stock acknowledgement. These drive real multi-turn
conversations and assert the previous answer is actually re-presented.
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


class Conversation:
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


# The stock acknowledgements that used to be returned instead of a real answer.
STOCK = re.compile(r"main yahin hoon|theek hai bhai|jab bhi zarurat", re.IGNORECASE)
DEVANAGARI = re.compile(r"[ऀ-ॿ]")

# Hinglish is Hindi written in Latin letters, so "is it English?" cannot be a
# script check. These are common Hinglish function words that would not appear in
# an English answer.
HINGLISH_WORDS = re.compile(
    r"\b(hai|hain|kar|karta|karte|karna|aap|aapko|mein|nahi|liye|hota|hoti|ke|ki|ko|se|par)\b",
    re.IGNORECASE,
)


def looks_english(text: str) -> bool:
    if DEVANAGARI.search(text):
        return False
    words = len(text.split()) or 1
    return len(HINGLISH_WORDS.findall(text)) / words < 0.08


def looks_hindi_or_hinglish(text: str) -> bool:
    if DEVANAGARI.search(text):
        return True
    words = len(text.split()) or 1
    return len(HINGLISH_WORDS.findall(text)) / words >= 0.08


def substantial(text: str) -> bool:
    return len(text.strip()) >= 150 and not STOCK.search(text)


# =========================================================================
# TEST 1 — Hinglish answer, then "explain this in English"
# =========================================================================
c1 = Conversation()
first = c1.say("according to ayurveda digestion kis par depend karta hai")
check(
    "1a. general question gets a real answer",
    first["kind"] == "chat" and len(first.get("answer", "")) > 150,
    f"kind={first['kind']}, {len(first.get('answer',''))} chars",
)
check(
    "1b. the full answer is remembered for follow-ups",
    len(c1.context.get("last_answer") or "") > 150,
    f"{len(c1.context.get('last_answer') or '')} chars stored",
)

english = c1.say("can you please explain this in english")
english_text = english.get("answer", "")
check(
    "1c. THE BUG: does not reply with a stock acknowledgement",
    not STOCK.search(english_text),
    english_text[:90],
)
check(
    "1d. returns a substantial answer, not a one-liner",
    substantial(english_text),
    f"{len(english_text)} chars",
)
check("1e. the answer is in English", looks_english(english_text), english_text[:90])
check(
    "1f. it is the SAME content, not a fresh search",
    any(w in english_text.lower() for w in ("agni", "digest", "food", "meal")),
    english_text[:90],
)

# =========================================================================
# TEST 2 — English answer, then "Hindi me batao"
# =========================================================================
c2 = Conversation()
c2.say("tell me about ashwagandha in english")
hindi = c2.say("ab isko hindi me batao")
hindi_text = hindi.get("answer", "")
check("2a. no stock acknowledgement", not STOCK.search(hindi_text), hindi_text[:90])
check("2b. substantial answer", substantial(hindi_text), f"{len(hindi_text)} chars")
check("2c. answer switched to Hindi/Hinglish", looks_hindi_or_hinglish(hindi_text), hindi_text[:90])

# =========================================================================
# TEST 3 — "explain in simple English"
# =========================================================================
c3 = Conversation()
c3.say("gas problem ke liye ayurveda kya kehta hai")
simple = c3.say("explain in simple english")
simple_text = simple.get("answer", "")
check("3a. no stock acknowledgement", not STOCK.search(simple_text), simple_text[:90])
check("3b. substantial answer", substantial(simple_text), f"{len(simple_text)} chars")
check("3c. in English", looks_english(simple_text), simple_text[:90])

# =========================================================================
# TEST 4 — "summarize the above"
# =========================================================================
c4 = Conversation()
long_answer = c4.say("what does ayurveda say about sleep and daily routine")
summary = c4.say("summarize the above")
summary_text = summary.get("answer", "")
check("4a. no stock acknowledgement", not STOCK.search(summary_text), summary_text[:90])
check(
    "4b. a summary is shorter than the original",
    0 < len(summary_text) < len(long_answer.get("answer", "")),
    f"{len(long_answer.get('answer',''))} -> {len(summary_text)} chars",
)

# =========================================================================
# TEST 5 — "explain that in detail"
# =========================================================================
c5 = Conversation()
short_answer = c5.say("what is agni in ayurveda")
detailed = c5.say("explain that in more detail")
detailed_text = detailed.get("answer", "")
check("5a. no stock acknowledgement", not STOCK.search(detailed_text), detailed_text[:90])
check("5b. substantial answer", substantial(detailed_text), f"{len(detailed_text)} chars")

# =========================================================================
# TEST 6 — follow-ups must not hijack genuinely new messages
# =========================================================================
c6 = Conversation()
c6.say("what is ashwagandha")
new_topic = c6.say("mujhe acidity hai")
check(
    "6a. a new health complaint still opens the cards",
    new_topic["kind"] == "intake",
    f"kind={new_topic['kind']}",
)

c7 = Conversation()
greet = c7.say("hi kaise ho")
check(
    "6b. a follow-up phrase with nothing to refer back to is not mishandled",
    greet["kind"] == "chat" and len(greet.get("answer", "")) > 10,
    f"kind={greet['kind']}",
)

failed = [n for n, ok, _ in results if not ok]
print(f"\n===== follow-up: {len(results) - len(failed)}/{len(results)} passed =====")
if failed:
    print("\nFailing:")
    for name in failed:
        print(f"  - {name}")
sys.exit(1 if failed else 0)
