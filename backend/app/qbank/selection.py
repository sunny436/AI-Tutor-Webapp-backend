"""Serving stored questions: tests, adaptive practice sets, answers, results and coverage.

SQL filters and fixed rules only: no model is called and nothing is generated (docs/question_bank.md,
"Selection contract").
- **Eligible** = servable (approved or awaiting review: the owner's decision, 2026-10-16), active
  and matching every filter exactly. A filter is never relaxed, and
  nothing is taken from another class, subject, book, chapter, topic, language, difficulty or format.
- **Too few eligible questions** = a shortage report, and no set (unless the caller allowed a
  partial one).
- **Order** is seeded by the set's id (md5(seed || question_id)): the same set always holds the same
  questions, two sets differ. Questions the student has seen come last, or not at all (unseen_only).
- **A set is created once per request_id**: the same request again gets the same set; another
  request with that id gets 409.
- **Adaptive**: one question at a time, chosen from the student's previous answer (`pick_next`:
  in the topic for adaptive practice, under the set's row lock, so a retried "next" gets the open
  question back; in the test so far for a test in the chat, app/qbank/chat_tests.py).
- **Answers** belong to a served question of the student's own set; the database grades them from
  the key and keeps the first (0015's qb_set_items_answer). The same answer again gets the same
  result; a different one gets 409. An adaptive answer returns the key and explanation at once; a
  test's come with its results, once it is closed or fully answered.
- **Accuracy** per concept is smoothed accuracy, (right + 1) / (tries + 2): a practice signal,
  not a validated measure of mastery.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import exists, func, literal, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    QB_DIFFICULTIES,
    QB_FORMATS,
    QB_LANGUAGES,
    QbBook,
    QbChapter,
    QbQuestion,
    QbSet,
    QbSetItem,
    QbTopic,
)
from app.errors import Conflict, NotFound, ValidationFailed
from app.qbank.validate import TARGET_PER_TOPIC

MAX_SET = 100
SERVABLE = ("approved", "needs_review")  # 0016's index predicate; never draft or rejected
REQUIRED = ("language", "class_level", "subject_code", "syllabus_version")
OPTIONAL = ("book_id", "chapter_id", "topic_id", "question_format", "unseen_only")


@dataclass(frozen=True)
class Filters:
    language: str
    class_level: int
    subject_code: str
    syllabus_version: str
    book_id: str | None = None
    chapter_id: str | None = None
    topic_id: str | None = None
    question_format: str | None = None
    unseen_only: bool = False


def parse_filters(raw: dict[str, Any]) -> Filters:
    unknown = set(raw) - {*REQUIRED, *OPTIONAL}
    if unknown:
        raise ValidationFailed(f"Unknown filters: {', '.join(sorted(unknown))}.")
    missing = [name for name in REQUIRED if raw.get(name) is None]
    if missing:
        raise ValidationFailed(f"Required filters: {', '.join(missing)}.")
    if raw["language"] not in QB_LANGUAGES:
        raise ValidationFailed(f"language must be one of {', '.join(QB_LANGUAGES)}.")
    if not isinstance(raw["class_level"], int) or not 6 <= raw["class_level"] <= 12:
        raise ValidationFailed("class_level must be 6-12.")
    if raw.get("question_format") is not None and raw["question_format"] not in QB_FORMATS:
        raise ValidationFailed(f"question_format must be one of {', '.join(QB_FORMATS)}.")
    for name in ("subject_code", "syllabus_version", "book_id", "chapter_id", "topic_id"):
        if raw.get(name) is not None and (not isinstance(raw[name], str) or not raw[name] or len(raw[name]) > 120):
            raise ValidationFailed(f"{name} must be a short string.")
    if not isinstance(raw.get("unseen_only", False), bool):
        raise ValidationFailed("unseen_only must be true or false.")
    return Filters(**raw)


async def _check_scope(session: AsyncSession, f: Filters) -> None:
    """A named book, chapter or topic must exist inside the requested class, subject and language."""
    in_scope = (
        QbBook.language == f.language,
        QbBook.class_level == f.class_level,
        QbBook.subject_code == f.subject_code,
    )
    checks = []
    if f.book_id:
        checks.append(("book", select(QbBook.book_id).where(QbBook.book_id == f.book_id, *in_scope)))
    if f.chapter_id:
        query = select(QbChapter.chapter_id).join(QbBook, QbBook.book_id == QbChapter.book_id)
        query = query.where(QbChapter.chapter_id == f.chapter_id, *in_scope)
        checks.append(("chapter", query.where(QbChapter.book_id == f.book_id) if f.book_id else query))
    if f.topic_id:
        query = (
            select(QbTopic.topic_id)
            .join(QbChapter, QbChapter.chapter_id == QbTopic.chapter_id)
            .join(QbBook, QbBook.book_id == QbChapter.book_id)
            .where(QbTopic.topic_id == f.topic_id, *in_scope)
        )
        query = query.where(QbChapter.chapter_id == f.chapter_id) if f.chapter_id else query
        checks.append(("topic", query.where(QbBook.book_id == f.book_id) if f.book_id else query))
    for name, query in checks:
        if await session.scalar(query) is None:
            raise ValidationFailed(
                f"That {name} is not in Class {f.class_level} {f.subject_code} ({f.language}) as requested."
            )


def _seen(user_id: uuid.UUID) -> Any:
    return exists().where(
        QbSetItem.user_id == user_id,
        QbSetItem.topic_id == QbQuestion.topic_id,
        QbSetItem.question_id == QbQuestion.question_id,
    )


def _eligible(f: Filters, user_id: uuid.UUID) -> list[Any]:
    conditions = [
        QbQuestion.review_status.in_(SERVABLE),
        QbQuestion.is_active.is_(True),
        QbQuestion.language == f.language,
        QbQuestion.class_level == f.class_level,
        QbQuestion.subject_code == f.subject_code,
        QbQuestion.syllabus_version == f.syllabus_version,
    ]
    for name in ("book_id", "chapter_id", "topic_id", "question_format"):
        if getattr(f, name) is not None:
            conditions.append(getattr(QbQuestion, name) == getattr(f, name))
    if f.unseen_only:
        conditions.append(~_seen(user_id))
    return conditions


async def _pool(
    session: AsyncSession, f: Filters, user_id: uuid.UUID, seed: str, difficulty: str, n: int
) -> tuple[list[tuple[str, str]], int]:
    """Up to n eligible questions of one difficulty, unseen first, in the set's seeded order; and how
    many are eligible in all."""
    query = (
        select(QbQuestion.question_id, QbQuestion.topic_id, func.count().over().label("available"))
        .where(*_eligible(f, user_id), QbQuestion.difficulty == difficulty)
        .order_by(_seen(user_id), func.md5(literal(seed) + QbQuestion.question_id))
        .limit(n)
    )
    rows = (await session.execute(query)).all()
    return [(row.question_id, row.topic_id) for row in rows], rows[0].available if rows else 0


async def _claim(
    session: AsyncSession, user_id: uuid.UUID, request_id: uuid.UUID, mode: str, spec: dict, requested: int
) -> tuple[uuid.UUID, dict | None]:
    """A new set for this request, or (its id, a replay) when the request was already made."""
    set_id = await session.scalar(
        insert(QbSet)
        .values(user_id=user_id, request_id=request_id, mode=mode, filters=spec, requested=requested)
        .on_conflict_do_nothing(index_elements=["user_id", "request_id"])
        .returning(QbSet.id)
    )
    if set_id is not None:
        return set_id, None
    found = (
        await session.execute(
            select(QbSet.id, QbSet.mode, QbSet.filters, QbSet.requested, QbSet.served).where(
                QbSet.user_id == user_id, QbSet.request_id == request_id
            )
        )
    ).one()
    await session.rollback()
    if found.mode != mode or found.filters != spec:
        raise Conflict("This request id was already used for a different set.", code="request_reused")
    replay = {
        "status": "partial" if mode == "test" and found.served < found.requested else "created",
        "set_id": found.id,
        "requested": found.requested,
        "served": found.served,
        "replayed": True,
    }
    return found.id, replay


async def create_test(
    session: AsyncSession,
    user_id: uuid.UUID,
    request_id: uuid.UUID,
    filters: dict[str, Any],
    distribution: dict[str, int],
    *,
    allow_partial: bool = False,
) -> dict[str, Any]:
    """A test: the requested number of questions per difficulty, all at once."""
    f = parse_filters(filters)
    if set(distribution) - set(QB_DIFFICULTIES) or not all(
        isinstance(n, int) and n >= 0 for n in distribution.values()
    ):
        raise ValidationFailed("distribution counts easy, medium and hard questions.")
    requested = sum(distribution.values())
    if not 1 <= requested <= MAX_SET:
        raise ValidationFailed(f"A test has 1-{MAX_SET} questions.")
    spec = {"filters": asdict(f), "distribution": distribution, "allow_partial": allow_partial}
    set_id, replay = await _claim(session, user_id, request_id, "test", spec, requested)
    if replay:
        return replay
    await _check_scope(session, f)
    picked: list[tuple[str, str]] = []
    shortage = {}
    for difficulty in QB_DIFFICULTIES:
        wanted = distribution.get(difficulty, 0)
        if wanted:
            rows, available = await _pool(session, f, user_id, str(set_id), difficulty, wanted)
            if available < wanted:
                shortage[difficulty] = {"requested": wanted, "available": available}
            picked += rows
    if shortage and (not allow_partial or not picked):
        await session.rollback()
        return {"status": "shortage", "buckets": shortage}
    await session.execute(
        insert(QbSetItem),
        [
            {"set_id": set_id, "position": position, "user_id": user_id, "question_id": question_id, "topic_id": topic}
            for position, (question_id, topic) in enumerate(picked, 1)
        ],
    )
    await session.execute(update(QbSet).where(QbSet.id == set_id).values(served=len(picked)))
    await session.commit()
    return {
        "status": "partial" if shortage else "created",
        "set_id": set_id,
        "requested": requested,
        "served": len(picked),
        "buckets": shortage,
    }


async def create_adaptive(
    session: AsyncSession,
    user_id: uuid.UUID,
    request_id: uuid.UUID,
    filters: dict[str, Any],
    length: int,
    *,
    allow_partial: bool = False,
) -> dict[str, Any]:
    """An adaptive practice set in one topic: `length` questions, served one at a time by next_item."""
    f = parse_filters(filters)
    if f.topic_id is None:
        raise ValidationFailed("Adaptive practice needs a topic_id.")
    if not isinstance(length, int) or not 1 <= length <= MAX_SET:
        raise ValidationFailed(f"An adaptive set has 1-{MAX_SET} questions.")
    spec = {"filters": asdict(f), "length": length, "allow_partial": allow_partial}
    set_id, replay = await _claim(session, user_id, request_id, "adaptive", spec, length)
    if replay:
        return replay
    await _check_scope(session, f)
    available = await session.scalar(select(func.count()).where(*_eligible(f, user_id)))
    if available < length and (not allow_partial or not available):
        await session.rollback()
        return {"status": "shortage", "buckets": {"any": {"requested": length, "available": available}}}
    await session.commit()
    return {"status": "created", "set_id": set_id, "requested": length, "served": 0}


# The next question from a pool of topics, from the student's previous answer:
#   no history -> medium, the weakest (untried) concept | wrong -> one level easier, same concept
#   right with a hint -> same level, same concept      | right, no hint -> one level harder, weakest other concept
#   skipped -> same level, another concept (a skip is not an answer: no step down)
# "Previous" is the set's question at :previous_position when one is given (a test in the chat), else the
# student's latest answer in the pool (any set). A concept is a topic's: (topic_id, concept_tag). Unseen
# questions first; never twice in one set; never the previous question while anything else is left; ties
# by md5(seed || question id). `available` counts what the pool has left for the set. Index ranges only
# (ix_qb_set_items_user_id_topic_id_answered_at, ix_qb_questions_adaptive).
ADAPTIVE_PICK = text(
    """
    WITH history AS (
        SELECT i.question_id, i.is_correct, i.hinted, i.answered_at, q.level,
               q.topic_id || ' ' || q.concept_tag AS concept
        FROM qb_set_items i JOIN qb_questions q ON q.question_id = i.question_id
        WHERE i.user_id = :user_id AND i.topic_id = ANY(CAST(:topic_ids AS text[])) AND i.answered_at IS NOT NULL
    ), last AS (
        SELECT i.question_id, i.is_correct, i.hinted, i.answered_at IS NULL AS skipped, q.level,
               q.topic_id || ' ' || q.concept_tag AS concept
        FROM qb_set_items i JOIN qb_questions q ON q.question_id = i.question_id
        WHERE i.set_id = :set_id AND i.user_id = :user_id AND i.position = CAST(:previous_position AS integer)
        UNION ALL
        (SELECT question_id, is_correct, hinted, false, level, concept FROM history
         WHERE CAST(:previous_position AS integer) IS NULL ORDER BY answered_at DESC LIMIT 1)
    ), target AS (
        SELECT CASE WHEN l.level IS NULL THEN 2
                    WHEN l.skipped THEN l.level
                    WHEN NOT l.is_correct THEN greatest(l.level - 1, 1)
                    WHEN l.hinted THEN l.level
                    ELSE least(l.level + 1, 3) END AS level,
               CASE WHEN NOT l.skipped AND (NOT l.is_correct OR l.hinted) THEN l.concept END AS same_concept,
               CASE WHEN l.skipped OR (l.is_correct AND NOT l.hinted) THEN l.concept END AS other_than,
               l.question_id AS previous
        FROM (VALUES (1)) AS one (x) LEFT JOIN last l ON true
    ), accuracy AS (
        SELECT concept, (count(*) FILTER (WHERE is_correct) + 1)::real / (count(*) + 2) AS score
        FROM history GROUP BY concept
    ), seen AS (
        SELECT DISTINCT ON (question_id) question_id, is_correct AS last_correct, answered_at AS last_at
        FROM history ORDER BY question_id, answered_at DESC
    )
    SELECT q.question_id, q.topic_id, q.concept_tag, q.level, q.difficulty, q.stem, q.option_a, q.option_b,
           q.option_c, q.option_d, q.correct_option, q.explanation, c.title AS case_title, c.body AS case_body,
           count(*) OVER () AS available
    FROM qb_questions q
    CROSS JOIN LATERAL (SELECT q.topic_id || ' ' || q.concept_tag AS concept) k
    CROSS JOIN target t
    LEFT JOIN qb_cases c ON c.case_id = q.case_id
    LEFT JOIN accuracy a ON a.concept = k.concept
    LEFT JOIN seen s ON s.question_id = q.question_id
    WHERE q.review_status IN ('approved', 'needs_review') AND q.is_active
      AND q.topic_id = ANY(CAST(:topic_ids AS text[])) AND q.language = :language
      AND q.class_level = :class_level AND q.subject_code = :subject_code
      AND (CAST(:syllabus_version AS text) IS NULL OR q.syllabus_version = :syllabus_version)
      AND (CAST(:difficulty AS text) IS NULL OR q.difficulty = :difficulty)
      AND (NOT CAST(:card AS boolean) OR (
          length(q.stem) + coalesce(length(c.title) + length(c.body) + 9, 0) <= 1000
          AND greatest(length(q.option_a), length(q.option_b), length(q.option_c), length(q.option_d)) <= 400
          AND length(q.explanation) <= 2000))
      AND NOT EXISTS (SELECT 1 FROM qb_set_items x WHERE x.set_id = :set_id AND x.question_id = q.question_id)
    ORDER BY s.question_id IS NOT NULL,
             q.question_id IS NOT DISTINCT FROM t.previous,
             abs(q.level - t.level),
             k.concept IS DISTINCT FROM coalesce(t.same_concept, k.concept),
             coalesce(k.concept = t.other_than, false),
             coalesce(a.score, 0.5),
             s.last_correct NULLS FIRST,
             s.last_at NULLS FIRST,
             md5(CAST(:seed AS text) || q.question_id)
    LIMIT 1
    """
)


@dataclass(frozen=True)
class Pool:
    """Where the next question comes from: these topics of one class, subject and language (and one
    syllabus version and difficulty, when given). `card`: only questions the chat's quiz card can show
    (app/assessments/state.py limits; the few longest case questions are left out)."""

    language: str
    class_level: int
    subject_code: str
    topic_ids: tuple[str, ...]
    syllabus_version: str | None = None
    difficulty: str | None = None
    card: bool = False


async def pick_next(
    session: AsyncSession,
    user_id: uuid.UUID,
    pool: Pool,
    seed: str,
    set_id: uuid.UUID | None = None,
    previous_position: int | None = None,
) -> Any:
    """The question to serve next (ADAPTIVE_PICK) with its content and key, and how many the pool has
    left for the set (`available`); None when it has none. Only reads; never commits."""
    return (
        await session.execute(
            ADAPTIVE_PICK,
            {
                "user_id": user_id,
                "set_id": set_id,
                "seed": seed,
                "previous_position": previous_position,
                "topic_ids": list(pool.topic_ids),
                "language": pool.language,
                "class_level": pool.class_level,
                "subject_code": pool.subject_code,
                "syllabus_version": pool.syllabus_version,
                "difficulty": pool.difficulty,
                "card": pool.card,
            },
        )
    ).one_or_none()


ITEM = text(
    """
    SELECT i.position, q.question_id, q.topic_id, q.difficulty, q.question_format, q.marks,
           c.title AS case_title, c.body AS case_body, q.stem, q.option_a, q.option_b, q.option_c, q.option_d,
           i.answered_at IS NOT NULL AS answered
    FROM qb_set_items i
    JOIN qb_questions q ON q.question_id = i.question_id
    LEFT JOIN qb_cases c ON c.case_id = q.case_id
    WHERE i.set_id = :set_id AND i.position = :position AND i.user_id = :user_id
    """
)


async def _item(session: AsyncSession, user_id: uuid.UUID, set_id: uuid.UUID, position: int) -> dict[str, Any]:
    row = (await session.execute(ITEM, {"set_id": set_id, "position": position, "user_id": user_id})).mappings().one()
    item = {name: row[name] for name in row if not name.startswith("option_")}
    item["options"] = [row["option_a"], row["option_b"], row["option_c"], row["option_d"]]
    return item


async def next_item(session: AsyncSession, user_id: uuid.UUID, set_id: uuid.UUID) -> dict[str, Any]:
    """The adaptive set's open question, or a new one chosen now; never two open at once."""
    found = (
        await session.execute(
            select(QbSet.mode, QbSet.requested, QbSet.served, QbSet.filters, QbSet.closed_at)
            .where(QbSet.id == set_id, QbSet.user_id == user_id)
            .with_for_update()
        )
    ).one_or_none()
    if found is None:
        await session.rollback()
        raise NotFound()
    if found.mode != "adaptive":
        await session.rollback()
        raise Conflict("A test is served whole, not one question at a time.", code="not_adaptive")
    open_position = await session.scalar(
        select(QbSetItem.position).where(QbSetItem.set_id == set_id, QbSetItem.answered_at.is_(None))
    )
    if open_position is not None:
        item = await _item(session, user_id, set_id, open_position)
        await session.commit()
        return {"status": "open", "item": item}
    if found.closed_at is not None or found.served >= found.requested:
        await session.commit()
        return {"status": "finished"}
    f = Filters(**found.filters["filters"])
    pool = Pool(f.language, f.class_level, f.subject_code, (f.topic_id,), f.syllabus_version)
    picked = await pick_next(session, user_id, pool, str(set_id), set_id)  # from the latest answer in the topic
    if picked is None:
        await session.rollback()
        return {"status": "shortage", "available": 0}
    position = found.served + 1
    await session.execute(
        insert(QbSetItem).values(
            set_id=set_id, position=position, user_id=user_id, question_id=picked.question_id, topic_id=picked.topic_id
        )
    )
    await session.execute(update(QbSet).where(QbSet.id == set_id).values(served=position))
    item = await _item(session, user_id, set_id, position)
    await session.commit()
    return {"status": "served", "item": item}


