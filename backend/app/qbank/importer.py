"""Importing the bank's text files (qbank/) into PostgreSQL: one transaction, all or nothing, safe to rerun.

read_bank (validate.py) checks everything first; with any error nothing is written. Then, under an
advisory lock (a second import waits for the first):
- syllabus versions, books, chapters, topics, concepts and cases are inserted, or updated when
  they changed;
- each question is inserted, updated when its content or review changed, or left alone, so an
  unchanged rerun writes nothing;
- a question in the database but no longer in the files is reported, and retired (is_active =
  false) only with retire_missing. Nothing is ever deleted: answers point at questions.
A dry run does all of it and rolls back, so its report is exactly what an applied run does,
the database's own checks (the chapter cap among them) included.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import QbBook, QbCase, QbChapter, QbConcept, QbQuestion, QbSyllabusVersion, QbTopic
from app.qbank.validate import Bank, read_bank

IMPORT_LOCK = 7_301_015  # pg_advisory_xact_lock key: one import at a time


@dataclass
class ImportReport:
    applied: bool = False
    errors: list[str] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)  # question_id -> why it was sent to review
    counts: dict[str, dict[str, int]] = field(default_factory=dict)  # table -> inserted / updated / unchanged
    missing: list[str] = field(default_factory=list)  # in the database, not in the files
    retired: int = 0


async def import_bank(session: AsyncSession, root: Path, *, apply: bool, retire_missing: bool = False) -> ImportReport:
    bank = read_bank(root)
    report = ImportReport(errors=list(bank.errors), notes=dict(bank.notes))
    if bank.errors:
        return report
    try:
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": IMPORT_LOCK})
        await _write(session, bank, report, retire_missing)
    except DBAPIError as error:  # the database's own checks: the chapter cap, keys, duplicates
        await session.rollback()
        report.errors.append(f"refused by the database: {str(error.orig).splitlines()[0]}")
        return report
    if apply:
        await session.commit()
        report.applied = True
    else:
        await session.rollback()
    return report


async def _write(session: AsyncSession, bank: Bank, report: ImportReport, retire_missing: bool) -> None:
    versions = [
        {name: version[name] for name in ("code", "curriculum", "academic_session", "title", "source_url")}
        for version in bank.syllabus_versions.values()
    ]
    books = [
        {
            name: book[name]
            for name in ("book_id", "curriculum", "class_level", "subject_code", "language", "title", "edition")
        }
        for book in bank.books.values()
    ]
    chapters = [
        {
            "chapter_id": chapter_id,
            "book_id": chapter["book_id"],
            "chapter_number": chapter["chapter_number"],
            "old_chapter_number": chapter.get("old_chapter_number"),
            "title": chapter["title"],
            "ncert_chapter_id": chapter.get("ncert_chapter_id"),
            "max_questions": chapter["max_questions"],
        }
        for chapter_id, chapter in bank.chapters.items()
    ]
    topics = [
        {
            "topic_id": topic_id,
            "chapter_id": topic["chapter_id"],
            "topic_number": topic["topic_number"],
            "title": topic["title"],
            "ncert_sections": topic.get("ncert_sections"),
        }
        for topic_id, topic in bank.topics.items()
    ]
    concepts = [
        {"topic_id": topic_id, "concept_tag": tag, "learning_objective": concept["learning_objective"]}
        for (topic_id, tag), concept in bank.concepts.items()
    ]
    cases = [{name: case[name] for name in ("case_id", "topic_id", "title", "body")} for case in bank.cases.values()]
    await _sync(session, QbSyllabusVersion, ("code",), versions, report)
    await _sync(session, QbBook, ("book_id",), books, report)
    await _sync(session, QbChapter, ("chapter_id",), chapters, report)
    await _sync(session, QbTopic, ("topic_id",), topics, report)
    await _sync(session, QbConcept, ("topic_id", "concept_tag"), concepts, report)
    await _sync(session, QbCase, ("case_id",), cases, report)
    await _sync(session, QbQuestion, ("question_id",), bank.rows, report)

    in_files = {row["question_id"] for row in bank.rows}
    stored = await session.scalars(
        select(QbQuestion.question_id).where(
            QbQuestion.chapter_id.in_(list(bank.chapters)), QbQuestion.is_active.is_(True)
        )
    )
    report.missing = sorted(set(stored) - in_files)
    if retire_missing and report.missing:
        result = await session.execute(
            update(QbQuestion)
            .where(QbQuestion.question_id.in_(report.missing))
            .values(is_active=False, updated_at=func.clock_timestamp())
        )
        report.retired = result.rowcount
    # Fresh statistics with the new rows: without them the planner picks nested loops for the adaptive
    # query right after a large import (measured: 159 ms instead of 10 on the test machine).
    await session.execute(text("ANALYZE qb_questions, qb_chapters, qb_topics, qb_concepts, qb_cases"))


async def _sync(
    session: AsyncSession, model: Any, key: tuple[str, ...], rows: list[dict], report: ImportReport
) -> None:
    """Insert new rows and update changed ones (changes first, so a value a row gives up is free for
    a new one); unchanged rows are not written."""
    counts = {"inserted": 0, "updated": 0, "unchanged": 0}
    report.counts[model.__tablename__] = counts
    if not rows:
        return
    columns = list(rows[0])
    keys = [tuple(row[name] for name in key) for row in rows]
    existing = {}
    for start in range(0, len(keys), 1000):
        result = await session.execute(
            select(*(getattr(model, name) for name in columns)).where(
                tuple_(*(getattr(model, name) for name in key)).in_(keys[start : start + 1000])
            )
        )
        for found in result.mappings():
            existing[tuple(found[name] for name in key)] = dict(found)
    new = [row for row, row_key in zip(rows, keys, strict=True) if row_key not in existing]
    changed = [row for row, row_key in zip(rows, keys, strict=True) if row_key in existing and existing[row_key] != row]
    for row in changed:
        values = {**row, "updated_at": func.clock_timestamp()} if model is QbQuestion else row
        await session.execute(
            update(model).where(*(getattr(model, name) == row[name] for name in key)).values(**values)
        )
    if new:
        await session.execute(insert(model), new)
    counts.update(inserted=len(new), updated=len(changed), unchanged=len(rows) - len(new) - len(changed))
