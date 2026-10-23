"""Practice tests and exercises: what the tutor writes into a reply for the student to answer,
graded and recorded by the server (docs/api-contract.md, "Practice tests").

- **Built with the reply, all or nothing.** `build` runs when the reply is saved
  (ChatService._finalize), in the same UPDATE. A reply holds at most one practice block: a test
  (one ```quiz block, or one ```mcq for a single question) or an exercise (one ```fill-blank). The
  whole block is checked first: every question, its options and its answer (for a test, also the
  number of questions the student asked for), every blank and its accepted answers. Anything
  wrong keeps nothing (the reason is `assessmentError`), never part of it. There is no retry
  behind the student's back: Regenerate is the retry.
- **The tutor is told the record** (`tutor_summary`), latest first, in words a model reads as
  fact: what was answered, the score, what to do when asked. A model that is only given the
  score tends to believe the transcript instead, where no answer appears (scripts/eval_tutor_record.py
  measures this against the configured model).
- **Questions and grading come only from the saved reply.** The record keeps the test's
  canonical form and its sha256 (`hash`). A client names a question and an option, never content
  or a result, and must send the hash it was shown.
- **Answers are final and in order.** The same response sent again is the same success, so a
  retry after a lost reply records nothing twice. A different response to an answered question,
  or a response to a question ahead of the waiting one, is refused.
- **A question-bank test may grow** (`adaptive`, app/qbank/chat_tests.py): it starts with one
  question, and each response adds the next one (`extend`), chosen from it. Its `total` is fixed
  when it is set, unless the bank runs out (then it ends with the questions it has). A response
  names the hash of the questions it was shown, so a retry after a lost reply is still the same
  success.
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
MAX_BLANKS = 20
LETTERS = "ABCDEFGH"
LANGUAGES = ("quiz", "mcq", "fill-blank")  # the practice blocks the app records
SUMMARY_HEADING = "## Practice tests in this chat"
SUMMARY_FRAME = (
    "The app records the student's answers to the tests and exercises you write (they are not in the "
    "chat transcript). This record is authoritative."
)
USE_RECORD = (
    "- When the student asks how they did, answer from this record: the score, what they got right and "
    "wrong, and the ideas behind the wrong answers. Never say you cannot see their answers."
)
NOT_ANSWERED = (
    "- There is no score yet: the student has not checked a single blank. If they ask how they did, say "
    "they haven't answered it yet and invite them to fill in the blanks and press Check answers. Never "
    "state, guess or imply a score, or which blanks are right or wrong."
)
# A fill-blank block's answers, as the model wrote them: `[[answer]]` or `[[answer|alternative]]`.
_ANSWER_KEY = re.compile(r"\[\[[^\[\]]*\]\]")
_FILL_FENCE = re.compile(r"(^|\n)([ \t]*)(`{3,}|~{3,})[ \t]*fill-blank\b[^\n]*\n.*?\n[ \t]*\3[ \t]*(?=\n|$)", re.S)


def for_model(content: str) -> str:
    """A reply as the tutor is shown it in the chat history: each fill-in-the-blanks exercise with its
    answers replaced by blanks. The record (tutor_summary) is the only place the tutor reads results and
    right answers from, so the exercise's own answer key can never be mistaken for the student's answers."""
    if "fill-blank" not in content:
        return content
    return _FILL_FENCE.sub(lambda match: _ANSWER_KEY.sub("____", match.group(0)), content)


SUMMARY_MAX = 2600  # the whole block; the latest record comes first and is never cut
LATEST_MAX = 2100
MISSED_SHOWN = 5  # missed questions told with their wording

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
# A blank in a fill-blank exercise, as the web app reads it: [[answer|alternative]]. A longer one is a
# malformed key (the exercise is refused whole), never left in the text.
_BLANK = re.compile(r"\[\[([^\]\n]{1,80})\]\]")
_LONG_BLANK = re.compile(r"\[\[[^\]\n]{81,}\]\]")


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


_TEST_FENCE = re.compile(r"(?:`{3,}|~{3,})[ \t]*(?:quiz|mcq|fill-blank)(?=\s|$)", re.M)


def has_test(content: str) -> bool:
    """Whether a reply may hold a practice block (a fence named quiz, mcq or fill-blank); `build` decides."""
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


def _fill_blank(spec: Any) -> dict | None:
    """A fill-in-the-blanks exercise, read the way the web app reads it: blanks `[[answer|alternative]]`
    of 1-80 characters, 1-20 of them, every alternative an accepted answer (none empty). The key is the
    tutor's: anything malformed refuses the exercise whole."""
    if not isinstance(spec, dict):
        return None
    text, explanation = spec.get("text"), spec.get("explanation")
    if not _text(text, 3000) or _LONG_BLANK.search(text):
        return None
    if explanation is not None and not (
        isinstance(explanation, str) and len(explanation) <= 2000 and "\x00" not in explanation
    ):
        return None
    segments: list[str] = []
    answers: list[list[str]] = []
    last = 0
    for match in _BLANK.finditer(text):
        accepted = [answer.strip() for answer in match[1].split("|")]
        if not all(accepted):  # an empty alternative, e.g. [[a|]]
            return None
        segments.append(text[last : match.start()])
        answers.append(accepted)
        last = match.end()
    segments.append(text[last:])
    if not 1 <= len(answers) <= MAX_BLANKS:
        return None
    return {
        "kind": "fill_blank",
        "segments": segments,
        "answers": answers,
        "explanation": explanation if explanation and explanation.strip() else None,
    }