async def items(session: AsyncSession, user_id: uuid.UUID, set_id: uuid.UUID) -> list[dict[str, Any]]:
    """Every served question of a set, without keys."""
    positions = (
        await session.scalars(
            select(QbSetItem.position)
            .where(QbSetItem.set_id == set_id, QbSetItem.user_id == user_id)
            .order_by(QbSetItem.position)
        )
    ).all()
    if (
        not positions
        and await session.scalar(select(QbSet.id).where(QbSet.id == set_id, QbSet.user_id == user_id)) is None
    ):
        raise NotFound()
    return [await _item(session, user_id, set_id, position) for position in positions]


async def _key(session: AsyncSession, question_id: str) -> dict[str, str]:
    row = (
        await session.execute(
            select(QbQuestion.correct_option, QbQuestion.explanation).where(QbQuestion.question_id == question_id)
        )
    ).one()
    return {"correct_option": row.correct_option, "explanation": row.explanation}


async def answer(
    session: AsyncSession,
    user_id: uuid.UUID,
    set_id: uuid.UUID,
    position: int,
    chosen: str,
    *,
    hinted: bool = False,
) -> dict[str, Any]:
    """Answer a served question once. The same answer again returns the first result."""
    if chosen not in ("A", "B", "C", "D") or not isinstance(hinted, bool):
        raise ValidationFailed("chosen is one of A, B, C, D.")
    set_open = select(QbSet.id).where(QbSet.id == QbSetItem.set_id, QbSet.closed_at.is_(None)).exists()
    recorded = (
        await session.execute(
            update(QbSetItem)
            .where(
                QbSetItem.set_id == set_id,
                QbSetItem.position == position,
                QbSetItem.user_id == user_id,
                QbSetItem.answered_at.is_(None),
                set_open,
            )
            .values(chosen=chosen, hinted=hinted)
            .returning(QbSetItem.question_id, QbSetItem.is_correct)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    replayed = recorded is None
    if replayed:
        found = (
            await session.execute(
                select(QbSetItem.question_id, QbSetItem.chosen, QbSetItem.hinted, QbSetItem.is_correct).where(
                    QbSetItem.set_id == set_id, QbSetItem.position == position, QbSetItem.user_id == user_id
                )
            )
        ).one_or_none()
        if found is None:
            await session.rollback()
            raise NotFound()
        if found.chosen is None:
            await session.rollback()
            raise Conflict("This set is closed.", code="set_closed")
        if (found.chosen, found.hinted) != (chosen, hinted):
            await session.rollback()
            raise Conflict("This question was already answered differently.", code="already_answered")
        recorded = found
    mode = await session.scalar(select(QbSet.mode).where(QbSet.id == set_id))
    result: dict[str, Any] = {"set_id": set_id, "position": position, "replayed": replayed}
    if mode == "adaptive":
        result |= {"is_correct": recorded.is_correct, **await _key(session, recorded.question_id)}
    await session.commit()
    return result


async def close_set(session: AsyncSession, user_id: uuid.UUID, set_id: uuid.UUID) -> dict[str, Any]:
    closed = await session.scalar(
        update(QbSet)
        .where(QbSet.id == set_id, QbSet.user_id == user_id, QbSet.closed_at.is_(None))
        .values(closed_at=func.clock_timestamp())
        .returning(QbSet.closed_at)
    )
    if closed is None:
        closed = await session.scalar(select(QbSet.closed_at).where(QbSet.id == set_id, QbSet.user_id == user_id))
        if closed is None:
            await session.rollback()
            raise NotFound()
    await session.commit()
    return {"set_id": set_id, "closed_at": closed}


async def results(session: AsyncSession, user_id: uuid.UUID, set_id: uuid.UUID) -> dict[str, Any]:
    """Score, answers, keys and explanations: an adaptive set at any time; a test once closed or
    fully answered."""
    found = (
        await session.execute(select(QbSet.mode, QbSet.closed_at).where(QbSet.id == set_id, QbSet.user_id == user_id))
    ).one_or_none()
    if found is None:
        raise NotFound()
    rows = (
        (
            await session.execute(
                select(
                    QbSetItem.position,
                    QbSetItem.question_id,
                    QbSetItem.chosen,
                    QbSetItem.is_correct,
                    QbQuestion.correct_option,
                    QbQuestion.explanation,
                )
                .join(QbQuestion, QbQuestion.question_id == QbSetItem.question_id)
                .where(QbSetItem.set_id == set_id, QbSetItem.user_id == user_id)
                .order_by(QbSetItem.position)
            )
        )
        .mappings()
        .all()
    )
    if found.mode == "test" and found.closed_at is None and any(row["chosen"] is None for row in rows):
        raise Conflict("Results come once the test is closed or every question is answered.", code="not_finished")
    return {
        "set_id": set_id,
        "answered": sum(row["chosen"] is not None for row in rows),
        "correct": sum(bool(row["is_correct"]) for row in rows),
        "items": [dict(row) for row in rows],
    }


CONCEPT_ACCURACY = text(
    """
    SELECT q.topic_id, q.concept_tag, count(*) AS answered, count(*) FILTER (WHERE i.is_correct) AS correct,
           round((count(*) FILTER (WHERE i.is_correct) + 1)::numeric / (count(*) + 2), 2) AS smoothed_accuracy
    FROM qb_set_items i JOIN qb_questions q ON q.question_id = i.question_id
    WHERE i.user_id = :user_id AND q.chapter_id = :chapter_id AND i.answered_at IS NOT NULL
    GROUP BY q.topic_id, q.concept_tag
    ORDER BY smoothed_accuracy, q.topic_id, q.concept_tag
    """
)


async def concept_accuracy(session: AsyncSession, user_id: uuid.UUID, chapter_id: str) -> list[dict[str, Any]]:
    """Per concept, weakest first: smoothed accuracy, a practice signal (not "mastery")."""
    rows = await session.execute(CONCEPT_ACCURACY, {"user_id": user_id, "chapter_id": chapter_id})
    return [dict(row) for row in rows.mappings()]


COVERAGE = text(
    """
    SELECT b.class_level, b.subject_code, b.book_id, b.title AS book_title, b.language, c.chapter_number,
           c.chapter_id, c.title AS chapter_title, c.question_count, c.max_questions, t.topic_number, t.topic_id,
           t.title AS topic_title,
           count(q.question_id) AS stored,
           count(*) FILTER (WHERE q.difficulty = 'easy') AS stored_easy,
           count(*) FILTER (WHERE q.difficulty = 'medium') AS stored_medium,
           count(*) FILTER (WHERE q.difficulty = 'hard') AS stored_hard,
           count(*) FILTER (WHERE q.review_status = 'approved' AND q.is_active) AS approved,
           count(*) FILTER (WHERE q.review_status IN ('draft', 'needs_review') AND q.is_active) AS unreviewed,
           count(*) FILTER (WHERE q.review_status = 'rejected') AS rejected,
           count(*) FILTER (WHERE q.review_status = 'approved' AND q.is_active AND q.difficulty = 'easy')
               AS approved_easy,
           count(*) FILTER (WHERE q.review_status = 'approved' AND q.is_active AND q.difficulty = 'medium')
               AS approved_medium,
           count(*) FILTER (WHERE q.review_status = 'approved' AND q.is_active AND q.difficulty = 'hard')
               AS approved_hard,
           CASE WHEN t.topic_id IS NULL THEN 'topics_missing'
                WHEN count(q.question_id) = 0 THEN 'missing'
                WHEN count(*) FILTER (WHERE q.review_status = 'approved' AND q.is_active) >= :target
                     THEN 'complete'
                WHEN count(*) FILTER (WHERE q.review_status IN ('approved', 'draft', 'needs_review')
                                        AND q.is_active) >= :target
                     THEN 'awaiting_review'
                ELSE 'underfilled' END AS status,
           greatest(:target - count(*) FILTER (WHERE q.review_status = 'approved' AND q.is_active), 0) AS shortfall
    FROM qb_books b
    JOIN qb_chapters c ON c.book_id = b.book_id
    LEFT JOIN qb_topics t ON t.chapter_id = c.chapter_id
    LEFT JOIN qb_questions q ON q.topic_id = t.topic_id
    GROUP BY b.class_level, b.subject_code, b.book_id, b.title, b.language, c.chapter_number, c.chapter_id,
             c.title, c.question_count, c.max_questions, t.topic_number, t.topic_id, t.title
    ORDER BY b.class_level, b.subject_code, b.language, b.book_id, c.chapter_number, t.topic_number
    """
)
COUNTER_DRIFT = text(
    """
    SELECT c.chapter_id FROM qb_chapters c
    WHERE c.question_count <> (SELECT count(*) FROM qb_questions q WHERE q.chapter_id = c.chapter_id)
    """
)


async def coverage(session: AsyncSession, target: int = TARGET_PER_TOPIC) -> dict[str, Any]:
    """Per topic of every book in the bank: stored, approved and unreviewed questions, approved per
    difficulty, the status and the shortfall to `target`; and any chapter whose counter drifted."""
    rows = [dict(row) for row in (await session.execute(COVERAGE, {"target": target})).mappings()]
    drift = list((await session.scalars(COUNTER_DRIFT)).all())
    return {"target": target, "topics": rows, "counter_drift": drift}
