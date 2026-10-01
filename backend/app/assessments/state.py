"""Practice tests: a test the tutor writes into a reply, answered one question at a time, graded
and recorded by the server (docs/api-contract.md, "Practice tests").

- **Built with the reply, all or nothing.** `build` runs when the reply is saved
  (ChatService._finalize), in the same UPDATE. A reply holds at most one test: one ```quiz block,
  or one ```mcq for a single question. The whole test is checked first: every question, its
  options and its answer, and the number of questions the student asked for. Anything wrong
  keeps no test at all (the reason is `assessmentError`), never part of one. There is no retry
  behind the student's back: Regenerate is the retry.
- **Questions and grading come only from the saved reply.** The record keeps the test's
  canonical form and its sha256 (`hash`). A client names a question and an option, never content
  or a result, and must send the hash it was shown.
- **Answers are final and in order.** The same response sent again is the same success, so a
  retry after a lost reply records nothing twice. A different response to an answered question,
  or a response to a question ahead of the waiting one, is refused.
- **Stored on the message** (`messages.metadata.assessments`); the reply's text never changes.
  Only a `complete` reply can be answered: a regenerated (superseded) one is closed with its test.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = 1
MAX_QUESTIONS = 30
MAX_OPTIONS = 8
LETTERS = "ABCDEFGH"
LANGUAGES = ("quiz", "mcq")
SUMMARY_HEADING = "## Practice tests in this chat"
SUMMARY_MAX = 1200  # the whole block; the latest test comes first and is never cut
LATEST_MAX = 700

# A fence (``` or ~~~), after anything that can hold one: indentation, list markers, quote marks.
_FENCE = re.compile(r"^(?P<prefix>[ \t>]*(?:(?:[-+*]|\d{1,9}[.)])[ \t]+[ \t>]*)*)(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
_LETTER = re.compile(r"\(?([A-Ha-h])[).:]?")
_NUMBER_WORDS = {
    word: value
    for value, word in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
        "sixteen seventeen eighteen nineteen twenty".split()
    )
}
_COUNT = r"\b(\d{1,3}|" + "|".join(_NUMBER_WORDS) + r")[\s-]+(?:(?:more|new|different|practice)\s+)?"
_ASKED_MCQS = re.compile(_COUNT + r"(?:mcqs?|multiple[\s-]*choice)\b", re.I)
_ASKED_QUESTIONS = re.compile(_COUNT + r"(?:questions?|qs)\b", re.I)
# "questions" counts only in a request for a test; "explain these 2 questions" asks for none.
_TEST_WORDS = re.compile(r"\b(?:quiz|test|mcqs?|practi[cs]e|exam|revis(?:e|ion)|ask me|give me|one by one)\b", re.I)
# A number right after these is a class, a chapter or a page, not how many questions.
_NOT_A_COUNT = {
    "class", "grade", "std", "standard", "chapter", "ch", "unit", "lesson", "page", "pg", "exercise", "ex",
    "level", "part", "section", "sec", "year", "sem", "semester", "term", "paper", "no", "number", "question",
    "q", "set", "module", "week", "day", "topic",
}  # fmt: skip
_CLAIMED = re.compile(r"\bquestion\s+1\s+(?:of|/)\s+(\d{1,3})\b|\b(\d{1,3})[\s-]+question\s+(?:quiz|test)\b", re.I)


class Refused(Exception):
    """The response conflicts with the test as it is (409). `reason` is stable, for logs and clients."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Invalid(Exception):
    """No such question or option in this test (422)."""


@dataclass(frozen=True)
class _Block:
    language: str
    body: str
    closed: bool
    top_level: bool


