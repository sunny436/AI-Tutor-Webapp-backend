"""What a student's latest message asks for, read by Ollalink's classification model.

`POST {OLLALINK_BASE_URL}/v1/classify` with the header `X-NH-GPU-Key` (the key is the credential and
is never logged). app/chat/service.py applies the reading (INTENT_ROUTER=on) or only records it (shadow).

- **Two requests, one question each** (app/intents/taxonomy.py): the group question, then only the
  chosen group's question; every option is a fixed text of at most 80 characters. Each question and
  each long option costs time (2026-10-22, warm, server time: one question with nine short options
  260 ms, two such questions in one request 417 ms, all nine with the owner's long criteria 4.6 s).
  The second request is not made when the group is `other` or P(group) is below
  INTENT_MIN_GROUP_CONFIDENCE.
- **What is sent** (`text_for`, at most about 1,100 characters): the latest message (its first 600
  and last 400 characters when longer) and the kinds of the files it attaches, never their names.
  For a short follow-up (six words or fewer and at most 200 characters: "why?", "make it shorter"),
  also the message before it and the end of the tutor's reply, each labelled context only. Never who
  the student is or their settings.
- **Applied only when it is clear** (`Scored.decide`): every field of each response is checked, or
  none of it is used (bad_response). The best intent is the most likely one in the group the group
  question chose, so its group is always that choice; it is applied only when the group is not
  `other`, P(group) is at least INTENT_MIN_GROUP_CONFIDENCE and P(group) x P(intent | group) at least
  INTENT_MIN_CONFIDENCE. Otherwise there is no intent: the tutor as before.
- **An explicit constraint first** (`explicit_hint_only`): a message that asks only for a hint (in
  English, Hindi or Hinglish) is hint_only, whatever the model says and whether or not it answers.
- **Fast failure:** one pooled client; both requests together are capped by INTENT_ROUTER_TIMEOUT_S
  and never retried, and a failure in either is no intent (never a guess from the group alone).
  After 3 slow failures (timeouts, no connection) in a row, calls pause for 60 s; a refused key
  (401/403) pauses them for 10 minutes, a rate limit (429) for its Retry-After. `classify` never
  raises: a failure is a reason code, and the turn goes on without an intent.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
import unicodedata
from dataclasses import dataclass, replace
from typing import Any

import httpx

from app.intents.scope import QUESTION as SCOPE_QUESTION
from app.intents.scope import QUESTION_ID as SCOPE_ID
from app.intents.scope import Scope, decide
from app.intents.taxonomy import (
    ABSTAIN,
    GROUP_MEMBERS,
    GROUP_QUESTION,
    GROUPS,
    INTENT_QUESTION,
    INTENTS,
    TAXONOMY_VERSION,
)
from app.llm.base import ChatMessage
from app.llm.openai_compatible import redact_secrets
from app.logging import get_logger
from app.rag.graph import FOLLOW_UP_MAX_WORDS

log = get_logger("app.intents")

CLASSIFY_PATH = "/v1/classify"
KEY_HEADER = "X-NH-GPU-Key"
USER_AGENT = "PadhAI/1"
CURRENT_CHARS = (600, 400)  # the head and tail of a longer message
PREVIOUS_CHARS = (300, 100)
REPLY_TAIL_CHARS = 200
FOLLOW_UP_MAX_CHARS = 200  # six words can still be long (a pasted equation or link): no context then
SLOW_FAILURES_TO_PAUSE = 3
SLOW_PAUSE_S = 60.0
KEY_PAUSE_S = 600.0
RETRY_AFTER_S = (1, 30, 300)  # the shortest, the default and the longest pause after a 429
KINDS = {"image": "an image", "pdf": "a PDF"}  # any other attached file is "a file"
# Warm-ups (IntentClassifier.nudge): what one asks (no student's words), how long it may take (a whole cold
# start; it never holds up a reply), and how long an idle connection is kept (httpx's default is 5 s).
WARM_TEXT = "Current message: hello"
WARM_TIMEOUT_S = 10.0
KEEPALIVE_S = 300.0
FAILED = frozenset(
    {"timeout", "unavailable", "unauthorized", "rate_limited", "bad_request", "bad_response", "internal_error"}
)

# Each request asks one of these: "group" first, then the chosen group's own question. The options are
# the compact texts (taxonomy.py `option`); the owner's long criteria are never sent.
QUESTIONS: dict[str, dict[str, Any]] = {
    "group": {"type": "choice", "question": GROUP_QUESTION, "options": dict(GROUPS)},
    **{
        group: {
            "type": "choice",
            "question": INTENT_QUESTION,
            "options": {name: INTENTS[name].option for name in members},
        }
        for group, members in GROUP_MEMBERS.items()
    },
}

# Every question a request may ask: the router's, and the study scope's own (app/intents/scope.py).
ASKED: dict[str, dict[str, Any]] = {**QUESTIONS, SCOPE_ID: SCOPE_QUESTION}

_FENCED = re.compile(r"(`{3,}|~{3,}).*?(?:\1|\Z)", re.S)
# The student asks only for a hint, in their own words (English, Hinglish, Hindi): explicit constraints
# beat any reading of the message. Saying they do NOT want a hint (_NO_HINT) wins over it.
_HINT_ONLY = re.compile(
    r"\bhints?\s+only\b|\bonly\s+(?:a\s+|one\s+|some\s+)?(?:small\s+|little\s+)?hints?\b"
    r"|\bjust\s+(?:give\s+me\s+)?(?:a\s+|one\s+|some\s+)?(?:small\s+|little\s+)?hints?\b"
    r"|\bgive\s+me\s+(?:a\s+|one\s+)?(?:small\s+|little\s+)?hint\b(?![\s,;]+(?:and|then|with)\b)"
    r"|\b(?:don'?t|do\s+not)\s+(?:tell|give|show)\s+(?:me\s+)?(?:the\s+)?(?:final\s+|full\s+)?(?:answer|solution)\b"
    r"(?!\s+(?:in|as|like|so|too|with|using|only|until|till|before|at\s+the\s+end)\b)"
    r"|\bwithout\s+(?:telling|giving|showing)\s+(?:me\s+)?(?:the\s+)?(?:final\s+|full\s+)?(?:answer|solution)\b"
    r"|\bno\s+(?:answer|solution)s?\W{0,3}just\b"
    r"|\b(?:answer|jawab|uttar|solution)\s+(?:mat|na)\s+(?:batana|batao|bata|btana|do|dena)\b"
    r"|\b(?:bas|sirf|sirff|keval|kewal)\s+(?:ek\s+)?hints?\b"
    r"|\bhints?\s+(?:do|de\s*do|dijiye)\b(?!\s+(?:not|you|i|we|they|it|me|help|helps|work)\b)"  # not English "hints do"
    r"|(?:सिर्फ\u093c?|केवल|बस)\s*(?:एक\s+)?(?:संकेत|हिंट|इशारा)"
    r"|(?:उत्तर|जवाब|आंसर)\s+(?:मत|न)\s+(?:बताना|बताओ|बताएं|बताइए|देना|दो)"
    # Only the next (or first) step, asked for: a hint by another name ("only the first step is hard" is not).
    r"|\b(?:give|tell|show)\s+(?:me\s+)?(?:only|just)\s+(?:the\s+)?(?:next|first)\s+step\b"
    r"|\b(?:only|just)\s+(?:give|tell|show)\s+(?:me\s+)?(?:the\s+)?(?:next|first)\s+step\b"
    r"|\b(?:bas|sirf|sirff|keval|kewal)\s+(?:pehla|pahla|agla|next|first)\s+step\s+(?:bata|batao|batana|btao|dikha|dikhao|do)\b"
    r"|(?:सिर्फ़?|केवल|बस)\s*(?:पहला|अगला)\s*(?:चरण|स्टेप)\s*(?:बताओ|बताइए|बताना|बता\s*दो|दिखाओ)"
    # No full solution; just a pointer to where to begin.
    r"|\bno\s+(?:full|complete|whole|entire)\s+(?:solution|answer)s?\b"
    r"|\b(?:don'?t|do\s+not)\s+(?:want|need)\s+(?:the\s+)?(?:full|complete|whole|entire)\s+(?:solution|answer)\b"
    r"|\b(?:only|just)\s+(?:tell|show|give)\s+(?:me\s+)?(?:where|how)\s+to\s+(?:begin|start)\b"
    r"|\bjust\s+point\s+me\s+in\s+the\s+right\s+direction\b"
    r"|\bbas\s+(?:idea|shuruaat|shuruat)\b|बस\s*(?:पहला|अगला)\s*कदम",
    re.I,
)
# Wanting to solve it themselves (_SELF) and asking how to begin (_START), in the same message: a hint by
# another name ("I'll crack this myself, just tell me where to begin"). Either alone is not.
_SELF = re.compile(
    r"\b(?:solve|do|crack|try|work\s+out|figure\s+out|attempt)\s+(?:it|this|this\s+one|the\s+rest|that)?\s*"
    r"(?:myself|by\s+myself|on\s+my\s+own)\b"
    r"|\bkhud\s+(?:se\s+)?(?:solve|karna|karunga|karungi|karoonga|try|hal)\b"
    r"|(?:खुद|स्वयं)\s*(?:से\s*)?(?:हल|करना|करूँगा|करूंगा|करूंगी|कोशिश)",
    re.I,
)
_START = re.compile(
    r"\b(?:where|how)\s+(?:to|do\s+i|should\s+i|can\s+i)\s+(?:begin|start)\b|\bpoint\s+me\s+in\s+the\s+right\s+direction\b"
    r"|\b(?:first|next)\s+step\b|\b(?:an?\s+)?(?:idea|nudge|clue|pointer)\b"
    r"|\b(?:kaise|kahan\s+se)\s+(?:start|shuru|shuruaat|shuruat)\b|\b(?:shuruaat|shuruat)\b|\bidea\s+do\b"
    r"|\b(?:pehla|pahla|agla)\s+step\b"
    r"|(?:पहला|अगला)\s*(?:कदम|चरण|स्टेप)|कैसे\s*शुरू|शुरुआत",
    re.I,
)
_NO_HINT = re.compile(
    r"\b(?:don'?t|do\s+not|never|no)\s+(?:need|want|give\s+me)\s+(?:for\s+)?(?:just\s+|only\s+)?"
    r"(?:a\s+|any\s+)?hints?\b"
    r"|\b(?:don'?t|do\s+not|never)\s+give\s+(?:me\s+)?(?:only\s+)?hints?\b"
    r"|\bhints?\s+(?:do\s+not|don'?t|does\s+not|doesn'?t)\s+help\b"
    r"|\bnot\s+(?:just|only|merely)\s+(?:a\s+|one\s+)?hints?\b"
    r"|\b(?:no|not)\s+(?:a\s+|any\s+)?hints?\b|\bhints?\s+(?:nahi|nahin|nhi|mat)\b"
    r"|(?:संकेत|हिंट|इशारा)\s+(?:नहीं|मत)"
    # Not wanting to solve it themselves; asking for the whole answer.
    r"|\b(?:don'?t|do\s+not|not)\s+(?:want|like|going)\s+to\s+(?:solve|do|try|crack|work\s+out|figure\s+out)\b"
    r"|\b(?:give|show|tell)\s+me\s+the\s+(?:full|complete|whole|entire)\s+(?:answer|solution)\b",
    re.I,
)


@dataclass(frozen=True)
class Routed:
    """One message's reading: the intent to apply (None: the tutor as before), the best guess with its
    group, its score and P(group), and why nothing is applied."""

    intent: str | None
    best: str | None = None
    group: str | None = None
    confidence: float | None = None  # P(group) x P(best | group)
    group_confidence: float | None = None  # P(group), from the group question
    reason: str | None = None
    latency_ms: int = 0
    forced: bool = False  # explicit_hint_only: no model involved

    def record(self, applied: bool, source: str) -> dict:
        """messages.metadata.intent (internal): what was read, and whether this turn used it."""
        applied = applied and self.intent is not None
        return {
            "id": self.intent if applied else None,
            "best": self.best,
            "group": self.group,
            "confidence": None if self.confidence is None else round(self.confidence, 4),
            "groupConfidence": None if self.group_confidence is None else round(self.group_confidence, 4),
            "applied": applied,
            "forced": self.forced,
            "source": source,
            "reason": self.reason,
            "latencyMs": self.latency_ms,
            "version": TAXONOMY_VERSION,
        }


HINT_ONLY = Routed("hint_only", "hint_only", INTENTS["hint_only"].group, reason="explicit", forced=True)


@dataclass(frozen=True)
class Scored:
    """A checked reading: the group question's choice and P(group); once that group's own question is
    answered, its best intent and the score P(group) x P(intent | group). Only the chosen group's
    question is ever asked, so the best intent's group is always the group question's own choice."""

    group: str
    group_confidence: float
    best: str | None = None
    confidence: float | None = None

    def asks_intent(self, min_group_confidence: float) -> bool:
        """Whether the group's own question is worth asking: not `other`, and P(group) high enough."""
        return self.group != ABSTAIN and self.group_confidence >= min_group_confidence

    def with_intent(self, payload: Any) -> Scored:
        """With the group's own question answered (checked: raises BadResponse)."""
        intents = check(payload, self.group)
        best = max(GROUP_MEMBERS[self.group], key=intents.__getitem__)  # the first of equals: the owner's order
        return replace(self, best=best, confidence=self.group_confidence * intents[best])

    def decide(self, min_confidence: float, min_group_confidence: float) -> tuple[str | None, str | None]:
        """The intent to apply, or None and why not."""
        if self.group == ABSTAIN:
            return None, "other"
        if not self.asks_intent(min_group_confidence) or self.confidence is None or self.confidence < min_confidence:
            return None, "low_confidence"
        return self.best, None


