"""Practice tests in the chat come from the question bank, never from the model.

The tutor is taught one block for tests (app/chat/assistant.py BANK_BLOCKS): ```question-bank with a
chapter id from the list it is given on a turn that asks for a test (`menu`). Before the reply is
saved, `fill` replaces that block with a ```quiz block of stored questions and removes any practice
block the model wrote itself. The quiz is then recorded, answered and graded like every chat test
(app/assessments/state.py, app/chat/service.py), so no model call checks or scores anything.

Choosing the questions is SQL alone, on ix_qb_questions_select: the chapter's servable questions
(selection.SERVABLE), in an order seeded by the reply's id. The same reply always holds the same
questions, a regenerated one others, and no question appears twice in a test.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

FENCE = "question-bank"
MODEL_FENCES = ("quiz", "mcq", "fill-blank")  # practice blocks the model may no longer write
LANGUAGE_SUBJECTS = ("english", "hindi", "sanskrit")  # taught in their own language, whatever the medium
MAX_COUNT = 30  # app/assessments/state.py MAX_QUESTIONS
DEFAULT_COUNT = 10
LEVELS = {"easy": 1, "medium": 2, "hard": 3}

NOTE_UNKNOWN = (
    "_No test was set: that chapter is not in the question bank. Tell me the class, subject and chapter, "
    "and I'll set one._"
)
NOTE_EMPTY = "_No test was set: there are no stored questions for that yet._"
NOTE_MODEL = "_Practice questions come only from the question bank: ask for a test on a chapter._"
NOTE_FEWER = "_Only {n} stored questions match this, so the test has {n}._"

# A message that may ask for a test: then (only) the tutor is given the chapter list. "question" alone
# is not one ("I have a question"); "5 questions", "questions on light" and "ask me" are.
_TEST_REQUEST = re.compile(
    r"\b(?:quiz\w*|tests?|mcqs?|multiple[\s-]*choice|practi[cs]e|exam\w*|revis(?:e|ion)|ask me)\b"
    r"|\b(?:\d{1,2}|a few|some|more|few)\s+(?:\w+\s+)?questions\b|\bquestions\s+(?:on|from|for|about)\b"
    r"|\d{1,2}\s*(?:प्रश्न|सवाल)|टेस्ट|परीक्षा|अभ्यास|क्विज",
    re.I,
)
_CLASS = re.compile(r"\b(?:class|grade|std\.?|standard)\s*(\d{1,2})\b|कक्षा\s*(\d{1,2})", re.I)
CHAPTER_ID = re.compile(r"[A-Z]{3,6}\d-CH\d{2}")  # qb_chapters ids, e.g. JESC1-CH09
# A request the model fenced as JSON (or with no language), or wrote inline: ::question-bank{...}
# (the ::file directive's form) or a bare {"chapter": ...}. Read as a request only when it names
# a chapter id; anything else stays as it was.
LOOSE_FENCES = ("json", "jsonc", "")
_INLINE = re.compile(r"(?:::)?question-bank\s*(?=\{)|(?=\{\s*\"chapter\"\s*:)")
_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*([^\s`]*)[^`]*$")  # any fence; its language is the first word
_WORD = re.compile(r"\w{3,}")

MENU = text(
    """
    SELECT b.title AS book, b.language, c.chapter_id, c.chapter_number, c.title
    FROM qb_chapters c
    JOIN qb_books b ON b.book_id = c.book_id
    WHERE b.class_level = :class_level
      AND (b.language = :language OR b.subject_code IN ('english', 'hindi', 'sanskrit'))
      AND EXISTS (
          SELECT 1 FROM qb_questions q
          WHERE q.language = b.language AND q.class_level = b.class_level AND q.subject_code = b.subject_code
            AND q.chapter_id = c.chapter_id AND q.review_status IN ('approved', 'needs_review') AND q.is_active
      )
    ORDER BY b.subject_code, b.title, c.chapter_number
    """
)

CHAPTER = text(
    """
    SELECT c.chapter_id, c.chapter_number, c.title, b.title AS book, b.language, b.class_level, b.subject_code
    FROM qb_chapters c JOIN qb_books b ON b.book_id = c.book_id
    WHERE c.chapter_id = :chapter_id
    """
)

TOPICS = text(
    "SELECT topic_id, topic_number, title FROM qb_topics WHERE chapter_id = :chapter_id ORDER BY topic_number"
)

# The quiz card's limits (app/assessments/state.py _question) leave out the few longest case questions.
PICK = text(
    """
    SELECT q.question_id, q.difficulty, q.stem, q.option_a, q.option_b, q.option_c, q.option_d, q.correct_option,
           q.explanation, c.title AS case_title, c.body AS case_body
    FROM qb_questions q
    LEFT JOIN qb_cases c ON c.case_id = q.case_id
    WHERE q.language = :language AND q.class_level = :class_level AND q.subject_code = :subject_code
      AND q.chapter_id = :chapter_id
      AND (CAST(:topic_ids AS text[]) IS NULL OR q.topic_id = ANY(CAST(:topic_ids AS text[])))
      AND (CAST(:difficulty AS text) IS NULL OR q.difficulty = :difficulty)
      AND q.review_status IN ('approved', 'needs_review') AND q.is_active
      AND length(q.stem) + coalesce(length(c.title) + length(c.body) + 8, 0) <= 1000
      AND greatest(length(q.option_a), length(q.option_b), length(q.option_c), length(q.option_d)) <= 400
      AND length(q.explanation) <= 2000
    ORDER BY md5(CAST(:seed AS text) || q.question_id)
    LIMIT :n
    """
)


@dataclass(frozen=True)
class BankTest:
    """A test the bank set in a reply: its ```quiz block's body, and where its questions came from."""

    body: str
    chapter_id: str
    topic_ids: tuple[str, ...]  # () = the whole chapter
    question_ids: tuple[str, ...]


def wants_test(message: str) -> bool:
    return _TEST_REQUEST.search(message or "") is not None


async def menu(session: AsyncSession, message: str, grade: str | None, medium: str | None, earlier: str = "") -> str:
    """The chapters the tutor may set a test on, when the student's message asks for one: the class
    the message names, else theirs, else the last one named earlier in the chat (`earlier`), in their
    medium, and the language subjects. "" otherwise."""
    if not wants_test(message):
        return ""
    named = _CLASS.search(message) or (None if grade else ([*_CLASS.finditer(earlier)] or [None])[-1])
    own = re.fullmatch(r"Class (\d{1,2})", grade or "")
    level = int(next(group for group in named.groups() if group)) if named else int(own[1]) if own else None
    if level is None or not 6 <= level <= 12:
        return (
            "Question bank: it has tests for Classes 6-12 (NCERT). The student's class is not known: "
            "ask which class and chapter before writing a question-bank block."
        )
    language = "hindi" if (medium or "").casefold() == "hindi" else "english"
    rows = (await session.execute(MENU, {"class_level": level, "language": language})).all()
    if not rows:
        return f"Question bank: there are no stored tests for Class {level} yet."
    lines = [f"Question bank, Class {level}: the chapters a question-bank block may name (chapter id, then title)."]
    book = None
    for row in rows:
        if row.book != book:
            book = row.book
            lines.append(f"{book} ({row.language}):")
        lines.append(f"{row.chapter_id} {row.chapter_number}. {row.title}")
    return "\n".join(lines)


async def _topics(session: AsyncSession, chapter_id: str, wanted: Any) -> list[Any]:
    """The chapter's topics the request names (one, or a list), each by number or by the most words
    in common; [] (the whole chapter) when it names none clearly."""
    names = wanted if isinstance(wanted, list) else [wanted]
    topics = (await session.execute(TOPICS, {"chapter_id": chapter_id})).all()
    found = {topic.topic_id: topic for name in names[:10] if (topic := _topic(topics, name)) is not None}
    return sorted(found.values(), key=lambda topic: topic.topic_number)


def _topic(topics: list[Any], wanted: Any) -> Any:
    if wanted is None or isinstance(wanted, bool):
        return None
    if isinstance(wanted, int) or (isinstance(wanted, str) and wanted.strip().isdigit()):
        return next((topic for topic in topics if topic.topic_number == int(wanted)), None)
    if not isinstance(wanted, str):
        return None
    words = set(_WORD.findall(wanted.casefold()))
    scored = sorted(((len(words & set(_WORD.findall(t.title.casefold()))), t) for t in topics), key=lambda s: -s[0])
    if not scored or scored[0][0] == 0 or (len(scored) > 1 and scored[1][0] == scored[0][0]):
        return None
    return scored[0][1]


def _question(row: Any) -> dict:
    stem = row.stem if row.case_body is None else f"**{row.case_title}:** {row.case_body} ➜ {row.stem}"
    return {
        "question": stem,
        "options": [row.option_a, row.option_b, row.option_c, row.option_d],
        "answer": row.correct_option,
        "explanation": row.explanation,
    }


def _request(spec: Any) -> dict | None:
    """A question-bank request: a JSON object naming a chapter id."""
    chapter = spec.get("chapter") if isinstance(spec, dict) else None
    return spec if isinstance(chapter, str) and CHAPTER_ID.fullmatch(chapter.strip()) else None


def _parse(body: str) -> dict | None:
    try:
        return _request(json.loads(body))
    except ValueError:
        return None


async def _set(session: AsyncSession, spec: dict | None, seed: str) -> tuple[BankTest | None, str]:
    """The ```quiz block for one request, or a note saying why there is none."""
    if spec is None:
        return None, NOTE_UNKNOWN
    chapter = (await session.execute(CHAPTER, {"chapter_id": spec["chapter"].strip()})).one_or_none()
    if chapter is None:
        return None, NOTE_UNKNOWN
    topics = await _topics(session, chapter.chapter_id, spec.get("topics", spec.get("topic")))
    asked = spec.get("count")
    asked = asked if isinstance(asked, int) and not isinstance(asked, bool) and asked >= 1 else None
    count = min(asked, MAX_COUNT) if asked else DEFAULT_COUNT
    difficulty = spec.get("difficulty") if spec.get("difficulty") in LEVELS else None
    rows = (
        await session.execute(
            PICK,
            {
                "language": chapter.language,
                "class_level": chapter.class_level,
                "subject_code": chapter.subject_code,
                "chapter_id": chapter.chapter_id,
                "topic_ids": [topic.topic_id for topic in topics] or None,
                "difficulty": difficulty,
                "seed": seed,
                "n": count,
            },
        )
    ).all()
    if not rows:
        return None, NOTE_EMPTY
    rows = sorted(rows, key=lambda row: LEVELS[row.difficulty])  # easy first; the seeded order within a level
    named = " · ".join(topic.title for topic in topics)
    title = f"{chapter.book} · {chapter.chapter_number}. {chapter.title}" + (f" · {named}" if named else "")
    quiz = json.dumps(
        {"title": title[:200], "questions": [_question(row) for row in rows]}, ensure_ascii=False, separators=(",", ":")
    )
    test = BankTest(quiz, chapter.chapter_id, tuple(t.topic_id for t in topics), tuple(r.question_id for r in rows))
    fewer = f"\n\n{NOTE_FEWER.format(n=len(rows))}" if asked and len(rows) < asked else ""
    return test, f"```quiz\n{quiz}\n```{fewer}"


def _segments(content: str) -> list[tuple[str, str, str]]:
    """The reply in order as prose runs ("prose", "", text) and fenced blocks (language, body, raw).
    Every fence is read whole, whatever its language, so a closing fence is never taken for an opening one."""
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    segments: list[tuple[str, str, str]] = []
    prose: list[str] = []
    index = 0
    while index < len(lines):
        opened = _OPEN.match(lines[index])
        if opened is None:
            prose.append(lines[index])
            index += 1
            continue
        if prose:
            segments.append(("prose", "", "\n".join(prose)))
            prose = []
        fence = opened[1]
        close = re.compile(rf"^ {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$")
        end = index + 1
        while end < len(lines) and not close.match(lines[end]):
            end += 1
        segments.append((opened[2], "\n".join(lines[index + 1 : end]), "\n".join(lines[index : end + 1])))
        index = end + 1
    if prose:
        segments.append(("prose", "", "\n".join(prose)))
    return segments


async def fill(session: AsyncSession, content: str, seed: str) -> tuple[str, BankTest | None]:
    """The reply with its first test request set from the bank (a note when it can't be), later
    ones dropped, and every practice block the model wrote itself replaced by a note."""
    if not any(mark in content for mark in ("```", "~~~", FENCE, '"chapter"')):
        return content, None
    parts: list[str] = []
    test: BankTest | None = None
    asked = False
    for language, body, raw in _segments(content):
        if language == "prose":  # a request written inline, outside any fence
            pieces: list[str] = []
            position = 0
            for match in _INLINE.finditer(raw):
                if match.start() < position:
                    continue
                try:
                    spec, stop = json.JSONDecoder().raw_decode(raw, match.end())
                except ValueError:
                    continue
                if _request(spec) is None:
                    continue
                pieces.append(raw[position : match.start()])
                if not asked:
                    asked = True
                    test, block = await _set(session, spec, seed)
                    pieces.append(f"\n\n{block}\n\n")
                position = stop
            parts.append("".join([*pieces, raw[position:]]) if pieces else raw)
        elif language in MODEL_FENCES:
            parts.append(NOTE_MODEL)
        elif language == FENCE or (language in LOOSE_FENCES and _parse(body) is not None):
            if not asked:  # later requests are dropped: one test per reply
                asked = True
                test, block = await _set(session, _parse(body), seed)
                parts.append(block)
        else:
            parts.append(raw)  # an ordinary code block
    return "\n".join(parts), test