# ------------------------------------------------------------------ reading a reply
def _blocks(content: str) -> tuple[list[_Block], list[str]]:
    """The reply's fenced blocks, and its lines outside them. Fences are read as CommonMark does
    for a fence that starts a line (at most 3 spaces in; the body loses up to as many); one in a
    list item or a quote is still found, so it is never mistaken for prose."""
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[_Block] = []
    prose: list[str] = []
    index = 0
    while index < len(lines):
        match = _FENCE.match(lines[index])
        if match is None or (match["fence"][0] == "`" and "`" in match["info"]):
            prose.append(lines[index])
            index += 1
            continue
        prefix, fence = match["prefix"], match["fence"]
        top_level = prefix == " " * len(prefix) and len(prefix) <= 3
        close = re.compile(rf"^[ \t>]*{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$")
        body: list[str] = []
        index += 1
        while index < len(lines) and not close.match(lines[index]):
            line = lines[index]
            body.append(line[min(len(prefix), len(line) - len(line.lstrip(" "))) :] if top_level else line)
            index += 1
        info = match["info"].strip()
        blocks.append(_Block(info.split()[0] if info else "", "\n".join(body), index < len(lines), top_level))
        index += 1  # the closing fence
    return blocks, prose


_TEST_FENCE = re.compile(r"(?:`{3,}|~{3,})[ \t]*(?:quiz|mcq)(?=\s|$)", re.M)


def has_test(content: str) -> bool:
    """Whether a reply may hold a test (a fence named quiz or mcq somewhere); `build` decides."""
    return _TEST_FENCE.search(content) is not None