class BadResponse(ValueError):
    """A response that fails a check, named by the check: none of it is used."""


def _flat(text: str) -> str:
    return " ".join(text.split())


def _clip(text: str, head: int, tail: int) -> str:
    return text if len(text) <= head + tail else f"{text[:head]} … {text[-tail:]}"


def text_for(conversation: list[ChatMessage], attachments: tuple[str, ...] = ()) -> str:
    """What is classified: the latest message, with the kinds of the files it attaches; for a short
    follow-up, the message before it and the end of the tutor's reply too, labelled context only. One
    line each, so only the last line starts with "Current message". At most about 1,100 characters."""
    users = [index for index, message in enumerate(conversation) if message.role == "user" and message.content.strip()]
    if not users:
        return ""
    latest = _flat(conversation[users[-1]].content)
    current = _clip(latest, *CURRENT_CHARS)
    kinds = list(dict.fromkeys(KINDS.get(kind, "a file") for kind in attachments))
    if kinds:
        current += f" (attached: {', '.join(kinds)})"
    lines = []
    if len(users) > 1 and len(latest.split()) <= FOLLOW_UP_MAX_WORDS and len(latest) <= FOLLOW_UP_MAX_CHARS:
        lines.append(
            f"Previous message (context only): {_clip(_flat(conversation[users[-2]].content), *PREVIOUS_CHARS)}"
        )
        replies = [m.content for m in conversation[users[-2] + 1 : users[-1]] if m.role == "assistant"]
        reply = _flat(_FENCED.sub(" ", replies[-1])) if replies else ""
        if reply:
            lines.append(
                f"Tutor's reply, end (context only): {'…' if len(reply) > REPLY_TAIL_CHARS else ''}"
                f"{reply[-REPLY_TAIL_CHARS:]}"
            )
    lines.append(f"Current message: {current}")
    return "\n".join(lines)


