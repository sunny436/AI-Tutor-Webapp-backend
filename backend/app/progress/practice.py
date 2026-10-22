"""The practice record: what a student's answers to question-bank tests say about their learning
(GET /v1/progress/plan, /mastery, /revisions, /mistakes, /practice-tests and /practice-topics, and
the tutor's "Practice record" line through app.progress.learning.tutor_progress).

Read from the ledger (qb_sets, qb_set_items; app/qbank) on every request: nothing is stored, so
nothing can drift or be counted twice. Every number is an estimate from practice, never a mark.
- **Evidence** is an answered question of the student's own practice sets, graded by the database
  from the key: the first answer to a question on an India day (a test taken again at once adds
  nothing). An answer to a question edited after it was served (served_hash is not its
  content_hash) is set aside. Skipped questions, flashcards and the exercises the tutor writes are
  never evidence. A deleted chat keeps its answers: the ledger has no link to conversations.
- **Mastery** per concept is Bayesian knowledge tracing (GUESS, SLIP, LEARN, PRIOR): mastered at
  MASTERED_AT with MIN_ANSWERS answers to at least MIN_QUESTIONS questions (or all it has), weak
  below WEAK_BELOW after a wrong answer. Topics, chapters and subjects: means over what was
  practised, with how much of it was (coverage).
- **Mistakes**: wrong answers by concept, newest first; recurring = RECURRING_WRONG or more in the
  last RECURRING_DAYS India days.
- **Revision** per topic: a review day is an India day with answers in the topic, recalled with
  RECALLED or more of them right. The next review is LADDER's step after the last review, one step
  further for each recalled day in a row (the first step again after a lapse), at most
  WEAK_CAP_DAYS while the topic is weak. Scheduled from the days before today, so it holds all day.
- **The plan**: up to MAX_TASKS tasks of TASK_QUESTIONS questions (about TASK_MINUTES minutes each)
  within the daily goal: revisions due, then weak topics, then the next new topic of each subject,
  from the evidence before today, so it too holds all day.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from statistics import fmean
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.learning.context import PlanProfile, PracticeProgress, read_plan_profile, subject_name
from app.progress.learning import LEARNING_ZONE, PRACTICE_ANSWERS, learning_date
from app.qbank.chat_tests import quiz_question

GUESS, SLIP, LEARN, PRIOR = 0.25, 0.10, 0.15, 0.20  # BKT, per concept
MASTERED_AT, MIN_ANSWERS, MIN_QUESTIONS = 0.95, 3, 2
WEAK_BELOW = 0.5
EVIDENCE_LIMIT = 5000  # the newest answers read
LADDER = (1, 3, 7, 14, 30, 60)  # days to the next review after 1, 2, 3, ... recalled review days in a row
RECALLED = 0.75
WEAK_CAP_DAYS = 3
RECURRING_WRONG, RECURRING_DAYS = 2, 14
TASK_QUESTIONS, TASK_MINUTES, MAX_TASKS, DEFAULT_BUDGET = 5, 8, 6, 30
EXAM_SOON, EXAM_CLOSE = 30, 7  # days to the exam: at most one new topic a day, then none
LITTLE_HISTORY = 10  # fewer counted answers: the plan says it has little to go on
MODEL = {
    "method": "bkt",
    "prior": PRIOR,
    "learn": LEARN,
    "guess": GUESS,
    "slip": SLIP,
    "mastered_at": MASTERED_AT,
    "min_answers": MIN_ANSWERS,
    "min_questions": MIN_QUESTIONS,
}
RANK = {"overdue": 0, "due": 1, "done": 2, "upcoming": 3}

ANSWERS = text(
    """
    SELECT i.set_id, i.question_id, i.topic_id, q.concept_tag, i.chosen, i.is_correct, i.answered_at,
           coalesce(i.served_hash <> q.content_hash, false) AS revised
    FROM qb_set_items i JOIN qb_questions q ON q.question_id = i.question_id
    WHERE i.user_id = :user_id AND i.answered_at IS NOT NULL
    ORDER BY i.answered_at DESC
    LIMIT :limit
    """
)
TOPICS = text(
    """
    SELECT t.topic_id, t.topic_number, t.title AS topic_title, c.chapter_id, c.chapter_number,
           c.title AS chapter_title, b.book_id, b.title AS book_title, b.subject_code, b.class_level, b.language,
           (SELECT count(*) FROM qb_topics x WHERE x.chapter_id = c.chapter_id) AS chapter_topics
    FROM qb_topics t
    JOIN qb_chapters c ON c.chapter_id = t.chapter_id
    JOIN qb_books b ON b.book_id = c.book_id
    WHERE t.topic_id = ANY(CAST(:topic_ids AS text[]))
    """
)
CONCEPTS = text(
    """
    SELECT k.topic_id, k.concept_tag, k.learning_objective,
           (SELECT count(*) FROM qb_questions q
            WHERE q.topic_id = k.topic_id AND q.concept_tag = k.concept_tag
              AND q.review_status IN ('approved', 'needs_review') AND q.is_active) AS servable
    FROM qb_concepts k
    WHERE k.topic_id = ANY(CAST(:topic_ids AS text[]))
    """
)
# Chapters with servable questions in every book of these books' subjects (class and language).
SUBJECT_CHAPTERS = text(
    """
    SELECT b.subject_code, b.class_level, b.language, count(*) AS chapters
    FROM qb_books b JOIN qb_chapters c ON c.book_id = b.book_id
    WHERE (b.subject_code, b.class_level, b.language) IN (
              SELECT p.subject_code, p.class_level, p.language FROM qb_books p
              WHERE p.book_id = ANY(CAST(:book_ids AS text[])))
      AND EXISTS (
          SELECT 1 FROM qb_questions q
          WHERE q.language = b.language AND q.class_level = b.class_level AND q.subject_code = b.subject_code
            AND q.chapter_id = c.chapter_id AND q.review_status IN ('approved', 'needs_review') AND q.is_active
      )
    GROUP BY b.subject_code, b.class_level, b.language
    """
)
# The bank's topics for a class, in the student's medium and the language subjects (chat_tests.MENU's rule).
BANK = text(
    """
    SELECT b.subject_code, b.book_id, b.title AS book_title, b.language, c.chapter_id, c.chapter_number,
           c.title AS chapter_title, t.topic_id, t.topic_number, t.title AS topic_title, count(*) AS questions
    FROM qb_books b
    JOIN qb_chapters c ON c.book_id = b.book_id
    JOIN qb_topics t ON t.chapter_id = c.chapter_id
    JOIN qb_questions q ON q.topic_id = t.topic_id
    WHERE b.class_level = :class_level
      AND (b.language = :language OR b.subject_code IN ('english', 'hindi', 'sanskrit'))
      AND q.review_status IN ('approved', 'needs_review') AND q.is_active
    GROUP BY b.subject_code, b.book_id, b.title, b.language, c.chapter_id, c.chapter_number, c.title, t.topic_id,
             t.topic_number, t.title
    ORDER BY b.subject_code, b.title, c.chapter_number, t.topic_number
    """
)
QUESTIONS = text(
    """
    SELECT q.question_id, q.stem, q.option_a, q.option_b, q.option_c, q.option_d, q.correct_option, q.explanation,
           c.title AS case_title, c.body AS case_body
    FROM qb_questions q LEFT JOIN qb_cases c ON c.case_id = q.case_id
    WHERE q.question_id = ANY(CAST(:question_ids AS text[]))
    """
)
# The chat a set was taken in, while that chat still exists.
CHATS = text(
    """
    SELECT s.id, c.id AS conversation_id
    FROM qb_sets s
    JOIN conversations c ON c.id = CAST(s.filters ->> 'conversation_id' AS uuid) AND c.user_id = s.user_id
    WHERE s.user_id = :user_id AND s.id = ANY(CAST(:set_ids AS uuid[]))
    """
)
TESTS = text(
    """
    SELECT s.id, s.request_id, s.filters, s.created_at, s.requested, s.served, s.closed_at,
           counts.answered, counts.correct, c.id AS conversation_id
    FROM (SELECT * FROM qb_sets WHERE user_id = :user_id AND mode = 'chat' ORDER BY created_at DESC LIMIT :limit) s
    CROSS JOIN LATERAL (
        SELECT count(i.answered_at) AS answered, count(*) FILTER (WHERE i.is_correct) AS correct
        FROM qb_set_items i WHERE i.set_id = s.id
    ) counts
    LEFT JOIN conversations c ON c.id = CAST(s.filters ->> 'conversation_id' AS uuid) AND c.user_id = s.user_id
    ORDER BY s.created_at DESC
    """
)


@dataclass(frozen=True)
class Answer:
    """One answered question of the student's ledger."""

    set_id: uuid.UUID
    question_id: str
    topic_id: str
    concept_tag: str
    right: bool
    chosen: str
    answered_at: datetime
    revised: bool = False  # the question was edited after it was served: not evidence

    @property
    def day(self) -> date:
        return learning_date(self.answered_at)