def _same(given: str, expected: str) -> bool:
    """The web app's rule (widgets/fill-blank.tsx): ignoring case, spacing and trailing `.;,!`."""

    def norm(value: str) -> str:
        return re.sub(r"[.;,!]+$", "", re.sub(r"\s+", " ", value.strip().lower()))

    return norm(given) == norm(expected)


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
    if test.language == "fill-blank":
        exercise = _fill_blank(spec)
        if exercise is None:
            return None, "invalid_question"
        record = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "exercise",
            "position": 0,
            "title": None,
            "questions": [exercise],
            "total": 1,
            "locator": locator(test.body),
            "responses": [],
        }
        record["hash"] = fingerprint(record)
        return [record], None
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


def records_for(metadata: dict | None, content: str, status: str) -> list[dict]:
    """A reply's practice records: the stored ones; or, for a complete reply saved before its kind
    of block was recorded (no record and no `assessmentError`), the record its text gives now. That
    is built the same way on every read, so what a client is shown and its first answer agree; the
    first answer stores it (app/chat/router.py). A block the server can't accept stays read-only."""
    stored = (metadata or {}).get("assessments")
    if stored:
        return stored
    if status != "complete" or (metadata or {}).get("assessmentError") or not has_test(content):
        return []
    try:
        records, _ = build(content, None)
    except Exception:  # noqa: BLE001 - a reply is never unreadable because of its practice block
        return []
    return records or []


# ------------------------------------------------------------------ answering
def _possible(question: dict) -> int:
    """What a question is worth: 1 for multiple choice, one per blank for an exercise."""
    return len(question["answers"]) if question["kind"] == "fill_blank" else 1


def _answer(question: dict, value: Any) -> int | list[str]:
    """The response's value, if it fits the question: an option's index, or one text per blank."""
    if question["kind"] == "fill_blank":
        if (
            isinstance(value, list)
            and len(value) == len(question["answers"])
            and all(isinstance(given, str) and len(given) <= 200 and "\x00" not in given for given in value)
        ):
            return list(value)
    elif isinstance(value, int) and not isinstance(value, bool) and 0 <= value < len(question["options"]):
        return value
    raise Invalid("value")


def _graded(question: dict, index: int, wanted: str, value: Any, at: str) -> dict:
    response = {"question": index, "status": wanted, "value": value, "possible": _possible(question), "at": at}
    if question["kind"] == "fill_blank":
        accepted = question["answers"]
        marks = (
            [any(_same(given, answer) for answer in answers) for given, answers in zip(value, accepted, strict=True)]
            if wanted == "answered"
            else [False] * len(accepted)
        )
        return {**response, "earned": sum(marks), "marks": marks}
    return {**response, "earned": 1 if wanted == "answered" and value == question["correct"] else 0}