def request_body(text: str, question: str) -> dict[str, Any]:
    """One request: the text and one question, "group" or then the chosen group's own (or "scope")."""
    return {"text": text, "questions": {question: ASKED[question]}}


def _probability(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1


def check(payload: Any, question: str) -> dict[str, float]:
    """The question's probabilities, renormalised, from its response checked field by field: exactly
    the one question asked, a choice of exactly the options sent, its answer one of them, every value a
    probability. Raises BadResponse naming the first check that fails."""
    answers = payload.get("answers") if isinstance(payload, dict) else None
    if not isinstance(answers, dict) or set(answers) != {question}:
        raise BadResponse(f"{question}.answers")
    answer, options = answers[question], ASKED[question]["options"]
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        raise BadResponse(f"{question}.type")
    if not isinstance(answer.get("answer"), str) or answer["answer"] not in options:
        raise BadResponse(f"{question}.answer")
    if not _probability(answer.get("confidence")):
        raise BadResponse(f"{question}.confidence")
    probabilities = answer.get("probabilities")
    if not isinstance(probabilities, dict) or set(probabilities) != set(options):
        raise BadResponse(f"{question}.options")
    if not all(_probability(value) for value in probabilities.values()):
        raise BadResponse(f"{question}.probabilities")
    total = sum(probabilities.values())
    if total <= 0:
        raise BadResponse(f"{question}.sum")
    return {option: probabilities[option] / total for option in options}


def read_group(payload: Any) -> Scored:
    """The group question's response, checked (raises BadResponse): its choice and P(group)."""
    groups = check(payload, "group")
    group = max(GROUPS, key=groups.__getitem__)  # max keeps the first of equals: the taxonomy's order
    return Scored(group, groups[group])


def score(group_payload: Any, intent_payload: Any = None) -> Scored | None:
    """A message's reading from the responses to its group question and (when it was asked) its
    group's own question, or None when any check fails (bad_response)."""
    try:
        scored = read_group(group_payload)
        return scored if intent_payload is None or scored.group == ABSTAIN else scored.with_intent(intent_payload)
    except BadResponse:
        return None


def explicit_hint_only(text: str) -> bool:
    """Does the message itself ask only for a hint, not the answer? A fixed rule on the student's own
    words, applied before (or without) the classifier: a hint asked for by name, only the next step, no
    full solution, or wanting to solve it themselves together with asking how to begin."""
    text = unicodedata.normalize("NFC", text).replace("’", "'").replace("‘", "'")
    asked = _HINT_ONLY.search(text) is not None or (_SELF.search(text) is not None and _START.search(text) is not None)
    return asked and _NO_HINT.search(text) is None


def _error_code(response: httpx.Response) -> str | None:
    try:
        return redact_secrets(str(response.json()["error"]["code"]))[:40]
    except (ValueError, KeyError, TypeError):
        return None


class _Refused(Exception):
    """A response other than 200: its status is the reason, and may pause the calls (_refused)."""

    def __init__(self, response: httpx.Response):
        super().__init__(response.status_code)
        self.response = response


class IntentClassifier:
    """One pooled HTTP client to Ollalink's classification API, shared by every turn."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_s: float,
        min_confidence: float,
        min_group_confidence: float,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        scope_min_redirect: float = 0.5,
        scope_min_confidence: float = 0.5,
        warm_after_s: float = 0.0,
    ):
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={KEY_HEADER: api_key, "User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=httpx.Timeout(timeout_s, connect=min(1.0, timeout_s)),
            limits=httpx.Limits(max_connections=4, keepalive_expiry=KEEPALIVE_S),
            transport=transport,
        )
        self.warm_after_s = warm_after_s
        self._used = 0.0  # time.monotonic() of the latest request to Ollalink, of any kind
        self._warming: asyncio.Task | None = None
        self.timeout_s = timeout_s
        self.min_confidence = min_confidence
        self.min_group_confidence = min_group_confidence
        self.scope_min_redirect = scope_min_redirect
        self.scope_min_confidence = scope_min_confidence
        self._slow_failures = 0
        self._paused_until = 0.0
        self._paused = False

    async def aclose(self) -> None:
        if self._warming is not None:
            self._warming.cancel()
        await self._client.aclose()

    def nudge(self) -> None:
        """A student is using the app (any signed-in request): when nothing has been sent to Ollalink for
        warm_after_s, send one small warm-up in the background, so their next message doesn't wait for
        the service to wake (after a quiet minute or two a request took 1.2-1.8 s, after a long quiet
        3.6 s, against 0.3 s warm; measured 2026-10-23 from the server). At most one at a time and one
        per warm_after_s, never retried, never while paused; nobody using the app sends nothing. It makes
        the next request likely fast, not certain: that one still has its time limit and fallback."""
        now = time.monotonic()
        if not self.warm_after_s or now - self._used < self.warm_after_s or now < self._paused_until:
            return
        if self._warming is not None and not self._warming.done():
            return
        self._used = now
        self._warming = asyncio.get_running_loop().create_task(self._warm())

    async def _warm(self) -> None:
        started = time.perf_counter()
        try:
            async with asyncio.timeout(WARM_TIMEOUT_S):
                # Its own time limit: the client's (INTENT_ROUTER_TIMEOUT_S) would cut a cold start short and
                # throw its connection away, the very connection the next message should reuse.
                response = await self._client.post(
                    CLASSIFY_PATH, json=request_body(WARM_TEXT, SCOPE_ID), timeout=WARM_TIMEOUT_S
                )
            outcome = str(response.status_code)
        except (TimeoutError, httpx.HTTPError) as error:
            outcome = type(error).__name__
        log.info(
            "classifier warmed",
            extra={"outcome": outcome, "latency_ms": int((time.perf_counter() - started) * 1000)},
        )

    async def classify(self, conversation: list[ChatMessage], attachments: tuple[str, ...] = ()) -> Routed:
        """The intent of the conversation's latest message. Never raises (but when cancelled): a failure
        is a Routed without an intent, with the reason. Logged as metadata only."""
        started = time.perf_counter()
        try:
            routed, details = await self._classify(conversation, attachments)
        except Exception as error:  # noqa: BLE001 - routing never fails a turn
            routed, details = Routed(None, reason="internal_error"), {"error_type": type(error).__name__}
        routed = replace(routed, latency_ms=int((time.perf_counter() - started) * 1000))
        status = "failed" if routed.reason in FAILED else "ok" if routed.best else "skipped"
        log.log(
            logging.WARNING if status == "failed" else logging.INFO,
            "intent classified",
            extra={
                "status": status,
                "reason": routed.reason,
                "intent": routed.intent,
                "best": routed.best,
                "group": routed.group,
                "confidence": routed.confidence,
                "group_confidence": routed.group_confidence,
                "latency_ms": routed.latency_ms,
                **details,
            },
        )
        return routed

    async def _ask(self, text: str, question: str) -> Any:
        """One request with one question: the response's JSON (raises _Refused, BadResponse, httpx errors)."""
        self._used = time.monotonic()
        response = await self._client.post(CLASSIFY_PATH, json=request_body(text, question))
        if response.status_code != 200:
            raise _Refused(response)
        try:
            return response.json()
        except ValueError as error:
            raise BadResponse(f"{question}.json") from error

    async def _classify(self, conversation: list[ChatMessage], attachments: tuple[str, ...]) -> tuple[Routed, dict]:
        if time.monotonic() < self._paused_until:
            return Routed(None, reason="paused"), {}
        text = text_for(conversation, attachments)
        if not text:
            return Routed(None, reason="empty"), {}
        question = "group"
        try:
            async with asyncio.timeout(self.timeout_s):  # both requests together
                first = await self._ask(text, question)
                scored = read_group(first)
                if scored.asks_intent(self.min_group_confidence):
                    question = scored.group
                    scored = scored.with_intent(await self._ask(text, question))
        except (TimeoutError, httpx.TimeoutException):  # "asked": the question's id, "group" or a group's
            return self._slow_failure("timeout"), {"asked": question}
        except httpx.HTTPError as error:
            return self._slow_failure("unavailable"), {"asked": question, "error_type": type(error).__name__}
        except _Refused as refused:
            status = refused.response.status_code
            return self._refused(refused.response), {"asked": question, "http_status": status}
        except BadResponse as error:
            return Routed(None, reason="bad_response"), {"check": str(error)}
        if self._slow_failures or self._paused:
            log.info("intent classifier recovered", extra={"failures": self._slow_failures})
        self._slow_failures, self._paused = 0, False
        intent, reason = scored.decide(self.min_confidence, self.min_group_confidence)
        characters = first.get("characters")
        routed = Routed(intent, scored.best, scored.group, scored.confidence, scored.group_confidence, reason)
        return routed, {"characters": characters if isinstance(characters, int) else None}

    async def scope(self, conversation: list[ChatMessage], attachments: tuple[str, ...] = ()) -> Scope:
        """The study scope of the latest message (app/intents/scope.py): one request of its own, with the
        same client, time limit and pauses as `classify`. Never raises (but when cancelled): a failure is
        no decision, with the reason. Logged as metadata only."""
        started = time.perf_counter()
        try:
            found, details = await self._scope(conversation, attachments)
        except Exception as error:  # noqa: BLE001 - the scope never fails a turn
            found, details = Scope(None, reason="internal_error"), {"error_type": type(error).__name__}
        found = replace(found, latency_ms=int((time.perf_counter() - started) * 1000))
        failed = found.decision is None
        log.log(
            logging.WARNING if failed and found.reason in FAILED else logging.INFO,
            "scope decided",
            extra={
                "status": "failed" if failed else "ok",
                "decision": found.decision,
                "best": found.best,
                "confidence": found.confidence,
                "reason": found.reason,
                "latency_ms": found.latency_ms,
                **details,
            },
        )
        return found

    async def _scope(self, conversation: list[ChatMessage], attachments: tuple[str, ...]) -> tuple[Scope, dict]:
        if time.monotonic() < self._paused_until:
            return Scope(None, reason="paused"), {}
        text = text_for(conversation, attachments)
        if not text:
            return Scope(None, reason="empty"), {}
        try:
            async with asyncio.timeout(self.timeout_s):
                found = check(await self._ask(text, SCOPE_ID), SCOPE_ID)
        except (TimeoutError, httpx.TimeoutException):
            return Scope(None, reason=self._slow_failure("timeout").reason), {}
        except httpx.HTTPError as error:
            return Scope(None, reason=self._slow_failure("unavailable").reason), {"error_type": type(error).__name__}
        except _Refused as refused:
            status = refused.response.status_code
            return Scope(None, reason=self._refused(refused.response).reason), {"http_status": status}
        except BadResponse as error:
            return Scope(None, reason="bad_response"), {"check": str(error)}
        if self._slow_failures or self._paused:
            log.info("intent classifier recovered", extra={"failures": self._slow_failures})
        self._slow_failures, self._paused = 0, False
        return decide(found, self.scope_min_redirect, self.scope_min_confidence), {}

    def _pause(self, seconds: float, reason: str) -> None:
        self._paused_until = time.monotonic() + seconds
        self._paused = True
        log.warning("intent classifier paused", extra={"reason": reason, "pause_s": seconds})

    def _slow_failure(self, reason: str) -> Routed:
        self._slow_failures += 1
        if self._slow_failures >= SLOW_FAILURES_TO_PAUSE:
            self._pause(SLOW_PAUSE_S, reason)
        return Routed(None, reason=reason)

    def _refused(self, response: httpx.Response) -> Routed:
        status = response.status_code
        if status in (401, 403):
            log.warning(
                "intent classifier key unknown, not approved or without access",
                extra={"http_status": status, "code": _error_code(response)},
            )
            self._pause(KEY_PAUSE_S, "unauthorized")
            return Routed(None, reason="unauthorized")
        if status == 429:
            shortest, default, longest = RETRY_AFTER_S
            try:
                seconds = int(response.headers.get("Retry-After", ""))
            except ValueError:
                seconds = default
            self._pause(float(min(max(seconds, shortest), longest)), "rate_limited")
            return Routed(None, reason="rate_limited")
        if status in (400, 413, 422):
            log.warning("intent classifier bad request", extra={"http_status": status, "code": _error_code(response)})
            return Routed(None, reason="bad_request")
        return Routed(None, reason="unavailable")  # 503 while the model loads or is busy, any 5xx: no pause