def _trim(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip(" \t\n")


def locator(body: str) -> str:
    """Which block of the reply a test is: sha256 of its fence's body, trimmed. The web app
    computes the same from the block it draws, to put the record on the right card."""
    return hashlib.sha256(_trim(body).encode("utf-8")).hexdigest()


def fingerprint(record: dict) -> str:
    """sha256 of the test's canonical JSON: what a response must name to be accepted."""
    canonical = {"kind": record["kind"], "title": record.get("title"), "questions": record["questions"]}
    text = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _text(value: Any, limit: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit and "\x00" not in value


def _correct(answer: Any, options: list[str]) -> int | None:
    """The one option the answer names: a 0-based number, a letter ("B") or the option's own
    text. An answer that could mean two options means none."""
    if isinstance(answer, bool):
        return None
    if isinstance(answer, int):
        return answer if 0 <= answer < len(options) else None
    if not isinstance(answer, str) or len(answer) > 400:
        return None
    text = answer.strip().casefold()
    found = {index for index, option in enumerate(options) if option.strip().casefold() == text}
    letter = _LETTER.fullmatch(answer.strip())
    if letter and LETTERS.index(letter[1].upper()) < len(options):
        found.add(LETTERS.index(letter[1].upper()))
    return found.pop() if len(found) == 1 else None


def _question(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    text, options, explanation = raw.get("question"), raw.get("options"), raw.get("explanation")
    if not _text(text, 1000) or not isinstance(options, list) or not 2 <= len(options) <= MAX_OPTIONS:
        return None
    if not all(_text(option, 400) for option in options):
        return None
    if len({option.strip().casefold() for option in options}) != len(options):
        return None
    if explanation is not None and not (isinstance(explanation, str) and len(explanation) <= 2000):
        return None
    correct = _correct(raw.get("answer"), options)
    if correct is None or (explanation and "\x00" in explanation):
        return None
    return {
        "kind": "mcq",
        "text": text,
        "options": list(options),
        "correct": correct,
        "explanation": explanation if explanation and explanation.strip() else None,
    }


def asked_count(question: str | None) -> int | None:
    """How many questions the student asked for ("10 MCQs", "give me five questions"), at most
    MAX_QUESTIONS; None when the message names no count ("class 10 questions" names a class)."""
    text = question or ""
    patterns = [_ASKED_MCQS] + ([_ASKED_QUESTIONS] if _TEST_WORDS.search(text) else [])
    for pattern in patterns:
        for match in pattern.finditer(text):
            before = re.search(r"([A-Za-z]+)\W*$", text[: match.start()])
            if before and before[1].lower() in _NOT_A_COUNT:
                continue
            raw = match[1].lower()
            count = int(raw) if raw.isdigit() else _NUMBER_WORDS[raw]
            if count > 0:
                return min(count, MAX_QUESTIONS)
    return None


def _claimed_count(prose: list[str]) -> int | None:
    match = _CLAIMED.search("\n".join(prose))
    return int(match[1] or match[2]) if match else None


def build(content: str, question: str | None) -> tuple[list[dict] | None, str | None]:
    """The reply's test records, or why it has none: (records, None), (None, code), or (None, None)
    for a reply without a test. `question` is the student's message the reply answers."""
    blocks, prose = _blocks(content)
    tests = [block for block in blocks if block.language in LANGUAGES]
    if not tests:
        return None, None
    if len(tests) > 1:
        return None, "multiple_tests"
    test = tests[0]
    if not test.top_level:
        return None, "nested_test"
    if not test.closed:
        return None, "incomplete_test"
    try:
        spec = json.loads(test.body)
    except ValueError:
        return None, "invalid_json"
    title = None
    if test.language == "mcq":
        raw_questions: Any = [spec]
    elif isinstance(spec, dict) and isinstance(spec.get("questions"), list):
        raw_questions, title = spec["questions"], spec.get("title")
        if title is not None and not (isinstance(title, str) and len(title) <= 200 and "\x00" not in title):
            return None, "invalid_test"
    else:
        return None, "invalid_test"
    if not raw_questions:
        return None, "invalid_test"
    if len(raw_questions) > MAX_QUESTIONS:
        return None, "too_many_questions"
    questions = [_question(raw) for raw in raw_questions]
    if any(item is None for item in questions):
        return None, "invalid_question"
    total = len(questions)
    for expected in (asked_count(question), _claimed_count(prose)):
        if expected is not None and expected != total:
            return None, "count_mismatch"
    record = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "test",
        "position": 0,
        "title": title.strip() if title and title.strip() else None,
        "questions": questions,
        "total": total,
        "locator": locator(test.body),
        "responses": [],
    }
    record["hash"] = fingerprint(record)
    return [record], None


# ------------------------------------------------------------------ answering
def respond(
    record: dict, *, status: str, client_hash: str, question: int, action: str, value: int | None, at: str
) -> tuple[dict, bool]:
    """The record after this response, and whether it changed (False: the same response again).
    Raises Refused (409) or Invalid (422); never trusts anything but the question and option named."""
    if record.get("schemaVersion") != SCHEMA_VERSION:
        raise Refused("unsupported")
    if status != "complete":
        raise Refused("closed")
    if fingerprint(record) != record.get("hash"):
        raise Refused("corrupt")
    if client_hash != record["hash"]:
        raise Refused("changed")
    questions = record["questions"]
    if question >= len(questions):
        raise Invalid("question")
    if action == "answer" and (value is None or value >= len(questions[question]["options"])):
        raise Invalid("value")
    wanted = "answered" if action == "answer" else "skipped"
    value = value if action == "answer" else None
    for response in record["responses"]:
        if response["question"] == question:
            if response["status"] == wanted and response["value"] == value:
                return record, False
            raise Refused("answered")
    if question != len(record["responses"]):
        raise Refused("out_of_order")
    earned = 1 if wanted == "answered" and value == questions[question]["correct"] else 0
    response = {"question": question, "status": wanted, "value": value, "earned": earned, "possible": 1, "at": at}
    return {**record, "responses": [*record["responses"], response]}, True


def state_of(record: dict) -> str:
    answered = len(record["responses"])
    return "completed" if answered >= record["total"] else "active" if answered else "not_started"


def public(record: dict, message_id: Any, status: str) -> dict | None:
    """What a client may show: the questions, and the right answer and explanation only of those
    already answered or skipped. None for a record this code cannot read."""
    if record.get("schemaVersion") != SCHEMA_VERSION:
        return None
    responses = {response["question"]: response for response in record["responses"]}
    questions = []
    for index, question in enumerate(record["questions"]):
        response = responses.get(index)
        questions.append(
            {
                "kind": question["kind"],
                "text": question["text"],
                "options": question["options"],
                "response": None
                if response is None
                else {key: response[key] for key in ("status", "value", "earned", "possible", "at")},
                "correct": question["correct"] if response is not None else None,
                "explanation": question.get("explanation") if response is not None else None,
            }
        )
    answered = len(record["responses"])
    state = state_of(record)
    return {
        "id": f"{message_id}:{record['position']}",
        "position": record["position"],
        "schemaVersion": SCHEMA_VERSION,
        "kind": record["kind"],
        "title": record.get("title"),
        "hash": record["hash"],
        "locator": record["locator"],
        "state": state,
        "answerable": status == "complete" and state != "completed",
        "total": record["total"],
        "answered": answered,
        "current": answered if answered < record["total"] else None,
        "earned": sum(response["earned"] for response in record["responses"]),
        "possible": len(record["questions"]),  # every multiple-choice question is worth 1
        "questions": questions,
    }


# ------------------------------------------------------------------ what the tutor is told
def _quote(text: str, limit: int) -> str:
    """Model-written text on one line, in quotes it cannot close, at most `limit` characters."""
    flat = " ".join(str(text).split()).replace('"', "'")
    return f'"{flat if len(flat) <= limit else flat[: limit - 1] + "…"}"'


def _mark(response: dict, questions: list[dict]) -> str:
    number, right = response["question"] + 1, LETTERS[questions[response["question"]]["correct"]]
    if response["status"] == "skipped":
        return f"Q{number} skipped (answer {right})"
    chosen = LETTERS[response["value"]]
    return f"Q{number} {chosen} right" if response["earned"] else f"Q{number} {chosen} wrong (answer {right})"


def _latest(record: dict) -> str:
    questions, responses, total = record["questions"], record["responses"], record["total"]
    answered, correct = len(responses), sum(response["earned"] for response in responses)
    skipped = sum(1 for response in responses if response["status"] == "skipped")
    lines = []
    if answered >= total:
        lines.append(
            f"- Latest test: finished, {correct} of {total} correct" + (f", {skipped} skipped." if skipped else ".")
        )
    else:
        lines.append(
            f"- Latest test: question {answered + 1} of {total} is waiting; {correct} of {answered} answered correctly."
            if answered
            else f"- Latest test: {total} questions, none answered yet; question 1 is waiting."
        )
        lines.append(f"- Waiting: Q{answered + 1} {_quote(questions[answered]['text'], 100)}")
    marks = [_mark(response, questions) for response in responses]
    while marks and len("; ".join(marks)) > 180:
        marks = marks[1:]
    if marks:
        lines.append("- Answers: " + ("…; " if len(marks) < answered else "") + "; ".join(marks))
    if responses and questions[responses[-1]["question"]].get("explanation"):
        last = responses[-1]["question"]
        lines.append(f"- Why Q{last + 1}: {_quote(questions[last]['explanation'], 100)}")
    lines.append(
        "- The app's record, authoritative: the student answers in the test card, one question at a time. "
        "Never rewrite, re-ask or re-grade this test."
        # A new block would become the test that a typed letter or "next" reaches.
        + ("" if answered >= total else " Until it is finished, write no other mcq or quiz block unless asked.")
    )
    return "\n".join(lines)


def _earlier(record: dict) -> str:
    answered = len(record["responses"])
    correct = sum(response["earned"] for response in record["responses"])
    if answered >= record["total"]:
        return f"- Earlier test: {record['total']} questions, finished, {correct} correct."
    return f"- Earlier test: {record['total']} questions, {answered} answered, {correct} correct; unfinished."


def tutor_summary(newest_first: list[dict]) -> str:
    """The chat's practice tests for the system prompt, newest first: the latest one whole (at most
    LATEST_MAX characters by construction), then earlier ones while the block stays within
    SUMMARY_MAX. Empty when the chat has none, so the prompt is unchanged."""
    records = [record for record in newest_first if record.get("schemaVersion") == SCHEMA_VERSION]
    if not records:
        return ""
    text = f"{SUMMARY_HEADING}\n{_latest(records[0])}"
    for record in records[1:]:
        line = _earlier(record)
        if len(text) + 1 + len(line) > SUMMARY_MAX:
            break
        text += f"\n{line}"
    return text