def respond(
    record: dict, *, status: str, client_hash: str, question: int, action: str, value: Any, at: str
) -> tuple[dict, bool]:
    """The record after this response, and whether it changed (False: the same response again).
    Raises Refused (409) or Invalid (422); never trusts anything but the question and answer named."""
    if record.get("schemaVersion") != SCHEMA_VERSION:
        raise Refused("unsupported")
    if status != "complete":
        raise Refused("closed")
    if fingerprint(record) != record.get("hash"):
        raise Refused("corrupt")
    questions = record["questions"]
    seen = record["hash"]
    if record.get("adaptive") and question < len(questions):  # a growing test: the questions up to this one
        seen = fingerprint({**record, "questions": questions[: question + 1]})
    if client_hash not in (seen, record["hash"]):
        raise Refused("changed")
    if question >= len(questions):
        if record.get("adaptive") and question < record["total"]:
            raise Refused("out_of_order")  # a growing test's later questions are not chosen yet
        raise Invalid("question")
    wanted = "answered" if action == "answer" else "skipped"
    value = _answer(questions[question], value) if action == "answer" else None
    for response in record["responses"]:
        if response["question"] == question:
            if response["status"] == wanted and response["value"] == value:
                return record, False
            raise Refused("answered")
    if question != len(record["responses"]):
        raise Refused("out_of_order")
    response = _graded(questions[question], question, wanted, value, at)
    return {**record, "responses": [*record["responses"], response]}, True


def extend(record: dict, raw: Any) -> dict:
    """A growing test with its next question (`raw`, a question in a ```quiz block's form), or, when
    there is none (the bank ran out), with its total cut to the questions it has. Never changes
    `record` itself."""
    question = _question(raw) if raw is not None else None
    if question is None:
        grown = {**record, "total": len(record["questions"])}
    else:
        grown = {**record, "questions": [*record["questions"], question]}
    return {**grown, "hash": fingerprint(grown)}


def state_of(record: dict) -> str:
    answered = len(record["responses"])
    return "completed" if answered >= record["total"] else "active" if answered else "not_started"


