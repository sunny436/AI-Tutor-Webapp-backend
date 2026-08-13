"""
Language consistency and conversation continuity, against the live `/consult`.

    python tests/test_continuity.py     (needs the backend on :4000)

The six scenarios below are the reported failures, in the order they were
reported. What they have in common is that the SECOND message carries almost no
information of its own — "tell me more" names no topic and no language — so
everything depends on state the assistant is supposed to be holding:

  language   sticky on the context, set once and changed only when asked
  topic      `last_answer`, which the follow-up branch rewrites instead of
             re-answering
  retrieval  skipped entirely for follow-ups; searching the corpus again for
             "continue" would answer a question nobody asked
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402  (needs the sys.path line above)

BASE = "http://localhost:4000"
results: list[tuple[str, bool, str]] = []

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
HINGLISH = re.compile(
    r"\b(hai|hain|kar|karta|karna|aap|aapko|mein|nahi|liye|hota|ke|ki|ko|se|par|"
    r"kare|karein|rakhein|khaayein|piyein|wala|zyada)\b",
    re.IGNORECASE,
)
STOCK = re.compile(r"main yahin hoon|theek hai bhai|jab bhi zarurat", re.IGNORECASE)


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


def post(payload: dict) -> dict:
    request = urllib.request.Request(
        f"{BASE}/consult",
        data=json.dumps(payload).encode("utf-8"),
        # Server-to-server credential — /consult refuses anonymous callers so a
        # published backend cannot have its LLM quota spent by strangers.
        headers={"Content-Type": "application/json", "x-service-key": config.SERVICE_KEY},
    )
    with urllib.request.urlopen(request, timeout=200) as response:
        return json.loads(response.read())


class Chat:
    def __init__(self) -> None:
        self.context: dict | None = None

    def say(self, text: str) -> str:
        consulting = (self.context or {}).get("phase") in {"collecting", "choosing"}
        payload = (
            {"context": self.context, "freeText": text}
            if consulting
            else {"problem": text, "context": self.context}
        )
        result = post(payload)
        self.context = result["context"]
        return result.get("answer") or result.get("message") or ""

    @property
    def language(self) -> str:
        return (self.context or {}).get("language", "")


def devanagari_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return len(DEVANAGARI.findall(text)) / len(letters) if letters else 0.0


def is_english(text: str) -> bool:
    if DEVANAGARI.search(text):
        return False
    words = len(text.split()) or 1
    return len(HINGLISH.findall(text)) / words < 0.06


def is_hinglish(text: str) -> bool:
    if devanagari_share(text) > 0.15:
        return False
    words = len(text.split()) or 1
    return len(HINGLISH.findall(text)) / words >= 0.06


def is_devanagari(text: str) -> bool:
    return devanagari_share(text) > 0.5


def substantial(text: str) -> bool:
    return len(text.strip()) >= 120 and not STOCK.search(text)


# 1 — English is kept across a follow-up that carries no language signal
c = Chat()
first = c.say("Explain digestion in English")
check("1a. English question answered in English", is_english(first), first[:60])
more = c.say("Tell me more")
check("1b. 'Tell me more' stays in English", is_english(more), more[:60])
check("1c. and is a real continuation", substantial(more), f"{len(more)} chars")

# 2 — an explicit request overrides the settled language
c = Chat()
c.say("What is PCOS?")
hindi = c.say("Explain this in Hindi")
check("2a. 'in Hindi' switches to Devanagari", is_devanagari(hindi), hindi[:60])
check("2b. language remembered on the context", c.language == "devanagari", c.language)

# 3 — the reverse switch, from a Hinglish thread
c = Chat()
c.say("gas problem ho rahi hai")
english = c.say("explain this in English")
check("3a. 'in English' switches to English", is_english(english), english[:60])
after = c.say("tell me more")
check("3b. and the switch STICKS on the next turn", is_english(after), after[:60])

# 4 — "give examples" continues the topic instead of starting one
c = Chat()
c.say("what causes acidity")
examples = c.say("give examples")
check(
    "4a. 'give examples' stays on acidity",
    any(w in examples.lower() for w in ("acid", "pitta", "chai", "spicy", "mirchi", "khana")),
    examples[:60],
)
check("4b. and is substantial", substantial(examples), f"{len(examples)} chars")

# 5 — summarise
c = Chat()
long_answer = c.say("what does ayurveda say about sleep and daily routine")
summary = c.say("Summarize the above")
check(
    "5a. summary is shorter than the original",
    0 < len(summary) < len(long_answer),
    f"{len(long_answer)} -> {len(summary)}",
)

# 6 — bare "continue"
c = Chat()
c.say("what is agni in ayurveda")
cont = c.say("Continue")
check("6a. 'Continue' is not a stock reply", not STOCK.search(cont), cont[:60])
check(
    "6b. and stays on the topic",
    any(w in cont.lower() for w in ("agni", "digest", "pachan", "fire")),
    cont[:60],
)

failed = [n for n, ok, _ in results if not ok]
print(f"\n===== continuity: {len(results) - len(failed)}/{len(results)} passed =====")
if failed:
    print("\nFailing:")
    for name in failed:
        print(f"  - {name}")
sys.exit(1 if failed else 0)