@dataclass(frozen=True)
class Topic:
    """Where a topic is in the bank."""

    topic_id: str
    number: int
    title: str
    chapter_id: str
    chapter_number: int
    chapter_title: str
    book_id: str
    book_title: str
    subject_code: str
    class_level: int
    language: str
    chapter_topics: int = 0


@dataclass
class Concept:
    """What the evidence says of one concept of a topic, from its answers oldest first."""

    topic_id: str
    tag: str
    estimate: float = PRIOR
    answered: int = 0
    correct: int = 0
    questions: set[str] = field(default_factory=set)
    last_at: datetime | None = None


@dataclass(frozen=True)
class Review:
    """A topic's revision as of the start of `today` (`schedule`)."""

    topic_id: str
    state: str  # overdue, due, done (reviewed today while due or overdue) or upcoming
    due: date
    interval: int
    recall: float
    last_reviewed: date
    last_accuracy: float
    reviews: int


@dataclass(frozen=True)
class Task:
    """A task of the plan, before today's answers are counted against it."""

    kind: str  # revise, strengthen or learn
    reason: str  # overdue, due, weak_concept, next_topic or start_here
    topic: Topic
    concept_tag: str | None = None
    estimate: float | None = None
    due: date | None = None
    overdue_days: int | None = None


@dataclass(frozen=True)
class Record:
    """A student's answers (the newest EVIDENCE_LIMIT, oldest first), and the bank's topics and
    concepts (learning objective, servable questions) they are in."""

    answers: list[Answer]
    topics: dict[str, Topic]
    concepts: dict[tuple[str, str], tuple[str, int]]