def public(record: dict, message_id: Any, status: str) -> dict | None:
    """What a client may show: the questions, and the right answers and explanation only of those
    already answered or skipped. Every question has every field (null where it does not apply), so a
    reply's metadata and the response endpoint give the same shape. None for a record this code
    cannot read."""
    if record.get("schemaVersion") != SCHEMA_VERSION:
        return None
    responses = {response["question"]: response for response in record["responses"]}
    questions = []
    for index, question in enumerate(record["questions"]):
        response = responses.get(index)
        blank = question["kind"] == "fill_blank"
        questions.append(
            {
                "kind": question["kind"],
                "text": None if blank else question["text"],
                "options": None if blank else question["options"],
                "segments": question["segments"] if blank else None,
                "blanks": len(question["answers"]) if blank else None,
                "response": None
                if response is None
                else {
                    **{key: response[key] for key in ("status", "value", "earned", "possible", "at")},
                    "marks": response.get("marks"),
                },
                "correct": None if blank or response is None else question["correct"],
                "answers": question["answers"] if blank and response is not None else None,
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
        "possible": sum(_possible(question) for question in record["questions"]),
        "questions": questions,
    }


# ------------------------------------------------------------------ what the tutor is told
def _quote(text: str, limit: int) -> str:
    """Text on one line, in quotes it cannot close, at most `limit` characters. Student-typed text
    is only ever shown this way: information, never instructions (as in app/learning/tutor.py)."""
    flat = " ".join(str(text).split()).replace('"', "'")
    return f'"{flat if len(flat) <= limit else flat[: limit - 1] + "…"}"'


def _title(record: dict) -> str:
    return f" {_quote(record['title'], 80)}" if record.get("title") else ""


def _mark(response: dict, questions: list[dict]) -> str:
    number, right = response["question"] + 1, LETTERS[questions[response["question"]]["correct"]]
    if response["status"] == "skipped":
        return f"Q{number} skipped ({right})"
    chosen = LETTERS[response["value"]]
    return f"Q{number} {chosen} right" if response["earned"] else f"Q{number} {chosen} wrong ({right})"


def _test_lines(record: dict) -> list[str]:
    questions, responses, total = record["questions"], record["responses"], record["total"]
    answered, right = len(responses), sum(response["earned"] for response in responses)
    skipped = sum(1 for response in responses if response["status"] == "skipped")
    if answered >= total:
        wrong = answered - right - skipped
        state = f"FINISHED. Score {right} out of {total} ({right} right, {wrong} wrong, {skipped} skipped)."
    elif answered:
        state = f"IN PROGRESS, {answered} of {total} answered ({right} right); question {answered + 1} is waiting."
    else:
        state = f"NOT STARTED; question 1 of {total} is waiting."
    lines = [f"- Latest test{_title(record)}: {state}"]
    if responses:  # every answered question: the tutor is asked about any of them
        marks = "; ".join(_mark(response, questions) for response in responses)
        lines.append(f"- Answers (letter chosen; right answer in brackets): {marks}")
    # The wording of the latest missed questions, so "explain my mistakes" still works once a long
    # chat has pushed the test itself out of the transcript the tutor sees.
    missed = [response for response in responses if not response["earned"]][-MISSED_SHOWN:]
    if missed:
        details = []
        for response in missed:
            question = questions[response["question"]]
            chosen = (
                "skipped"
                if response["status"] == "skipped"
                else f"chose {_quote(question['options'][response['value']], 30)}"
            )
            right = _quote(question["options"][question["correct"]], 30)
            details.append(f"Q{response['question'] + 1} {_quote(question['text'], 80)}: {chosen}, right {right}")
        lines.append(f"- Missed questions (the latest {len(missed)}): {'; '.join(details)}")
    lines.append(USE_RECORD)
    if answered < total:
        # A new block would become the test that a typed letter or "next" reaches.
        lines.append(
            "- They answer in the test card, one question at a time; encourage them to finish it there. "
            "Until it is finished, write no other practice block unless asked."
        )
    lines.append("- Never rewrite, re-ask or re-grade this test.")
    return lines


def _exercise_lines(record: dict) -> list[str]:
    exercise = record["questions"][0]
    blanks = len(exercise["answers"])
    response = record["responses"][0] if record["responses"] else None
    if response is None:
        lines = [f"- Latest exercise (fill in the blanks, {blanks} blanks): NOT ANSWERED YET."]
    elif response["status"] == "skipped":
        lines = [f"- Latest exercise (fill in the blanks): SKIPPED (answers shown), 0 of {blanks} blanks right."]
    else:
        right = response["earned"]
        lines = [
            f"- Latest exercise (fill in the blanks): CHECKED. Score {right} out of {blanks} blanks "
            f"({right} right, {blanks - right} wrong)."
        ]
    # Its text with the blanks numbered, for when a long chat has pushed it out of the transcript.
    text = "".join(
        segment + (f"__{number}__" if number <= blanks else "")
        for number, segment in enumerate(exercise["segments"], start=1)
    )
    lines.append(f"- Text: {_quote(text, 200)}")
    if response is not None and response["status"] != "skipped":
        # Every blank, with what they typed: the exercise's own answers are in the transcript too,
        # and a model told only the wrong ones may read those as the student's.
        typed = [
            f"{number} {_quote(given, 16)} " + ("right" if mark else f"wrong ({_quote(accepted[0], 16)})")
            for number, (given, mark, accepted) in enumerate(
                zip(response["value"], response["marks"], exercise["answers"], strict=True), start=1
            )
        ]
        lines.append(f"- Blanks (what they typed; right answer in brackets): {'; '.join(typed)}")
    if response is None:
        # Nothing is graded yet, so there is no score to tell: USE_RECORD would ask for one.
        lines.append(NOT_ANSWERED)
        lines.append("- They type into the blanks in the exercise card and press Check answers.")
    else:
        lines.append(USE_RECORD)
    lines.append("- Never rewrite or re-grade this exercise.")
    return lines


def _latest(record: dict) -> str:
    return "\n".join(_exercise_lines(record) if record["kind"] == "exercise" else _test_lines(record))


def _earlier(record: dict) -> str:
    answered, total = len(record["responses"]), record["total"]
    right = sum(response["earned"] for response in record["responses"])
    if record["kind"] == "exercise":
        blanks = len(record["questions"][0]["answers"])
        if not answered:
            return f"- Earlier exercise (fill in the blanks): NOT ANSWERED ({blanks} blanks)."
        return f"- Earlier exercise (fill in the blanks): {right} of {blanks} blanks right."
    if answered >= total:
        return f"- Earlier test{_title(record)}: FINISHED, score {right} out of {total}."
    if answered:
        return f"- Earlier test{_title(record)}: IN PROGRESS, {answered} of {total} answered ({right} right)."
    return f"- Earlier test{_title(record)}: NOT STARTED ({total} questions)."


def tutor_summary(newest_first: list[dict]) -> str:
    """The chat's practice tests and exercises for the system prompt, newest first: the latest one
    whole (at most LATEST_MAX characters by construction), then earlier ones while the block stays
    within SUMMARY_MAX. Empty when the chat has none, so the prompt is unchanged."""
    records = [record for record in newest_first if record.get("schemaVersion") == SCHEMA_VERSION]
    if not records:
        return ""
    text = f"{SUMMARY_HEADING}\n{SUMMARY_FRAME}\n{_latest(records[0])}"
    for record in records[1:]:
        line = _earlier(record)
        if len(text) + 1 + len(line) > SUMMARY_MAX:
            break
        text += f"\n{line}"
    return text
