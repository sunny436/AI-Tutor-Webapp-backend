"""
Language, memory and grounding, against the live `/consult` endpoint.

    python tests/test_language.py     (needs the backend on :4000)

Covers what the other suites do not:

  test_retrieval    picks the right NOTE               (no LLM involved)
  test_followup     re-presents the previous ANSWER    (translation mechanics)
  test_conversation routes a message to the right KIND (greeting vs cards)
  THIS SUITE        the answer the user actually reads — is it in their
                    language, does it come from the note, and does the bot still
                    know what they said three turns ago?

Also pins four regressions that were fixed this session but guarded by nothing,
so they could return silently. Each is a real reported bug.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

# Running this as `python tests/test_language.py` puts `tests/` on sys.path, not
# the repo root, so the `from src.consult.router import ...` block at the bottom
# died with ModuleNotFoundError — meaning that whole set of deterministic
# `requested_language` regression checks never actually executed. Same line every
# other suite here already carries (see tests/test_retrieval.py).
sys.path.append(str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402  (needs the sys.path line above)

BASE = "http://localhost:4000"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


def post(payload: dict) -> dict:
    # /consult refuses anonymous callers so a published backend cannot have its
    # LLM quota spent by strangers. The service key is the server-to-server
    # credential for exactly this: it admits the request without claiming to be
    # any particular user, so these tests still exercise the real HTTP path.
    request = urllib.request.Request(
        f"{BASE}/consult",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-service-key": config.SERVICE_KEY},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read())


class Chat:
    """A conversation that carries its context, exactly as the browser does."""

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

    def text(self, result: dict) -> str:
        return result.get("answer") or result.get("message") or ""


DEVANAGARI = re.compile(r"[ऀ-ॿ]")
# Hindi function words that would not appear in an English sentence.
HINGLISH_WORDS = re.compile(
    r"\b(hai|hain|kar|karta|karna|aap|aapko|mein|nahi|liye|hota|ke|ki|ko|se|par|"
    r"kare|karein|rakhein|khaayein|piyein)\b",
    re.IGNORECASE,
)
STOCK = re.compile(r"main yahin hoon|theek hai bhai|jab bhi zarurat", re.IGNORECASE)


def devanagari_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return len(DEVANAGARI.findall(text)) / len(letters)


def is_hinglish(text: str) -> bool:
    if devanagari_share(text) > 0.15:
        return False
    words = len(text.split()) or 1
    return len(HINGLISH_WORDS.findall(text)) / words >= 0.06


def is_english(text: str) -> bool:
    if DEVANAGARI.search(text):
        return False
    words = len(text.split()) or 1
    return len(HINGLISH_WORDS.findall(text)) / words < 0.06


def substantial(text: str) -> bool:
    return len(text.strip()) >= 150 and not STOCK.search(text)


# =========================================================================
# 1. Script mirroring — the answer comes back in the language asked
# =========================================================================
c = Chat()
hindi = c.text(c.say("अम्लपित्त के लिए क्या खाना चाहिए"))
check("1a. Devanagari question gets a substantial answer", substantial(hindi), f"{len(hindi)} chars")
check("1b. answered in Devanagari", devanagari_share(hindi) > 0.5, hindi[:70])

c = Chat()
hinglish = c.text(c.say("acidity ke liye kya khana chahiye"))
check("2a. Hinglish question gets a substantial answer", substantial(hinglish), f"{len(hinglish)} chars")
check("2b. answered in Hinglish, not Devanagari", is_hinglish(hinglish), hinglish[:70])

c = Chat()
english = c.text(c.say("what should I eat for acidity according to ayurveda"))
check("3a. English question gets a substantial answer", substantial(english), f"{len(english)} chars")
check("3b. answered in English", is_english(english), english[:70])

# =========================================================================
# 2. Grounding — the answer uses the note, and admits when there is none
# =========================================================================
c = Chat()
grounded = c.text(c.say("kabz ke liye kya khaye"))
# Foods named in constipation.md specifically. A model answering from its own
# recall reaches for generic "fibre and water"; one reading the note names these.
hits = [w for w in ("munakka", "anjeer", "papita", "ghee", "daliya", "alsi") if w in grounded.lower()]
check("4a. answer is grounded in the note", len(hits) >= 2, f"note terms found: {hits}")

c = Chat()
unknown = c.say("mujhe malaria ke baare mein batao")
unknown_text = c.text(unknown)
check(
    "4b. a topic with no note still gets a real reply, not an empty one",
    len(unknown_text.strip()) > 40,
    f"kind={unknown['kind']}, {len(unknown_text)} chars",
)
check(
    "4c. and cites no source, because nothing was retrieved",
    not unknown.get("sources"),
    f"sources={[s.get('source') for s in unknown.get('sources') or []]}",
)

# =========================================================================
# 3. Conversation memory — beyond a single turn
# =========================================================================
c = Chat()
c.say("mujhe raat ko neend nahi aati")
c.say("haan bilkul")
recall = c.text(c.say("main aapko kya bata raha tha?"))
check(
    "5a. remembers the topic three turns later",
    any(w in recall.lower() for w in ("neend", "sleep", "insomnia", "anidra", "नींद")),
    recall[:80],
)

# =========================================================================
# 4. Language switching mid-conversation, twice
# =========================================================================
c = Chat()
c.say("gas aur bloating ke liye kya karu")
switched = c.text(c.say("explain that in english please"))
check("6a. switches to English on request", is_english(switched), switched[:70])
switched_back = c.text(c.say("ab isko wapas hinglish me batao"))
check("6b. switches back to Hinglish", is_hinglish(switched_back), switched_back[:70])

# =========================================================================
# 5. REGRESSIONS — fixed this session, previously guarded by nothing
# =========================================================================
c = Chat()
thyroid = c.say("thyroid ke liye kya khana chahiye")
thyroid_text = c.text(thyroid)
check(
    "7a. REGRESSION: 'thyroid...' is not answered with a stock acknowledgement",
    not STOCK.search(thyroid_text),
    thyroid_text[:70],
)
check(
    "7b. REGRESSION: an informational question is answered, not turned into cards",
    thyroid["kind"] == "chat" and substantial(thyroid_text),
    f"kind={thyroid['kind']}, {len(thyroid_text)} chars",
)

c = Chat()
noise = c.say("bs kuch nahi kat rha ha time")
check(
    "7c. REGRESSION: a message with no health signal does not open a consultation",
    noise["kind"] == "chat",
    f"kind={noise['kind']}",
)

c = Chat()
offtopic = c.say("who won the world cup")
offtopic_text = c.text(offtopic)
check(
    "7d. REGRESSION: an off-topic question is declined, not answered with an invented fact",
    offtopic["kind"] == "chat" and not re.search(r"\b(19|20)\d{2}\b", offtopic_text),
    offtopic_text[:70],
)

# =========================================================================
# 6. A real complaint still opens the cards
# =========================================================================
c = Chat()
complaint = c.say("mujhe bahut acidity ho rahi hai")
check(
    "8a. a personal complaint still opens the intake cards",
    complaint["kind"] == "intake",
    f"kind={complaint['kind']}",
)

# =========================================================================
# 7. REGRESSION: "in <adjective> english" is still a language request
# =========================================================================
# "explain in simple english" returned NO requested language, because the
# pattern only matched the preposition and the language side by side. The
# conversation kept its sticky Hinglish and answered an English request in
# Hinglish - the most-reported bug in this project. Pinned in code rather than
# against the LLM, so it fails instantly and deterministically if it returns.
from src.consult.router import requested_language  # noqa: E402

for phrase, want in [
    ("explain in simple english", "english"),
    ("explain in very simple english", "english"),
    ("in english please", "english"),
    ("english me batao", "english"),
    ("translate this into english", "english"),
    ("in easy hindi", "devanagari"),
    ("ab isko hindi me batao", "devanagari"),
    ("हिंदी में बताओ", "devanagari"),
    ("hinglish me likho", "hinglish"),
    # Must stay silent: ordinary sentences are not language requests, and a
    # pattern loose enough to fire here would hijack every other turn.
    ("i have gas problem", ""),
    ("what does ayurveda say about sleep", ""),
    ("tell me more", ""),
]:
    got = requested_language(phrase)
    check(
        f"9. REGRESSION: requested_language({phrase!r}) -> {want!r}",
        got == want,
        f"got {got!r}",
    )

# =========================================================================
# 8. REGRESSION: "hii" during intake must not become a symptom
# =========================================================================
# Typing "hii" while the cards were open filed it as extra detail and pushed the
# questionnaire to round 2, so saying hello got "Almost done - what would you
# like me to cover?". The graph had a branch for this but it ran on the ROUTER's
# verdict, so it broke whenever the router disagreed or was unreachable. Now
# settled in code, and pinned here.
from src.consult.router import is_small_talk  # noqa: E402

for phrase, want in [
    ("hii", True),
    ("hello", True),
    ("namaste", True),
    ("नमस्ते", True),
    ("thanks", True),
    ("ok", True),
    ("bye", True),
    # Must NOT match. Swallowing a real complaint because it opens with a
    # greeting would be a far worse bug than the one this fixes.
    ("hi, mujhe acidity hai", False),
    ("hello I have gas problem", False),
    ("namaste, sar dard ho raha hai", False),
    ("ok but what about food", False),
]:
    check(
        f"10. REGRESSION: is_small_talk({phrase!r}) is {want}",
        is_small_talk(phrase) == want,
        f"got {is_small_talk(phrase)}",
    )

# ---------------------------------------------------------------------------
# 11. The detector must not read ordinary English as Hinglish.
#
# `_HINGLISH_MARKERS` used to treat every romanised Hindi word as proof, and some
# of those words are English: `me` matched "Tell me more", "Give me a diet plan"
# and "Can you help me with my digestion?"; `sir` matched "Sir, what should I
# do?". Seven of nine plain English sentences came back hinglish.
#
# The damage was not one mislabelled turn. Conversation language is sticky — it
# is detected only when unset — so a misread FIRST message locked the whole
# conversation into Hinglish, which is what users reported as "English answers
# keep turning into Hinglish".
from src.consult.router import detect_language  # noqa: E402

for phrase, want in [
    # English that contains a weak marker and must stay English.
    ("Can you help me with my digestion?", "english"),
    ("Tell me more about ashwagandha", "english"),
    ("Give me a diet plan", "english"),
    ("What can you do for me?", "english"),
    ("Please guide me on yoga", "english"),
    ("Sir, what should I do?", "english"),
    ("tell me more", "english"),
    ("What should I eat in the morning?", "english"),
    ("I have trouble sleeping at night", "english"),
    # Hinglish must still be recognised — one strong marker is enough.
    ("mujhe acidity hai", "hinglish"),
    ("kya main yoga kar sakta hoon", "hinglish"),
    ("neend nahi aati", "hinglish"),
    ("mera pet kharab hai", "hinglish"),
    ("roz subah kya khana chahiye", "hinglish"),
    # Two weak markers together are Hindi grammar showing through.
    ("ye kar ke dekho", "hinglish"),
    ("मुझे नींद नहीं आती", "devanagari"),
]:
    check(
        f"11. detect_language({phrase!r}) is {want}",
        detect_language(phrase) == want,
        f"got {detect_language(phrase)}",
    )

failed = [name for name, ok, _ in results if not ok]
print(f"\n===== language & memory: {len(results) - len(failed)}/{len(results)} passed =====")
if failed:
    print("\nFailing:")
    for name in failed:
        print(f"  - {name}")
sys.exit(1 if failed else 0)