# ------------------------------------------------------------------ the rules (pure)
def bkt(p: float, right: bool) -> float:
    """The chance the concept is known after one more answer: Bayes on the answer, then learning."""
    known = p * (1 - SLIP) if right else p * SLIP
    unknown = (1 - p) * GUESS if right else (1 - p) * (1 - GUESS)
    p = known / (known + unknown)
    return p + (1 - p) * LEARN


def counted(answers: list[Answer]) -> list[Answer]:
    """The evidence, oldest first: no revised answer, and only the first answer to a question on an India day."""
    first: dict[tuple[str, date], Answer] = {}
    for answer in sorted(answers, key=lambda answer: answer.answered_at):
        if not answer.revised:
            first.setdefault((answer.question_id, answer.day), answer)
    return list(first.values())


def concepts(evidence: list[Answer]) -> dict[tuple[str, str], Concept]:
    found: dict[tuple[str, str], Concept] = {}
    for answer in evidence:  # oldest first
        key = (answer.topic_id, answer.concept_tag)
        concept = found.setdefault(key, Concept(*key))
        concept.estimate = bkt(concept.estimate, answer.right)
        concept.answered += 1
        concept.correct += answer.right
        concept.questions.add(answer.question_id)
        concept.last_at = answer.answered_at
    return found


def concept_state(concept: Concept, servable: int) -> str:
    """mastered, weak, not_enough_evidence or learning; `servable`: the concept's questions in the bank."""
    distinct = len(concept.questions) >= min(MIN_QUESTIONS, servable)
    if concept.estimate >= MASTERED_AT and concept.answered >= MIN_ANSWERS and distinct:
        return "mastered"
    if concept.estimate < WEAK_BELOW and concept.correct < concept.answered:
        return "weak"
    return "not_enough_evidence" if concept.answered < MIN_ANSWERS else "learning"


def topic_state(states: list[str], concepts_in_topic: int) -> str:
    """Mastered when every concept of the topic is; weak when a practised one is."""
    if len(states) >= concepts_in_topic and all(state == "mastered" for state in states):
        return "mastered"
    if "weak" in states:
        return "weak"
    return "not_enough_evidence" if all(state == "not_enough_evidence" for state in states) else "learning"


def topic_estimates(found: dict[tuple[str, str], Concept]) -> dict[str, float]:
    """Per topic: the mean estimate of its practised concepts."""
    by_topic: dict[str, list[float]] = defaultdict(list)
    for concept in found.values():
        by_topic[concept.topic_id].append(concept.estimate)
    return {topic: fmean(estimates) for topic, estimates in by_topic.items()}


