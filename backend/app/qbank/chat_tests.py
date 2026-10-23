"""Practice tests in the chat come from the question bank, never from the model.

The tutor is taught one block for tests (app/chat/assistant.py BANK_BLOCKS): ```question-bank with a
chapter id (or up to three, for a mock test) from the list it is given on a turn that asks for a test
(`menu`). Before the reply is saved, `fill` replaces that block with a ```quiz block of stored
questions and removes any test block the model wrote itself (a fill-in-the-blanks exercise it writes
stays, in its fence even if the model left that out: app/assessments grades it, and it is never
practice evidence). The quiz is then recorded,
answered and graded like every chat test (app/assessments/state.py, app/chat/service.py), so no model
call checks or scores anything.

Every test is a practice set in the ledger (qb_sets mode `chat`, its request id the reply's id; one
qb_set_items row per question served), whose answers are the evidence app/progress/practice.py reads.
Choosing the questions is SQL alone (selection.pick_next): the servable questions of the named topics,
or of the whole chapters, picked from the student's previous answer. An adaptive test
(ADAPTIVE_CHAT_TESTS) shows its first question; app/chat/router.py records each answer in the ledger
and serves the next question in the transaction that records it (`answer`, `next_question`, `close`).
Otherwise every question is chosen when the test is set. The same reply always starts with the same
question, and no question appears twice in a test.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.qbank import selection

FENCE = "question-bank"
MODEL_FENCES = ("quiz", "mcq")  # test blocks the model may no longer write (fill-blank exercises it may)
LANGUAGE_SUBJECTS = ("english", "hindi", "sanskrit")  # taught in their own language, whatever the medium
MAX_COUNT = 30  # app/assessments/state.py MAX_QUESTIONS
MAX_CHAPTERS = 3  # a mock test's chapters, all of one class, subject and language
DEFAULT_COUNT = 10
LEVELS = {"easy": 1, "medium": 2, "hard": 3}

NOTE_UNKNOWN = (
    "_No test was set: that chapter is not in the question bank. Tell me the class, subject and chapter, "
    "and I'll set one._"
)
NOTE_EMPTY = "_No test was set: there are no stored questions for that yet._"
NOTE_MODEL = "_Practice questions come only from the question bank: ask for a test on a chapter._"
NOTE_EXERCISE = "_One practice block per reply: ask for the exercise again once the test is done._"
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
# (the ::file directive's form) or a bare {"chapter": ...} or {"chapters": [...]}. Read as a request
# only when it names chapter ids; anything else stays as it was.
LOOSE_FENCES = ("json", "jsonc", "")
_INLINE = re.compile(r"(?:::)?question-bank\s*(?=\{)|(?=\{\s*\"chapters?\"\s*:)")
# A fill-in-the-blanks exercise the model wrote without its fence: {"text": "... [[answer]] ...",
# "explanation": "..."} bare in the text, as a ::: card (`:::fill-blank`, the study cards' form; most of
# them on 2026-10-23), or in a block with another language (json, none, a misspelt one). Put in its
# fence, or the student would read the answer key instead of an exercise to answer.
_BARE_EXERCISE = re.compile(r"\{\s*\"text\"\s*:")
_CARD_OPEN = re.compile(r"(?:^|\n)[ \t]*:{3,}[ \t]*[\w-]*(?:fill|blank)[\w-]*(?:\[[^\]\n]*\]|\{[^}\n]*\})*\s*$", re.I)
_CARD_CLOSE = re.compile(r"\s*\n[ \t]*:{3,}[ \t]*(?=\n|$)")
EXERCISE_KEYS = {"title", "text", "explanation"}
# Or with no JSON at all: a ::: card whose own text has the [[blanks]] (`:::steps[...]`, `:::fill-blank`;
# a third of the Hindi exercises on 2026-10-23). That text is the exercise.
_CARD_START = re.compile(r"^[ \t]*:{3,}[ \t]*[\w-]+(?:\[(?P<title>[^\]\n]*)\])?")
_CARD_END = re.compile(r"^[ \t]*:{3,}[ \t]*$")
_BOLD_BLANK = re.compile(r"\*\*(\[\[[^\]\n]+\]\])\*\*")
# Or as a leaf directive, the ::file{ref=F1} form: ::fill-blank{text="... [[answer]] ..." explanation="..."}.
_DIRECTIVE = re.compile(r"^[ \t]*::[\w-]*(?:fill|blank)[\w-]*\{(?P<attrs>.*?\")\s*\}[ \t]*$", re.I | re.M | re.S)
_ATTRIBUTE = re.compile(r"(\w+)\s*=\s*\"((?:[^\"\\]|\\.)*)\"")
# Or in its block but not strict JSON: line breaks inside its strings, or `text: ...` lines.
_KEY_LINE = re.compile(r"^\s*\"?(text|explanation)\"?\s*:\s*(.+?)\s*,?\s*$", re.M)
# Any fence, as app/assessments/state.py finds them: after indentation, list markers or quote marks;
# its language is the first word of its info.
_OPEN = re.compile(
    r"^(?P<prefix>[ \t>]*(?:(?:[-+*]|\d{1,9}[.)])[ \t]+[ \t>]*)*)(?P<fence>`{3,}|~{3,})[ \t]*(?P<info>[^\s`]*)[^`]*$"
)
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

# The ledger (0015, 0017): a test in the chat is a practice set of the reply (its request id); its
# questions are served as items and answered once, graded by the database (qb_set_items_answer).
NEW_SET = text(
    """
    INSERT INTO qb_sets (user_id, request_id, mode, filters, requested, served)
    VALUES (:user_id, :request_id, 'chat', CAST(:filters AS jsonb), :requested, :served)
    RETURNING id
    """
)
SERVE = text(
    "INSERT INTO qb_set_items (set_id, position, user_id, question_id, topic_id) "
    "VALUES (:set_id, :position, :user_id, :question_id, :topic_id)"
)
SERVED = text("UPDATE qb_sets SET served = :served, requested = :requested WHERE id = :set_id AND user_id = :user_id")
CHAT_SET = text(
    "SELECT request_id, filters, requested FROM qb_sets WHERE id = :set_id AND user_id = :user_id AND mode = 'chat'"
)
ANSWER = text(
    """
    UPDATE qb_set_items SET chosen = :chosen
    WHERE set_id = :set_id AND position = :position AND user_id = :user_id AND answered_at IS NULL
    RETURNING answered_at, is_correct
    """
)
CLOSE = text(
    """
    UPDATE qb_sets SET closed_at = clock_timestamp(),
                       requested = CASE WHEN CAST(:ended_early AS boolean) THEN served ELSE requested END
    WHERE id = :set_id AND user_id = :user_id AND closed_at IS NULL
    """
)
CLOSE_FOR_MESSAGE = text(
    """
    UPDATE qb_sets SET closed_at = clock_timestamp()
    WHERE user_id = :user_id AND request_id = :message_id AND mode = 'chat' AND closed_at IS NULL
    """
)


@dataclass(frozen=True)
class BankTest:
    """A test the bank set in a reply: its ```quiz block's body (the first question of an adaptive
    test, every question of a fixed one), its practice set, and where its questions came from."""

    body: str
    chapter_ids: tuple[str, ...]
    topic_ids: tuple[str, ...]  # the topics the request named; () = the whole chapters
    question_ids: tuple[str, ...]
    set_id: uuid.UUID
    total: int  # the questions the test will have
    adaptive: bool


def wants_test(message: str) -> bool:
    return _TEST_REQUEST.search(message or "") is not None


async def menu(
    session: AsyncSession,
    message: str,
    grade: str | None,
    medium: str | None,
    earlier: str = "",
    *,
    asked: bool | None = None,
) -> str:
    """The chapters the tutor may set a test on, when the student's message asks for one: the class
    the message names, else theirs, else the last one named earlier in the chat (`earlier`), in their
    medium, and the language subjects. "" otherwise. `asked`: whether the message asks for a test, as
    the intent router read it (app/intents); None: its words decide (wants_test)."""
    if not (wants_test(message) if asked is None else asked):
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


def quiz_question(row: Any) -> dict:
    """A stored question in a ```quiz block's form (app/assessments/state.py reads it), its case
    passage before the stem."""
    stem = row.stem if row.case_body is None else f"**{row.case_title}:** {row.case_body} ➜ {row.stem}"
    return {
        "question": stem,
        "options": [row.option_a, row.option_b, row.option_c, row.option_d],
        "answer": row.correct_option,
        "explanation": row.explanation,
    }


def _request(spec: Any) -> dict | None:
    """A question-bank request: a JSON object naming a chapter id ("chapter"), or up to MAX_CHAPTERS
    ("chapters", a mock test); with its chapter ids as "chapters"."""
    named = spec.get("chapters", spec.get("chapter")) if isinstance(spec, dict) else None
    named = [named] if isinstance(named, str) else named
    if not isinstance(named, list) or not all(isinstance(chapter, str) for chapter in named):
        return None
    chapters = list(dict.fromkeys(chapter.strip() for chapter in named))
    if not 1 <= len(chapters) <= MAX_CHAPTERS or not all(CHAPTER_ID.fullmatch(chapter) for chapter in chapters):
        return None
    return {**spec, "chapters": chapters}


def _parse(body: str) -> dict | None:
    try:
        return _request(json.loads(body))
    except ValueError:
        return None


async def _set(
    session: AsyncSession, spec: dict | None, seed: str, user_id: uuid.UUID, conversation_id: uuid.UUID, adaptive: bool
) -> tuple[BankTest | None, str]:
    """The ```quiz block for one request, and its practice set with the questions served so far; or a
    note saying why there is none. Never commits."""
    if spec is None:
        return None, NOTE_UNKNOWN
    chapters = [(await session.execute(CHAPTER, {"chapter_id": name})).one_or_none() for name in spec["chapters"]]
    if None in chapters or len({(c.class_level, c.subject_code, c.language) for c in chapters}) > 1:
        return None, NOTE_UNKNOWN  # a mock test is one class, subject and language
    first = chapters[0]
    named = []  # topics are named within one chapter; a mock test covers its chapters whole
    if len(chapters) == 1:
        named = await _topics(session, first.chapter_id, spec.get("topics", spec.get("topic")))
    pool = [topic.topic_id for topic in named]
    if not named:
        for chapter in chapters:
            pool += [topic.topic_id for topic in await session.execute(TOPICS, {"chapter_id": chapter.chapter_id})]
    asked = spec.get("count")
    asked = asked if isinstance(asked, int) and not isinstance(asked, bool) and asked >= 1 else None
    count = min(asked, MAX_COUNT) if asked else DEFAULT_COUNT
    difficulty = spec.get("difficulty") if spec.get("difficulty") in LEVELS else None
    scope = selection.Pool(
        first.language, first.class_level, first.subject_code, tuple(pool), difficulty=difficulty, card=True
    )
    row = await selection.pick_next(session, user_id, scope, seed)
    if row is None:
        return None, NOTE_EMPTY
    total = min(count, row.available)
    books = " · ".join(dict.fromkeys(chapter.book for chapter in chapters))
    title = f"{books} · " + " · ".join(f"{chapter.chapter_number}. {chapter.title}" for chapter in chapters)
    title = (title + "".join(f" · {topic.title}" for topic in named))[:200]
    filters = {
        "chapter_ids": [chapter.chapter_id for chapter in chapters],
        "language": first.language,
        "class_level": first.class_level,
        "subject_code": first.subject_code,
        "topic_ids": pool,
        "topics": [topic.topic_id for topic in named],
        "difficulty": difficulty,
        "conversation_id": str(conversation_id),
        "message_id": seed,
        "title": title,
    }
    values = {"user_id": user_id, "request_id": uuid.UUID(seed), "filters": json.dumps(filters, ensure_ascii=False)}
    set_id = await session.scalar(NEW_SET, {**values, "requested": total, "served": 0})
    rows = [row]
    while True:  # an adaptive test serves its first question; a fixed one all of them now, in that order
        item = {"set_id": set_id, "position": len(rows), "user_id": user_id}
        await session.execute(SERVE, {**item, "question_id": row.question_id, "topic_id": row.topic_id})
        if adaptive or len(rows) == total:
            break
        row = await selection.pick_next(session, user_id, scope, seed, set_id)
        if row is None:
            break
        rows.append(row)
    total = total if adaptive else len(rows)
    await session.execute(SERVED, {"served": len(rows), "requested": total, "set_id": set_id, "user_id": user_id})
    quiz = json.dumps(
        {"title": title, "questions": [quiz_question(row) for row in rows]}, ensure_ascii=False, separators=(",", ":")
    )
    test = BankTest(
        quiz,
        tuple(filters["chapter_ids"]),
        tuple(filters["topics"]),
        tuple(row.question_id for row in rows),
        set_id,
        total,
        adaptive,
    )
    fewer = f"\n\n{NOTE_FEWER.format(n=total)}" if asked and total < asked else ""
    return test, f"```quiz\n{quiz}\n```{fewer}"


async def answer(
    session: AsyncSession, user_id: uuid.UUID, set_id: uuid.UUID, position: int, letter: str
) -> tuple[datetime, bool] | None:
    """Record the student's answer to the question served at `position` of their test: graded by the
    database from the key. (answered_at, is_correct), or None when it already has an answer or there
    is no such question. Never commits."""
    params = {"chosen": letter, "set_id": set_id, "position": position, "user_id": user_id}
    found = (await session.execute(ANSWER, params)).one_or_none()
    return (found.answered_at, found.is_correct) if found is not None else None


async def next_question(session: AsyncSession, user_id: uuid.UUID, set_id: uuid.UUID, position: int) -> Any:
    """Serve the question after `position` of an adaptive test, chosen from the answer to that one (or
    its skip): the stored question, or None when its chapters have nothing left. Never commits."""
    found = (await session.execute(CHAT_SET, {"set_id": set_id, "user_id": user_id})).one_or_none()
    if found is None:
        return None
    filters = found.filters
    scope = selection.Pool(
        filters["language"],
        filters["class_level"],
        filters["subject_code"],
        tuple(filters["topic_ids"]),
        difficulty=filters["difficulty"],
        card=True,
    )
    row = await selection.pick_next(session, user_id, scope, str(found.request_id), set_id, position)
    if row is None:
        return None
    item = {"set_id": set_id, "user_id": user_id}
    question = {"question_id": row.question_id, "topic_id": row.topic_id}
    await session.execute(SERVE, {**item, **question, "position": position + 1})
    await session.execute(SERVED, {**item, "served": position + 1, "requested": found.requested})
    return row


async def close(session: AsyncSession, user_id: uuid.UUID, set_id: uuid.UUID, ended_early: bool = False) -> None:
    """A test is over: completed, or no longer answerable (regenerated, stopped, never shown). Ended
    early (the bank ran out): it holds what was served. Never commits."""
    await session.execute(CLOSE, {"set_id": set_id, "user_id": user_id, "ended_early": ended_early})


async def close_for_message(session: AsyncSession, user_id: uuid.UUID, message_id: uuid.UUID) -> None:
    """Close the test a reply set, if it has one (the reply was regenerated). Never commits."""
    await session.execute(CLOSE_FOR_MESSAGE, {"user_id": user_id, "message_id": message_id})


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
        fence = opened["fence"]
        close = re.compile(rf"^[ \t>]*{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$")
        end = index + 1
        while end < len(lines) and not close.match(lines[end]):
            end += 1
        body = "\n".join(line.lstrip(" \t>") for line in lines[index + 1 : end])  # inside a list or quote
        segments.append((opened["info"], body, "\n".join(lines[index : end + 1])))
        index = end + 1
    if prose:
        segments.append(("prose", "", "\n".join(prose)))
    return segments


def _exercise(value: Any) -> bool:
    """Whether JSON is a fill-in-the-blanks exercise: text with a [[blank]], and no other fields."""
    return (
        isinstance(value, dict)
        and isinstance(value.get("text"), str)
        and "[[" in value["text"]
        and set(value) <= EXERCISE_KEYS
    )


def _card_exercises(text: str) -> str:
    """Text with each ::: card whose own text has [[blanks]] (and no JSON or block) as a ```fill-blank
    block of that text, after its title."""
    lines = text.split("\n")
    out: list[str] = []
    index = 0
    while index < len(lines):
        opened = _CARD_START.match(lines[index])
        end = next((at for at in range(index + 1, len(lines)) if _CARD_END.match(lines[at])), None) if opened else None
        body = "\n".join(lines[index + 1 : end]).strip() if opened and end is not None else ""
        if "[[" not in body or "```" in body or _BARE_EXERCISE.search(body):
            out.append(lines[index])
            index += 1
            continue
        title = (opened["title"] or "").strip()
        exercise = json.dumps({"text": _BOLD_BLANK.sub(r"\1", body)}, ensure_ascii=False)
        out.append((f"**{title}**\n\n" if title else "") + f"```fill-blank\n{exercise}\n```")
        index = end + 1
    return "\n".join(out)


def _directive_exercises(text: str) -> str:
    """Text with each ::fill-blank{text="..."} directive as a ```fill-blank block of its fields."""

    def block(match: re.Match) -> str:
        fields = {name: value.replace('\\"', '"') for name, value in _ATTRIBUTE.findall(match["attrs"])}
        value = {key: fields[key] for key in ("text", "explanation") if key in fields}
        return f"```fill-blank\n{json.dumps(value, ensure_ascii=False)}\n```" if _exercise(value) else match[0]

    return _DIRECTIVE.sub(block, text)


def _lenient(body: str) -> str | None:
    """A fill-blank block's body that is not strict JSON but reads as an exercise, as strict JSON; None
    when it is strict JSON already, or not an exercise."""
    try:
        json.loads(body)
        return None
    except ValueError:
        pass
    try:
        value = json.loads(body, strict=False)  # line breaks and tabs inside its strings
    except ValueError:
        fields = dict(_KEY_LINE.findall(body))
        value = {key: fields[key].strip().strip('"') for key in ("text", "explanation") if key in fields}
    return json.dumps(value, ensure_ascii=False) if _exercise(value) else None


def _fenced(content: str) -> str:
    """The reply with each exercise the model wrote without its fence put in a ```fill-blank fence;
    the reply as it was when there is none."""
    parts: list[str] = []
    repaired = False
    for language, body, raw in _segments(content):
        if language == "prose":
            pieces: list[str] = []
            position = 0
            for match in _BARE_EXERCISE.finditer(raw):
                if match.start() < position or raw[match.start() - 1 : match.start()] == "`":  # inline code
                    continue
                try:
                    value, stop = json.JSONDecoder().raw_decode(raw, match.start())
                except ValueError:
                    continue
                if _exercise(value):
                    block = f"```fill-blank\n{raw[match.start() : stop]}\n```"
                    before = raw[position : match.start()]
                    card = _CARD_OPEN.search(before)
                    if card is not None:  # its ::: card goes, closing line included
                        before = before[: card.start()]
                        closed = _CARD_CLOSE.match(raw, stop)
                        stop = closed.end() if closed else stop
                    pieces += [before, f"\n\n{block}\n\n"]
                    position = stop
            text = "".join([*pieces, raw[position:]])
            carded = _card_exercises(_directive_exercises(text)) if "[[" in text else text
            parts.append(carded)
            repaired = repaired or bool(pieces) or carded != text
            continue
        if language == "fill-blank" and (strict := _lenient(body)) is not None:
            parts.append(f"```fill-blank\n{strict}\n```")
            repaired = True
            continue
        value = None
        if language != "fill-blank":
            try:
                value = json.loads(body)
            except ValueError:
                pass
        if _exercise(value):
            parts.append(f"```fill-blank\n{body}\n```")
            repaired = True
        else:
            parts.append(raw)
    return "\n".join(parts).strip("\n") if repaired else content


async def fill(
    session: AsyncSession,
    content: str,
    seed: str,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    *,
    adaptive: bool = True,
) -> tuple[str, BankTest | None]:
    """The reply (its id is `seed`) with its first test request set from the bank as the student's
    practice set (a note when it can't be), later ones dropped, every test block the model wrote
    itself replaced by a note, and an exercise written without its fence put in one. Never commits:
    the set is saved with the reply."""
    if "[[" in content:
        content = _fenced(content)
    if not any(mark in content for mark in ("```", "~~~", FENCE, '"chapter')):
        return content, None
    parts: list[str] = []
    exercises: list[int] = []  # the model's fill-blank blocks
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
                spec = _request(spec)
                if spec is None:
                    continue
                start = match.start()
                before = raw[:start].rstrip(" \t")
                if before.endswith(("```", "~~~")):  # fence marks around it on the same lines: replaced too
                    start = max(position, len(before.rstrip("`~")))
                tail = raw[stop:].lstrip(" \t\n")
                if tail.startswith(("```", "~~~")):
                    stop = len(raw) - len(tail.lstrip("`~"))
                pieces.append(raw[position:start])
                if not asked:
                    asked = True
                    test, block = await _set(session, spec, seed, user_id, conversation_id, adaptive)
                    pieces.append(f"\n\n{block}\n\n")
                position = stop
            parts.append("".join([*pieces, raw[position:]]) if pieces else raw)
        elif language in MODEL_FENCES:
            parts.append(NOTE_MODEL)
        elif language == FENCE or (language in LOOSE_FENCES and _parse(body) is not None):
            if not asked:  # later requests are dropped: one test per reply
                asked = True
                test, block = await _set(session, _parse(body), seed, user_id, conversation_id, adaptive)
                parts.append(block)
        else:
            if language == "fill-blank":
                exercises.append(len(parts))
            parts.append(raw)  # an ordinary code block
    if test is not None:  # one practice block per reply: the bank's test, recorded; not an unrecorded exercise
        for index in exercises:
            parts[index] = NOTE_EXERCISE
    return "\n".join(parts), test
