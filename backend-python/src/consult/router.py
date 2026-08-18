"""
consult/router.py
-----------------
Decides what the user actually wants before the consultation machinery starts.

Without this, every message — "hi", "thanks", "what can you do?" — was treated as
a health complaint and answered with a set of symptom cards. That made the
assistant feel like it had exactly one canned behaviour.

Now a message is classified first. Only a genuine health complaint starts the
intake; everything else gets a real conversational reply that ends by asking what
the user needs help with, so the conversation still leads somewhere.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import HumanMessage

import config
from src import prompts
from src.consult.repair import extract_json
from src.knowledge import match_topics
from src.llm import invoke as llm_invoke

Intent = Literal[
    "health", "greeting", "casual", "thanks", "goodbye", "refusal", "about",
    "knowledge", "other", "unavailable",
]
# "unavailable" is ours, never the model's — it means we couldn't reach the model.
VALID_INTENTS = {
    "health", "greeting", "casual", "thanks", "goodbye", "refusal", "about",
    "knowledge", "other",
}
# Intents answered with a plain conversational reply rather than question cards.
CONVERSATIONAL = {
    "greeting", "casual", "thanks", "goodbye", "refusal", "about", "other",
    "unavailable",
}

def describe_outage(detail: str) -> str:
    """Explain WHY the AI is unreachable, not just that it is.

    "Main abhi thoda busy hoon" was useless — it looks like a hiccup, so the user
    keeps retrying against a limit that will not clear for hours. The daily quota
    is by far the most common cause here (Groq's free tier is 100k tokens per
    model per day), so it gets its own message, with the provider's own retry
    time when it gives one.
    """
    lowered = (detail or "").lower()

    if "per day" in lowered or "tpd" in lowered or "quota" in lowered:
        wait = re.search(r"try again in ([\d]+m[\d.]+s|[\d.]+s)", detail or "")
        when = f" Thodi der baad try karein (~{wait.group(1)})." if wait else ""
        return (
            "⚠️ Aaj ki daily AI limit khatam ho gayi hai." + when +
            " (Daily AI credit limit reached — please try again later.)"
        )

    if "rate limit" in lowered or "429" in lowered:
        wait = re.search(r"try again in ([\d]+m[\d.]+s|[\d.]+s)", detail or "")
        when = f" (~{wait.group(1)})" if wait else ""
        return (
            f"⚠️ Bahut saare requests ek saath aa gaye. Thodi der baad try karein{when}."
            " (Too many requests — please wait a moment.)"
        )

    if "401" in lowered or "unauthorized" in lowered or "api key" in lowered or "authentication" in lowered:
        return (
            "⚠️ AI service ki API key galat ya expire ho gayi hai. "
            "(The AI service key is invalid — this needs fixing in settings.)"
        )

    return (
        "⚠️ AI service se abhi connect nahi ho pa raha. Thodi der baad try karein. "
        "(Can't reach the AI service right now.)"
    )

# Signatures of "the model is not reachable" as opposed to "the model replied
# with something unexpected". Only the former should stop the consultation.
_UNAVAILABLE_MARKERS = (
    "rate limit",
    "rate_limit",
    "429",
    "quota",
    "insufficient_quota",
    "401",
    "unauthorized",
    "invalid api key",
    "authentication",
    "timeout",
    "timed out",
    "connection",
    "503",
    "502",
    "overloaded",
    "service unavailable",
)


def is_unavailable(error_text: str) -> bool:
    lowered = (error_text or "").lower()
    return any(marker in lowered for marker in _UNAVAILABLE_MARKERS)


# --- follow-up detection ---------------------------------------------------
# "Explain this in English" is not a new question — it is an instruction about
# the answer already on screen. The classifier had no such intent, so it fell
# through to "casual" and the user got "Theek hai! Main yahin hoon", which reads
# as the assistant ignoring them.
#
# This is matched in code rather than left to the model: the phrasings are a
# small closed set, and getting it wrong is very visible.
#
# The set is split in two because the two halves need opposite treatment, and
# treating them the same produced a reproducible bug:
#
#     what is ashwagandha?  ->  "Ashwagandha is a root-based herb widely used…"
#     tell me more          ->  "Ashwagandha is a root-based herb widely used…"
#
# Both went to `rework_answer`, whose prompt says to work ONLY from the previous
# answer and introduce no new facts. That is exactly right for "say it in
# English" and exactly wrong for "tell me more", which is a request for material
# that is BY DEFINITION not in the previous answer.
_REWORK_PATTERNS = (
    # rewrite / translate the previous answer
    r"\b(in|into|me|mein)\s+(english|hindi|hinglish|marathi|gujarati|tamil|telugu|bengali|punjabi|urdu|kannada|malayalam)\b",
    r"\btranslate\b",
    r"\b(english|hindi|marathi|gujarati|punjabi|urdu)\s+(me|mein)\s+(bata|batao|likh|samjha)",
    # explain / simplify / summarise — referring to what was just said
    r"\bexplain\s+(this|it|that|the\s+above|again)\b",
    r"\b(simplify|summari[sz]e|shorten)\b",
    r"\b(simple|easy|aasan)\s+(words|language|bhasha|terms)\b",
    r"\b(short|brief)\s+(version|answer|me|mein)\b",
    r"\bin\s+(short|brief|simple)\b",
    r"\b(tell|explain|samjha|batao|bata)\s+(me\s+)?(this|it|that|isko|ise|yeh|ye)\b",
    r"\b(iska|isko|ise|uska|usko)\s+(matlab|translation|hindi|english)\b",
    r"\b(above|previous)\s+(answer|response|message)\b",
    r"\bsummar(y|ise|ize)\b",
    # Clarification requests about the previous answer.
    r"\bwhat\s+do\s+you\s+mean\b",
    r"^\s*(why|how|kyun|kyu|kaise)\s*\??\s*$",
    r"^\s*(matlab|iska\s+matlab)\s*\??\s*$",
    r"^\s*(above|that|this|it|isko|usko|yeh|ye)\s*\??\s*$",
)

# "Keep going" — carries no topic of its own, and asks for material the previous
# answer does not contain. Note where the near-misses fall: "in short" reworks,
# "in detail" continues; "explain this" reworks, "explain more" continues.
_CONTINUATION_PATTERNS = (
    r"^\s*(tell\s+me\s+)?more\b",
    r"\b(tell|say)\s+me\s+more\b",
    r"\bexplain\s+more\b",
    r"\b(elaborate|expand)\b",
    r"\bmore\s+detail",
    r"\bin\s+detail\b",
    r"\b(detailed|detail)\s+(version|answer|me|mein)\b",
    r"\b(continue|carry\s+on|go\s+on|and\s+then)\b",
    r"^\s*(aage|aur\s+batao|aur\s+bataiye|jari\s+rakho|continue\s+karo)\b",
    r"\b(give|show)\s+(me\s+)?(an?\s+)?examples?\b",
    r"^\s*examples?\b",
    r"\bexample\s+(do|dijiye|batao)\b",
)

_FOLLOWUP_RE = re.compile(
    "|".join(_REWORK_PATTERNS + _CONTINUATION_PATTERNS), re.IGNORECASE
)
_CONTINUATION_RE = re.compile("|".join(_CONTINUATION_PATTERNS), re.IGNORECASE)


def is_followup_request(text: str) -> bool:
    """Is this an instruction about the previous answer rather than a new question?

    Still matches everything it used to — the split below narrows what happens
    next, not what counts as a follow-up. Callers that branch on this keep
    working unchanged.
    """
    return bool(_FOLLOWUP_RE.search(text or ""))


def is_continuation_request(text: str) -> bool:
    """"Tell me more" — a follow-up asking to ADD, not to re-present.

    Always a subset of `is_followup_request`, so check this one first.
    """
    return bool(_CONTINUATION_RE.search(text or ""))


# --- small talk, decided in code -------------------------------------------
# A greeting typed while the intake cards are open must NEVER become a symptom
# note. It did: "hii" was filed as extra detail and pushed the questionnaire on
# to its second round, so the user got "Almost done, what would you like me to
# cover?" in reply to hello.
#
# The graph already had a branch for this, but it ran on the router's verdict -
# so the moment the router called "hii" anything other than conversational (or
# could not be reached at all), the greeting fell through and became a symptom.
# This is a tiny closed set and getting it wrong is glaringly visible, so it is
# settled here in code, exactly like `is_followup_request`.
_SMALL_TALK = re.compile(
    r"^\s*(?:"
    r"h+i+|h+e+y+|h+e+l+o+|hii+|hlo|yo|hola"
    r"|namaste|namaskar|नमस्ते|नमस्कार"
    r"|good\s*(?:morning|afternoon|evening|night)"
    r"|thanks?|thank\s*you|thx|ty|shukriya|dhanyavaad|धन्यवाद"
    r"|ok+|okay|okk+|k|hmm+|acha|achha|theek|thik|sahi|haan|ha|yes|no|nope"
    r"|bye|byee+|goodbye|alvida"
    r"|kaise\s*ho|kya\s*haal|how\s*are\s*you|sup|wassup"
    r")\s*[!.?😀-🿿]*\s*$",
    re.IGNORECASE,
)


def is_small_talk(text: str) -> bool:
    """A bare greeting, acknowledgement or sign-off - nothing to consult about.

    Anchored at both ends on purpose. "hi" must match, but "hi, mujhe acidity
    hai" must NOT - that one carries a real complaint and losing it would be a
    far worse bug than the one this fixes.
    """
    return bool(_SMALL_TALK.match(text or ""))


# --- complaint vs question -------------------------------------------------
# "Mujhe acidity hai" and "acidity kis par depend karta hai" both contain a
# health word, so the signal check alone sent BOTH into a consultation — the
# second one deserved an explanation, not a five-card questionnaire.
#
# The distinguishing feature is whether they are talking about THEMSELVES. A
# complaint says "mujhe", "mera", "I have". A general question asks "what is",
# "kya hai", "kis par depend".
# Hinglish has no fixed spelling, so these are matched by stem rather than by a
# list of exact words. That gap caused the worst failure this assistant has had:
# the pattern held "mujhe" but the user typed "mujha", so "accha mujha na cancer
# ha ek saal se" carried no personal marker, the health verdict was overruled,
# and a cancer disclosure came back as "Theek hai! 😄 Main yahin hoon."
#
#   muj\w*   mujhe, mujha, muje, mujhko, mujko, mujhy
#   mer[aei] mera, meri, mere   (mereko covered by the same stem + \w*)
#   ham/hum  hamein, humein, hume, hamko
_PERSONAL_MARKERS = re.compile(
    r"\b(muj\w*|mer[aei]\w*|h[au]m\w*|main\b|maine|apna|apni)\b"
    r"|\b(i\s+have|i\s+am|i\s+feel|i've|i\s+got|i\s+get|i\s+suffer|"
    r"my\s|me\s+ko)\b"
    # Devanagari: मुझे, मुझको, मेरा, मेरी, मेरे, हमें
    r"|(मुझ\w*|मेर[ाीे]\w*|हम\w*)",
    re.IGNORECASE,
)
_QUESTION_MARKERS = re.compile(
    r"\b(what\s+is|what\s+are|what\s+does|how\s+does|why\s+does|tell\s+me\s+about|"
    r"according\s+to|explain|meaning\s+of|kya\s+hai|kya\s+hota|kya\s+kehta|kis\s+par|"
    # Hindi verb endings vary by gender/number, so cover hai/hota/hoti/hote/hote.
    r"kya\s+hot[aeiou]|kaise\s+hot[aeiou]|kyun\s+hot[aeiou]|kaise\s+kaam|"
    r"ke\s+baare|ke\s+bare|batao\s+ki|matlab|kaun\s+se|konsa|kitna|"
    # "thyroid ke liye kya khana chahiye" asks what a person with the condition
    # should eat — it wants the note, not a questionnaire. Without these it fell
    # to `is_personal_complaint` and opened five cards instead of answering.
    # Deliberately NOT covering "kya karu" / "kya karun": that is someone asking
    # for help with their own problem, which is exactly what intake is for.
    #
    # The `\w*` endings are load-bearing. This whole alternation sits inside
    # \b(...)\b, so an alternative that stops mid-word can never match: `kya\s+kha`
    # requires a boundary straight after "kha", and in "kya khana" the next
    # character is "n". So "acidity me kya khana chahiye" -- the commonest Hinglish
    # diet question there is -- matched nothing and opened a questionnaire, while
    # the English and Devanagari forms of the same question answered directly.
    # The example in the comment above only passed because `ke\s+liye\s+kya`
    # rescued it, which hid the fact that `kya\s+kha` had never once fired.
    r"ke\s+liye\s+kya|kya\s+kha\w*|kya\s+p[ie]{1,2}n\w*|"
    r"ke\s+fayde|ke\s+nuksan|fayde\s+kya|benefits|kaun\s?s[aei]\w*|"
    r"how\s+to|should\s+i|"
    # IMPERATIVE requests for information. Without these, "give me only a food
    # chart for acidity" matched no question marker and no personal marker, so
    # `is_personal_complaint` fell through to its default of True and opened a
    # five-card questionnaire — the user asked for one section and got the whole
    # machine. An imperative is a request ABOUT a topic; "mujhe/my/I have" is
    # still checked first, so "give me a plan for my acidity" stays a complaint.
    r"give\s+me|show\s+me|tell\s+me|list|suggest|recommend|which|"
    r"batao|bataiye|bata\s+do|batana|naam\s+batao)\b"
    # Devanagari has no \b word boundary that Python recognises around its
    # letters, so these are matched without one.
    r"|(क्या\s+है|क्या\s+होता|क्या\s+खाना|क्या\s+खाएं|के\s+लिए\s+क्या|"
    r"के\s+फायदे|के\s+नुकसान|किस\s+पर|कैसे\s+होता|क्या\s+कहता|"
    r"के\s+बारे\s+में|का\s+मतलब|कौन\s?सा|कौन\s?सी)",
    re.IGNORECASE,
)


_DEVANAGARI = re.compile(r"[ऀ-ॿ]")

# Hindi function words that survive romanisation. Content words ("acidity",
# "migraine") are borrowed into Hinglish unchanged, so they prove nothing —
# only the grammar words tell the two apart.
#
# Split into two tiers because some romanised Hindi words ARE English words, and
# treating every marker as proof made the detector call ordinary English
# "hinglish". `me` was the worst offender: "Tell me more", "Give me a diet plan",
# "Can you help me with my digestion?" all matched on that one word. `sir` did
# the same to "Sir, what should I do?". Seven of nine plain English sentences
# came back hinglish.
#
# That mattered far more than a mislabelled turn. The conversation language is
# sticky by design (graph.py only detects when it is unset), so one bad read of
# the FIRST message locked the whole conversation into Hinglish — which is the
# "English answers keep turning into Hinglish" report.
_HINGLISH_STRONG = re.compile(
    r"\b(mujhe|mujha|mera|meri|mere|hai|hain|raha|rahi|rahe|hota|hoti|nahi|"
    r"kya|kaise|karna|karta|mein|liye|aur|bhi|jyada|zyada|bahut|thoda|roz|"
    r"subah|raat|khana|pet|sar|"
    # How people actually type, as opposed to how the words are spelled.
    # "kes ha ra tu" and "kesa ha tu" are real messages from a real user and
    # both scored ENGLISH, because the list had `kaise` but none of the ways
    # anyone writes it in a hurry. The conversation then locked to English and
    # answered a Hinglish speaker in English for the rest of the session.
    r"kesa|kese|kesi|kaisa|kaisi|"
    r"tum|tumhe|tumhara|tumhari|tera|teri|tere|"
    r"hoon|hun|kyun|kyu|kyon|kahan|kaha|kidhar|kab|"
    r"nahin|nhi|batao|bataiye|bata|bolo|"
    r"accha|acha|theek|thik|yaar|bhai|bhaiya|"
    r"mujhko|humko|hume|humein|bohot|bhot|kuch|"
    r"karu|karun|karo|kariye|chahiye|chaiye|chaiya)\b",
    re.IGNORECASE,
)

# Each of these is either a real English word or a fragment short enough to
# appear by accident. One on its own means nothing; two together are Hindi
# grammar showing through.
# Two of these are needed, because each one alone is too short or too close to an
# English word to be evidence. `tu` is the one that matters for the reported
# case: with the existing `ha`, "kes ha ra tu" now has two and is read correctly.
# Nothing that is ALSO an ordinary English word may be promoted to STRONG —
# turning English conversations Hinglish would be a worse bug than this one.
_HINGLISH_WEAK = re.compile(
    r"\b(ha|kar|ko|ka|ki|ke|se|me|par|din|sir|tu|ho|ab|wo|na)\b",
    re.IGNORECASE,
)


def detect_language(text: str) -> str:
    """`devanagari`, `hinglish` or `english` — decided in code, not by the model.

    The intake planner gets no system prompt and its JSON schema example is in
    English, so asking it to infer the user's language did not work: "mujhe
    acidity hai" still produced "How often do you experience acidity?" with
    English options, while the plan built from those answers came back in
    Hinglish. Naming the language outright removes the inference.

    Hinglish needs either one unambiguous marker or two ambiguous ones. A single
    weak marker is not evidence: `me` and `sir` are English words, and accepting
    one of them was enough to misread most English sentences.
    """
    body = text or ""
    if _DEVANAGARI.search(body):
        return "devanagari"
    if _HINGLISH_STRONG.search(body):
        return "hinglish"
    weak = {match.group(0).lower() for match in _HINGLISH_WEAK.finditer(body)}
    return "hinglish" if len(weak) >= 2 else "english"


# People put an adjective between the preposition and the language far more often
# than not - "in simple english", "in easy hindi", "in proper English". Matching
# only the adjacent form meant "explain in simple english" returned NO requested
# language, the conversation kept its sticky Hinglish, and the user got Hinglish
# back after asking for English. That was the single most-reported bug here, and
# it was this gap, not the prompt.
#
# `\w+` rather than a fixed list of adjectives: any word sitting there is a
# modifier, and enumerating them would just leave the next one broken.
_MOD = r"(?:\s+\w+){0,2}"

_LANGUAGE_REQUESTS = (
    (
        "english",
        re.compile(
            rf"\b(?:in|into|me|mein){_MOD}\s+english\b"
            r"|\benglish\s+(?:me|mein)\b"
            r"|\btranslate\s+(?:it\s+|this\s+)?(?:to|into)\s+english\b",
            re.I,
        ),
    ),
    ("hinglish", re.compile(r"\bhinglish\b", re.I)),
    # Naming the script outright is unambiguous and outranks everything below.
    ("devanagari", re.compile(r"\bdevanagari\b|देवनागरी", re.I)),
    # "hindi" is deliberately NOT resolved here. See `requested_language`.
    (
        "_hindi",
        re.compile(
            rf"\b(?:in|into|me|mein){_MOD}\s+hindi\b"
            r"|\bhindi\s+(?:me|mein)\b"
            r"|हिंदी\s*में|हिन्दी\s*में",
            re.I,
        ),
    ),
)

_DEVANAGARI_CHARS = re.compile(r"[ऀ-ॿ]")


def requested_language(text: str) -> str:
    """The language the user explicitly ASKED for, or "" if they did not.

    Kept separate from `detect_language`, which reports the language a message
    happens to be written in. "explain this in English" is written in English but
    the request is what matters, and it must outrank both the detected language
    and whatever the conversation had settled into.

    "HINDI" MEANS THE SCRIPT THEY ARE ALREADY TYPING IN.
    "hindi me batao" used to resolve to `devanagari` unconditionally, so somebody
    typing in Latin letters asked for Hindi and got देवनागरी back - a script they
    may well not read comfortably, and did not ask for. Hindi written in Latin
    letters is Hinglish, and it is what this product is built around.

    So the script of the REQUEST decides: ask in Devanagari (or name the script
    outright) and you get Devanagari; ask in Latin and you get Hinglish. Naming
    "devanagari" is matched before this and always wins, which is the escape
    hatch for a Latin typist who genuinely wants the script.

    This also matters for length. config.py measures Devanagari at ~2.6x the
    tokens per character of Latin, so an unwanted script switch was also the
    fastest way to reach the answer ceiling and get a truncated plan.
    """
    body = text or ""
    for name, pattern in _LANGUAGE_REQUESTS:
        if pattern.search(body):
            if name != "_hindi":
                return name
            return "devanagari" if _DEVANAGARI_CHARS.search(body) else "hinglish"
    return ""


def is_personal_complaint(text: str) -> bool:
    """Are they describing their OWN problem, or asking a general question?"""
    if _PERSONAL_MARKERS.search(text or ""):
        return True
    # No "mujhe"/"I have", but clearly interrogative -> a question about the topic.
    return not _QUESTION_MARKERS.search(text or "")


# --- grounding guard -------------------------------------------------------
# The classifier is not reliable enough to be trusted on its own. Observed:
#
#   "bs kuch nahi kat rha ha time"  -> health, condition "Digestive Discomfort"
#   "2+2 kitna hota hai"            -> health, condition "Digestive Issue"
#
# Both invented a complaint the user never made, and starting a consultation is
# the most intrusive thing this app can do. So a "health" verdict is only
# honoured when the message actually contains a health signal — otherwise we
# treat it as chit-chat. Erring this way is cheap: a missed complaint costs the
# user one more sentence, an invented one costs them a whole irrelevant form.
# Symptom and body words only. Condition NAMES deliberately live in the
# knowledge base's `aliases:` front matter instead — see `has_health_signal`.
_HEALTH_SIGNALS = (
    # Hindi / Hinglish
    "dard", "dukh", "peeda", "pareshan", "takleef", "problem", "samasya",
    "bimar", "bemar", "tabiyat", "tabiat", "sehat", "pet", "sar ", "sir ",
    "sirdard", "sardard", "gas", "jalan", "khujli", "sujan", "motion", "dast",
    "ulti", "vomit", "khansi", "khasi", "zukam", "sardi", "bukhar", "fever",
    "neend", "nind", "sona", "thakan", "kamzor", "kamzori", "chakkar",
    "ghabra", "tension", "chinta", "wajan", "vajan", "baal", "twacha",
    "kamar", "ghutna", "haath", "pair", "aankh", "kaan", "daant", "saans",
    # English
    "pain", "ache", "hurt", "sick", "ill", "unwell", "symptom", "suffering",
    "issue", "bloat", "nausea", "tired", "fatigue", "swell", "cramp",
    "burning", "weak", "itch", "rash", "allerg", "cough", "cold", "sleep",
    "health", "digest", "appetite", "weight", "stomach", "throat", "chest",
    "breath", "joint", "not feeling", "feeling low", "feel sick", "feeling sick",
)


def has_health_signal(text: str) -> bool:
    """True when the message actually mentions something health-related.

    Two sources, because the hand-written list above cannot keep up on its own.
    It had no entry for thyroid, cholesterol, piles, dandruff, acne, menopause or
    immunity, so "thyroid ke liye kya khana chahiye" was demoted to chit-chat and
    answered with a stock acknowledgement — the exact failure this guard exists
    to avoid causing.

    The knowledge base already names every condition it covers, in English,
    Hinglish and Sanskrit, so it is consulted as the second source. Any note
    added later extends this automatically; the literal list stays only for
    symptom words ("dard", "jalan") that belong to no single topic.
    """
    lowered = f" {(text or '').lower()} "
    if any(signal in lowered for signal in _HEALTH_SIGNALS):
        return True
    try:
        return bool(match_topics(text))
    except Exception:  # noqa: BLE001 - never let a cold vector store block routing
        return False

# This one call does two jobs with opposite needs: a JSON classification, which
# wants determinism, and the conversational reply itself, which must not read the
# same every time. Measured on `gemini-2.5-flash-lite`, 15/15 probes classified
# correctly at 0.4, 0.7 and 0.9 alike — but three "hi" turns produced ONE
# distinct greeting at 0.4 and three at 0.7. So the classification is not what
# the temperature was constraining; it was only flattening the prose.
# 0.7, being the lower of the two settings that gave full variety.
ROUTER_TEMPERATURE = 0.7
MAX_REPLY_CHARS = 700

# The router runs on every single message but only emits a small JSON
# classification, so it names its own model rather than always taking the best
# one. Spending the answer model's budget on classification buys nothing the user
# can see.
#
# This is a PREFERENCE, not a hard pin. It used to be absolute, and that made the
# router a single point of failure: when its one model hit the daily token limit,
# every consultation returned the red banner even though another model in the
# chain was healthy with a separate budget. `llm._available_models` now tries
# this one first and falls through to the rest of the chain.
ROUTER_MODEL = config.ROUTER_MODEL


@dataclass(frozen=True)
class Route:
    intent: Intent
    reply: str = ""
    problem: str = ""


# A second, hotter attempt used only when the first reply repeats the previous
# one verbatim. Higher than ROUTER_TEMPERATURE on purpose: the point is to move
# the model off an answer it has already settled on, and 0.7 demonstrably was not
# enough to do that on its own.
REPEAT_RETRY_TEMPERATURE = 1.0


def _normalise(text: str) -> str:
    """Lowercased, punctuation-free, for comparing two replies as sentences."""
    return re.sub(r"[^a-z0-9ऀ-ॿ ]+", "", (text or "").lower()).strip()


def _recent_assistant_lines(history: str, limit: int = 3) -> list[str]:
    """The assistant's last few replies, newest first.

    More than one, because repeating what you said THREE turns ago reads just as
    mechanically as repeating the last thing. Observed: four "how are you"s in a
    row where the fourth answer matched the second word for word, which a
    previous-line-only check waves through.
    """
    lines = [
        line[5:].strip()
        for line in reversed((history or "").splitlines())
        if line.startswith("You: ")
    ]
    return lines[:limit]


def _repeats(reply: str, previous: str) -> bool:
    """Is this the same sentence the assistant already said?

    Compared normalised, and by PREFIX in both directions, because neither text
    is necessarily whole: chat history stores 400 characters per turn, and one
    reply is often the other plus a trailing clause ("Main theek hoon, aap kaise
    hain?" versus the same sentence followed by an offer to help). Those are the
    same reply as far as a reader is concerned.

    20 characters is the floor for the prefix test — below that, two genuinely
    different short replies ("Theek hai!" / "Theek hai bhai") would collide.
    """
    a, b = _normalise(reply), _normalise(previous)
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return len(shorter) >= 20 and longer.startswith(shorter)


def _repeats_any(reply: str, previous: list[str]) -> bool:
    return any(_repeats(reply, line) for line in previous)


def _route_sync(
    message: str,
    history: str,
    greeted: bool,
    language: str = "",
    temperature: float = ROUTER_TEMPERATURE,
    avoid: str = "",
) -> Route:
    # `avoid` quotes back the sentence the model just produced and forbids it.
    #
    # Raising the temperature alone did NOT work — measured, the model returned
    # the identical sentence at 1.0 as at 0.7, five times out of five. A model
    # settled on a canonical answer needs to be told which answer is off limits,
    # not merely nudged.
    instruction = (
        f'\n\nYOU JUST SAID THIS, WORD FOR WORD: "{avoid}"\n'
        "Do not say it again. Answer the same message with the same meaning, in "
        "genuinely different words - a different opening, a different sentence "
        "shape. Repeating yourself verbatim is the one thing you must not do here."
        if avoid
        else ""
    )
    raw = llm_invoke(
        [
            HumanMessage(
                content=prompts.ROUTER_PROMPT.format(
                    message=message,
                    history=history,
                    greeted="yes" if greeted else "no",
                    # Empty on the first short message, where there is nothing to
                    # be faithful to yet - say so plainly rather than passing a
                    # blank the model has to interpret.
                    language=language or "not yet established",
                )
                + instruction
            )
        ],
        temperature=temperature,
        json_mode=True,
        model=ROUTER_MODEL,
        max_tokens=config.MAX_TOKENS_ROUTER,
    )

    parsed = extract_json(raw) or {}
    intent = str(parsed.get("intent") or "").strip().lower()
    if intent not in VALID_INTENTS:
        # An unrecognised intent must not silently swallow a real complaint, so
        # fall back to treating it as one.
        print(f"[consult] router returned unknown intent {intent!r}; treating as health")
        return Route(intent="health", problem=message)

    return Route(
        intent=intent,  # type: ignore[arg-type]
        reply=str(parsed.get("reply") or "").strip()[:MAX_REPLY_CHARS],
        problem=str(parsed.get("problem") or "").strip()[:300],
    )


async def route_message(
    message: str, history: str = "", greeted: bool = False, language: str = ""
) -> Route:
    """Classify one user message in context and, when it isn't a complaint, answer it.

    `history` and `greeted` are what stop the assistant repeating itself: without
    them every message looked like the first one, so "I don't need help, I was
    just texting" got the welcome message a second time.

    `language` is the conversation's resolved language. It matters because this
    function does not only classify - for every conversational intent it also
    WRITES the reply the user reads, and that reply used to be produced with no
    knowledge of the conversation's language at all. It simply mirrored the
    message, so "Ab se Hindi mein answer karo" (Latin script) was answered in
    Hinglish and the Hindi only began on the following turn. Every other writing
    path already took the resolved language; this one was the gap.
    """
    text = (message or "").strip()
    if not text:
        # An empty send is not a health complaint; say nothing new.
        return Route(intent="casual", reply="")

    try:
        route = await asyncio.to_thread(_route_sync, text, history, greeted, language)
    except Exception as error:  # noqa: BLE001
        detail = str(error)
        print(f"[consult] router failed: {detail}")
        # The model itself is unreachable (rate limit, outage, bad key). Falling
        # back to "health" here would start a consultation that cannot possibly
        # finish, so the user ends up staring at "I couldn't complete your plan"
        # next to a set of useless cards. Say what's actually happening instead.
        if is_unavailable(detail):
            return Route(intent="unavailable", reply=describe_outage(detail))
        return Route(intent="health", problem=text)

    # Ask again when the model has just repeated itself word for word.
    #
    # The prompt already forbids this, and the model does it anyway: asked "how
    # are you" three times it returned "I am functioning well, thank you for
    # asking. I hope you are doing well too." three times, character for
    # character. Instructions alone were not enough, so this checks.
    #
    # One retry, at a higher temperature, and whatever comes back is accepted —
    # a loop chasing novelty would spend the user's time and our budget on the
    # least important sentence in the conversation. Costs an extra call only in
    # the rare case that the first reply actually was a repeat.
    if route.intent in CONVERSATIONAL and route.reply:
        previous = _recent_assistant_lines(history)
        if _repeats_any(route.reply, previous):
            print(f"[consult] reply repeats an earlier one; asking again: {route.reply[:50]!r}")
            try:
                retried = await asyncio.to_thread(
                    _route_sync,
                    text,
                    history,
                    greeted,
                    language,
                    REPEAT_RETRY_TEMPERATURE,
                    route.reply,
                )
                if retried.reply and not _repeats_any(retried.reply, previous):
                    route = retried
            except Exception as error:  # noqa: BLE001
                # The first reply is still a usable answer; a repeat is far
                # better than an error.
                print(f"[consult] repeat retry failed, keeping the first reply: {error}")

    # Off-topic questions get a FIXED reply, never the model's own words.
    # Left to itself the model answers them — one test run produced "Arre, world
    # cup ka match toh 2 din pehle hi khela tha!", an invented sports fact from a
    # health assistant. There is no upside to free-forming here: the only correct
    # response is "that's outside what I do", so say exactly that.
    if route.intent == "other":
        return Route(intent="other", reply=_FALLBACK_REPLIES["other"])

    # A conversational intent with no reply would render an empty bubble. Falling
    # back to the consultation would be worse — answering "bye" with symptom cards
    # is exactly the bug being fixed — so give a short, safe acknowledgement.
    if route.intent in CONVERSATIONAL and not route.reply:
        return Route(intent=route.intent, reply=_FALLBACK_REPLIES.get(route.intent, _FALLBACK_REPLIES["casual"]))

    if route.intent == "health":
        # Don't open a questionnaire off a message that never mentioned a symptom
        # — UNLESS the user plainly said it is about themselves.
        #
        # This second clause is the important one. The keyword list can never be
        # complete, and treating it as the sole evidence produced the worst
        # failure this assistant has had: "mujha na cancer ha ek saal se" matched
        # nothing in the list and no note in the corpus, so a cancer disclosure
        # was demoted to chit-chat and answered "Theek hai! 😄 Main yahin hoon."
        #
        # "mujhe X hai" / "I have X" is a first-person disclosure whatever X is,
        # and no vocabulary check should be able to overrule it. The guard still
        # holds for messages with no personal marker at all, which is what it was
        # built for ("bs kuch nahi kat rha ha time").
        if not has_health_signal(text) and not _PERSONAL_MARKERS.search(text):
            # ...unless the CONVERSATION is already about health. A follow-up
            # leans on what came before and carries no vocabulary of its own:
            # "What should I avoid?" after two turns about acidity has no symptom
            # word and no "I have", so the guard fired and answered it with the
            # casual acknowledgement — "Theek hai! 😄 Main yahin hoon" in reply to
            # a real question, mid-consultation. Observed live.
            #
            # `knowledge`, not `health`: this answers the question from the notes
            # and cannot open a questionnaire, so honouring the verdict here
            # stays within what the guard was protecting against. Inventing a
            # consultation is still impossible; only the wrongly-dismissed
            # question changes.
            if has_health_signal(history):
                print(f"[consult] health follow-up in an active conversation: {text[:60]!r}")
                return Route(intent="knowledge")
            print(f"[consult] ignoring ungrounded health verdict for {text[:60]!r}")
            return Route(intent="casual", reply=_FALLBACK_REPLIES["casual"])
        # "Acidity kis par depend karta hai?" mentions a symptom but is a question
        # about the topic, not a complaint. Answer it; don't hand them a form.
        if not is_personal_complaint(text):
            print(f"[consult] health question, not a complaint: {text[:60]!r}")
            return Route(intent="knowledge")
        if not route.problem:
            return Route(intent="health", problem=text)

    return route


# Used only when the model returns a conversational intent with an empty reply.
_FALLBACK_REPLIES = {
    "greeting": "Namaste! 🌿 Bataiye, main aapki kya madad kar sakta hoon?",
    "casual": "Theek hai! 😄 Main yahin hoon, jab bhi zarurat ho bata dena.",
    "thanks": "Khushi hui madad karke! 🌿",
    "goodbye": "Take care! Apna dhyan rakhiye. 🌿",
    "refusal": "Bilkul theek hai — main yahin hoon jab bhi zarurat ho. 🌿",
    "about": "Main Ayurveda aur Yoga ki guidance deta hoon — root cause, khaana, yoga aur daily routine.",
    "other": (
        "Ye mere kaam ka hissa nahi hai 🙂 Main sirf Ayurveda, Yoga aur wellness "
        "mein madad karta hoon. Aapki sehat se juda koi sawaal ho to bataiye!"
    ),
}