def interval(days: list[tuple[int, int]], weak: bool) -> int:
    """Days from the last review to the next, from the review days so far ((right, answered) each,
    oldest first): LADDER's step for the recalled days in a row at the end, its first after a lapse."""
    run = 0
    for right, answered in days:
        run = run + 1 if right >= RECALLED * answered else 0
    step = LADDER[min(max(run - 1, 0), len(LADDER) - 1)]
    return min(step, WEAK_CAP_DAYS) if weak else step


def recall(elapsed: int, interval_days: int) -> float:
    """The chance of remembering `elapsed` days after the last review: 0.9 when the review is due."""
    return 1 / (1 + max(elapsed, 0) / (9 * interval_days))


def review(topic_id: str, days: dict[date, tuple[int, int]], today: date, weak: bool) -> Review:
    """A topic's revision from its review days (India date: (right, answered)), scheduled from the
    days before today; a topic first practised today, from today."""
    ordered = sorted(days.items())
    before = [(day, score) for day, score in ordered if day < today] or ordered
    last = before[-1][0]
    step = interval([score for _, score in before], weak)
    due = last + timedelta(days=step)
    if last >= today:
        state = "upcoming"
    elif today in days:
        state = "done" if due <= today else "upcoming"
    else:
        state = "overdue" if due < today else "due" if due == today else "upcoming"
    latest, (right, answered) = ordered[-1]
    return Review(topic_id, state, due, step, recall((today - last).days, step), latest, right / answered, len(ordered))


def schedule(evidence: list[Answer], today: date) -> list[Review]:
    """Every practised topic's revision, as of the start of `today`."""
    days: dict[str, dict[date, tuple[int, int]]] = defaultdict(dict)
    for answer in evidence:
        right, answered = days[answer.topic_id].get(answer.day, (0, 0))
        days[answer.topic_id][answer.day] = (right + answer.right, answered + 1)
    before = topic_estimates(concepts([answer for answer in evidence if answer.day < today]))
    return [review(topic, found, today, before.get(topic, 1.0) < WEAK_BELOW) for topic, found in days.items()]


def recent_wrong(evidence: list[Answer], today: date) -> Counter[tuple[str, str]]:
    """Wrong answers per concept in the last RECURRING_DAYS India days (today included)."""
    since = today - timedelta(days=RECURRING_DAYS - 1)
    return Counter(
        (answer.topic_id, answer.concept_tag) for answer in evidence if not answer.right and answer.day >= since
    )


def revision_order(item: Review, estimate: float | None) -> tuple:
    """Overdue, then due, each most at risk of being forgotten first, then the weaker topic; done;
    then upcoming, soonest first."""
    if item.state in ("overdue", "due"):
        return (RANK[item.state], item.recall, estimate if estimate is not None else 0.0, item.topic_id)
    return (RANK[item.state], item.due.toordinal(), 0.0, item.topic_id)


def next_topics(bank: list[Topic], subjects: list[str], practised: set[str], reason: str) -> list[Task]:
    """For each subject in order, its first topic not practised yet: in a chapter already begun if there
    is one, else in book order."""
    tasks = []
    for subject in subjects:
        topics = [topic for topic in bank if topic.subject_code == subject]
        begun = {topic.chapter_id for topic in topics if topic.topic_id in practised}
        fresh = [topic for topic in topics if topic.topic_id not in practised]
        if fresh:
            tasks.append(Task("learn", reason, min(fresh, key=lambda topic: topic.chapter_id not in begun)))
    return tasks


def choose(candidates: list[Task], budget_minutes: int, days_to_exam: int | None) -> list[Task]:
    """The plan from its candidates in order (revisions, weak topics, new topics): one task per topic,
    as many as the budget holds (at least one, at most MAX_TASKS); with the exam EXAM_SOON days away
    at most one new topic, and none in its last EXAM_CLOSE days."""
    room = max(1, min(MAX_TASKS, budget_minutes // TASK_MINUTES))
    new = MAX_TASKS
    if days_to_exam is not None:
        new = 0 if days_to_exam <= EXAM_CLOSE else 1 if days_to_exam <= EXAM_SOON else MAX_TASKS
    chosen: list[Task] = []
    for task in candidates:
        if len(chosen) == room:
            break
        if any(task.topic.topic_id == other.topic.topic_id for other in chosen):
            continue
        if task.kind == "learn":
            if not new:
                continue
            new -= 1
        chosen.append(task)
    return chosen


def prompt(kind: str, topic: Topic) -> str:
    """What a task, a revision or a mistake puts in a new chat for the student to send."""
    subject = subject_name(topic.subject_code) or topic.subject_code
    place = (
        f"Class {topic.class_level} {subject} ({topic.book_title}) Chapter {topic.chapter_number} "
        f'"{topic.chapter_title}", topic "{topic.title}"'
    )
    if kind == "revise":
        return f"Help me revise {place}, then test me on it: {TASK_QUESTIONS} questions."
    return f"Test me on {place}: {TASK_QUESTIONS} questions."


# ------------------------------------------------------------------ reading
async def read_record(session: AsyncSession, user_id: uuid.UUID) -> Record:
    rows = (await session.execute(ANSWERS, {"user_id": user_id, "limit": EVIDENCE_LIMIT})).all()
    answers = [
        Answer(
            row.set_id,
            row.question_id,
            row.topic_id,
            row.concept_tag,
            row.is_correct,
            row.chosen,
            row.answered_at,
            row.revised,
        )
        for row in reversed(rows)
    ]
    topic_ids = sorted({answer.topic_id for answer in answers})
    if not topic_ids:
        return Record([], {}, {})
    topics = {
        row.topic_id: Topic(
            row.topic_id,
            row.topic_number,
            row.topic_title,
            row.chapter_id,
            row.chapter_number,
            row.chapter_title,
            row.book_id,
            row.book_title,
            row.subject_code,
            row.class_level,
            row.language,
            row.chapter_topics,
        )
        for row in await session.execute(TOPICS, {"topic_ids": topic_ids})
    }
    found = await session.execute(CONCEPTS, {"topic_ids": topic_ids})
    return Record(
        answers, topics, {(row.topic_id, row.concept_tag): (row.learning_objective, row.servable) for row in found}
    )


def _states(record: Record, found: dict[tuple[str, str], Concept]) -> dict[tuple[str, str], str]:
    return {key: concept_state(concept, record.concepts.get(key, ("", 0))[1]) for key, concept in found.items()}


def _place(topic: Topic) -> dict[str, Any]:
    return {
        "topic_id": topic.topic_id,
        "topic_title": topic.title,
        "chapter_id": topic.chapter_id,
        "chapter_title": topic.chapter_title,
        "chapter_number": topic.chapter_number,
        "book_title": topic.book_title,
        "subject_code": topic.subject_code,
        "class_level": topic.class_level,
    }


async def _bank(session: AsyncSession, class_level: int, language: str) -> list[Any]:
    return (await session.execute(BANK, {"class_level": class_level, "language": language})).all()


# ------------------------------------------------------------------ the endpoints
async def mastery(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """Estimates per concept, topic, chapter and subject: practised ones only."""
    record = await read_record(session, user_id)
    evidence = counted(record.answers)
    found = concepts(evidence)
    states = _states(record, found)
    per_topic = Counter(topic_id for topic_id, _ in record.concepts)
    books = sorted({record.topics[topic_id].book_id for topic_id, _ in found})
    chapters_in = {
        (row.subject_code, row.class_level, row.language): row.chapters
        for row in (await session.execute(SUBJECT_CHAPTERS, {"book_ids": books}) if books else [])
    }
    topics: dict[str, dict[str, Any]] = {}
    for (topic_id, tag), concept in sorted(found.items()):
        topic = record.topics[topic_id]
        entry = topics.setdefault(
            topic_id,
            {"topic_id": topic_id, "number": topic.number, "title": topic.title, "estimates": [], "concepts": []},
        )
        entry["estimates"].append(concept.estimate)
        entry["concepts"].append(
            {
                "concept_tag": tag,
                "objective": record.concepts.get((topic_id, tag), ("", 0))[0],
                "estimate": round(concept.estimate, 3),
                "state": states[(topic_id, tag)],
                "answered": concept.answered,
                "correct": concept.correct,
                "distinct_questions": len(concept.questions),
                "last_answered_at": concept.last_at,
            }
        )
    chapters: dict[str, dict[str, Any]] = {}
    for topic_id, entry in topics.items():
        topic, estimates = record.topics[topic_id], entry.pop("estimates")
        concept_count = max(per_topic[topic_id], len(estimates))
        entry |= {
            "estimate": round(fmean(estimates), 3),
            "state": topic_state([concept["state"] for concept in entry["concepts"]], concept_count),
            "coverage": round(len(estimates) / concept_count, 3),
            "concept_count": concept_count,
        }
        chapter = chapters.setdefault(
            topic.chapter_id,
            {
                "chapter_id": topic.chapter_id,
                "number": topic.chapter_number,
                "title": topic.chapter_title,
                "book_title": topic.book_title,
                "topic_count": max(topic.chapter_topics, 1),
                "subject": (topic.subject_code, topic.class_level, topic.language),
                "topics": [],
            },
        )
        chapter["topics"].append(entry)
    subjects: dict[tuple[str, int, str], dict[str, Any]] = {}
    for chapter in sorted(chapters.values(), key=lambda chapter: (chapter["book_title"], chapter["number"])):
        key = chapter.pop("subject")
        chapter["topics"].sort(key=lambda topic: topic["number"])
        estimates = [topic["estimate"] for topic in chapter["topics"]]
        chapter |= {
            "estimate": round(fmean(estimates), 3),
            "coverage": round(min(len(estimates) / chapter["topic_count"], 1.0), 3),
        }
        subject = subjects.setdefault(
            key, {"subject_code": key[0], "class_level": key[1], "language": key[2], "chapters": []}
        )
        subject["chapters"].append(chapter)
    for key, subject in subjects.items():
        estimates = [chapter["estimate"] for chapter in subject["chapters"]]
        subject |= {
            "estimate": round(fmean(estimates), 3),
            "coverage": round(min(len(estimates) / max(chapters_in.get(key, 1), 1), 1.0), 3),
        }
    return {
        "model": MODEL,
        "answered": len(evidence),
        "revised_answers": sum(answer.revised for answer in record.answers),
        "subjects": [subjects[key] for key in sorted(subjects)],
    }


async def revisions(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> dict[str, Any]:
    """Every practised topic's revision today: overdue and due first, by forgetting risk."""
    today = learning_date(now)
    record = await read_record(session, user_id)
    evidence = counted(record.answers)
    current = topic_estimates(concepts(evidence))
    items = sorted(schedule(evidence, today), key=lambda item: revision_order(item, current.get(item.topic_id)))
    return {
        "date": today,
        "ladder_days": list(LADDER),
        "items": [
            {
                **_place(record.topics[item.topic_id]),
                "topic_number": record.topics[item.topic_id].number,
                "state": item.state,
                "due_date": item.due,
                "overdue_days": max((today - item.due).days, 0),
                "interval_days": item.interval,
                "recall": round(item.recall, 3),
                "last_reviewed": item.last_reviewed,
                "last_accuracy": round(item.last_accuracy, 3),
                "reviews": item.reviews,
                "estimate": round(current[item.topic_id], 3) if item.topic_id in current else None,
                "prompt": prompt("revise", record.topics[item.topic_id]),
            }
            for item in items
        ],
    }


async def mistakes(session: AsyncSession, user_id: uuid.UUID, now: datetime, limit: int) -> dict[str, Any]:
    """The newest `limit` wrong answers, by concept (the concept with the newest mistake first)."""
    today = learning_date(now)
    record = await read_record(session, user_id)
    evidence = counted(record.answers)
    states = _states(record, concepts(evidence))
    wrong = [answer for answer in reversed(evidence) if not answer.right]  # newest first
    wrong_all = Counter((answer.topic_id, answer.concept_tag) for answer in wrong)
    wrong_recent = recent_wrong(evidence, today)
    listed = wrong[:limit]
    content, chats = {}, {}
    if listed:
        ids = sorted({answer.question_id for answer in listed})
        content = {row.question_id: row for row in await session.execute(QUESTIONS, {"question_ids": ids})}
        sets = sorted({answer.set_id for answer in listed})
        chats = {
            row.id: row.conversation_id for row in await session.execute(CHATS, {"user_id": user_id, "set_ids": sets})
        }
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for answer in listed:
        key = (answer.topic_id, answer.concept_tag)
        topic = record.topics[answer.topic_id]
        group = groups.setdefault(
            key,
            {
                **_place(topic),
                "concept_tag": answer.concept_tag,
                "objective": record.concepts.get(key, ("", 0))[0],
                "wrong": wrong_all[key],
                "wrong_14d": wrong_recent[key],
                "recurring": wrong_recent[key] >= RECURRING_WRONG,
                "state": states[key],
                "prompt": prompt("strengthen", topic),
                "items": [],
            },
        )
        question = content[answer.question_id]
        shown = quiz_question(question)
        group["items"].append(
            {
                "question_id": answer.question_id,
                "answered_at": answer.answered_at,
                "stem": shown["question"],
                "options": shown["options"],
                "chosen": answer.chosen,
                "correct": question.correct_option,
                "explanation": question.explanation,
                "conversation_id": chats.get(answer.set_id),
            }
        )
    return {"recurring_rule": {"wrong": RECURRING_WRONG, "days": RECURRING_DAYS}, "concepts": list(groups.values())}


async def plan(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> dict[str, Any]:
    """Today's plan (India day), chosen from the evidence before today; today's answers only mark
    progress on it."""
    profile = await read_plan_profile(session, user_id)
    record = await read_record(session, user_id)
    rows = await _bank(session, profile.class_level, profile.language) if profile.class_level else []
    bank = [
        Topic(
            row.topic_id,
            row.topic_number,
            row.topic_title,
            row.chapter_id,
            row.chapter_number,
            row.chapter_title,
            row.book_id,
            row.book_title,
            row.subject_code,
            profile.class_level,
            row.language,
        )
        for row in rows
    ]
    return build_plan(record, profile, bank, learning_date(now))


def build_plan(record: Record, profile: PlanProfile, bank: list[Topic], today: date) -> dict[str, Any]:
    """The plan from a student's record, profile and the bank's topics for their class (in book order)."""
    evidence = counted(record.answers)
    found = concepts(evidence)
    states = _states(record, found)
    reviews = schedule(evidence, today)
    before = [answer for answer in evidence if answer.day < today]
    found_before = concepts(before)
    estimates_before = topic_estimates(found_before)
    # 1. Revisions due before today's answers: overdue first, each most at risk first.
    due = [item for item in reviews if item.state in ("overdue", "due", "done")]
    due.sort(key=lambda item: (item.due >= today, item.recall, estimates_before.get(item.topic_id, 0.0), item.topic_id))
    candidates = [
        Task(
            "revise",
            "overdue" if item.due < today else "due",
            record.topics[item.topic_id],
            estimate=round(estimates_before[item.topic_id], 3) if item.topic_id in estimates_before else None,
            due=item.due,
            overdue_days=(today - item.due).days,
        )
        for item in due
    ]
    # 2. Weak concepts, the weakest first.
    states_before = _states(record, found_before)
    weak = sorted(
        (concept for key, concept in found_before.items() if states_before[key] == "weak"),
        key=lambda concept: (concept.estimate, concept.topic_id, concept.tag),
    )
    candidates += [
        Task("strengthen", "weak_concept", record.topics[concept.topic_id], concept.tag, round(concept.estimate, 3))
        for concept in weak
    ]
    # 3. The next new topic of each of their subjects (or, before they chose any of the bank's, of each).
    offered = list(dict.fromkeys(topic.subject_code for topic in bank))
    subjects = [subject for subject in profile.subjects if subject in offered]
    practised = {answer.topic_id for answer in before}
    candidates += next_topics(bank, subjects or offered, practised, "next_topic" if subjects else "start_here")
    days_to_exam = (profile.exam_date - today).days if profile.exam_date and profile.exam_date >= today else None
    budget = profile.daily_minutes_goal or DEFAULT_BUDGET
    today_by_topic = Counter(answer.topic_id for answer in record.answers if answer.day == today)
    return {
        "date": today,
        "timezone": LEARNING_ZONE.key,
        "budget_minutes": budget,
        "budget_source": "goal" if profile.daily_minutes_goal else "default",
        "insufficient_history": len(evidence) < LITTLE_HISTORY,
        "needs_profile": not subjects,
        "exam_date": profile.exam_date,
        "days_to_exam": days_to_exam,
        "answered_today": sum(today_by_topic.values()),
        "answers_for_learning_day": PRACTICE_ANSWERS,
        "summary": {
            "answered": len(evidence),
            "practised_concepts": len(found),
            "mastered_concepts": sum(state == "mastered" for state in states.values()),
            "weak_concepts": sum(state == "weak" for state in states.values()),
            "due_revisions": sum(item.state == "due" for item in reviews),
            "overdue_revisions": sum(item.state == "overdue" for item in reviews),
            "recurring_mistakes": sum(count >= RECURRING_WRONG for count in recent_wrong(evidence, today).values()),
        },
        "tasks": [
            {
                "kind": task.kind,
                "reason": task.reason,
                "subject_code": task.topic.subject_code,
                "class_level": task.topic.class_level,
                "language": task.topic.language,
                "book_title": task.topic.book_title,
                "chapter_id": task.topic.chapter_id,
                "chapter_number": task.topic.chapter_number,
                "chapter_title": task.topic.chapter_title,
                "topic_id": task.topic.topic_id,
                "topic_number": task.topic.number,
                "topic_title": task.topic.title,
                "concept_tag": task.concept_tag,
                "estimate": task.estimate,
                "due_date": task.due,
                "overdue_days": task.overdue_days,
                "questions": TASK_QUESTIONS,
                "minutes": TASK_MINUTES,
                "prompt": prompt(task.kind, task.topic),
                "answered_today": today_by_topic[task.topic.topic_id],
                "done": today_by_topic[task.topic.topic_id] >= TASK_QUESTIONS,
            }
            for task in choose(candidates, budget, days_to_exam)
        ],
    }


async def practice_tests(session: AsyncSession, user_id: uuid.UUID, limit: int) -> dict[str, Any]:
    """The student's tests in the chat, newest first; the chat only while it still exists."""
    rows = await session.execute(TESTS, {"user_id": user_id, "limit": limit})
    return {
        "items": [
            {
                "set_id": row.id,
                "message_id": row.request_id if row.conversation_id else None,
                "conversation_id": row.conversation_id,
                "title": row.filters.get("title") or "",
                "chapter_ids": row.filters.get("chapter_ids") or [],
                "started_at": row.created_at,
                "total": row.requested,
                "served": row.served,
                "answered": row.answered,
                "correct": row.correct,
                "open": row.closed_at is None and row.conversation_id is not None,
            }
            for row in rows
        ]
    }


async def practice_topics(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """The bank's chapters and topics a student can practise: their class, in their medium, and the
    language subjects; their own subjects first."""
    profile = await read_plan_profile(session, user_id)
    base = {"class_level": profile.class_level, "language": profile.language, "subjects": []}
    if profile.class_level is None:
        return {**base, "available": False, "reason": "no_class"}
    rows = await _bank(session, profile.class_level, profile.language)
    if not rows:
        return {**base, "available": False, "reason": "no_questions"}
    subjects: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)  # subject -> book id -> book
    for row in rows:
        book = subjects[row.subject_code].setdefault(
            row.book_id, {"book_id": row.book_id, "title": row.book_title, "language": row.language, "chapters": {}}
        )
        chapter = book["chapters"].setdefault(
            row.chapter_id,
            {
                "chapter_id": row.chapter_id,
                "number": row.chapter_number,
                "title": row.chapter_title,
                "questions": 0,
                "topics": [],
            },
        )
        chapter["questions"] += row.questions
        chapter["topics"].append(
            {"topic_id": row.topic_id, "number": row.topic_number, "title": row.topic_title, "questions": row.questions}
        )
    own = {subject: index for index, subject in enumerate(profile.subjects)}
    return {
        **base,
        "available": True,
        "reason": None,
        "subjects": [
            {
                "subject_code": subject,
                "books": [{**book, "chapters": list(book["chapters"].values())} for book in books.values()],
            }
            for subject, books in sorted(subjects.items(), key=lambda item: (own.get(item[0], len(own)), item[0]))
        ],
    }


async def tutor_practice(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> PracticeProgress | None:
    """The practice record as the tutor is told it (app.progress.learning.tutor_progress), the same as
    /mastery and /revisions say; None before the student's first counted answer."""
    record = await read_record(session, user_id)
    evidence = counted(record.answers)
    if not evidence:
        return None
    today = learning_date(now)
    found = concepts(evidence)
    states = _states(record, found)
    weakest = sorted(
        (key for key, state in states.items() if state == "weak"), key=lambda key: (found[key].estimate, key)
    )
    current = topic_estimates(found)
    due = sorted(
        (item for item in schedule(evidence, today) if item.state in ("overdue", "due")),
        key=lambda item: revision_order(item, current.get(item.topic_id)),
    )
    return PracticeProgress(
        weakest=tuple(tag.replace("-", " ") for _, tag in weakest[:3]),
        due=tuple((record.topics[item.topic_id].title, (today - item.due).days) for item in due[:3]),
        mastered=sum(state == "mastered" for state in states.values()),
        answered_today=sum(answer.day == today for answer in record.answers),
        learning_day_answers=PRACTICE_ANSWERS,
    )
