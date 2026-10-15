"""Coverage of the question bank, read from the database (read-only).

    python scripts/qbank_coverage.py           # a summary and one line per topic
    python scripts/qbank_coverage.py --json    # the same as JSON

Per topic of every book in the bank: questions stored, approved (servable) and unreviewed,
approved per difficulty, and its status: complete (at least --target approved), awaiting_review
(enough stored, not enough approved), underfilled, missing (no questions) or topics_missing (a
chapter with no topics yet). Also each chapter's use of its question limit, and any chapter whose
counter disagrees with its rows (there should be none). Real counts only: a book that is not in a
manifest yet is not in the bank at all.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run(args: argparse.Namespace) -> int:
    from sqlalchemy import text

    from app.db.session import Database
    from app.qbank.selection import coverage
    from app.settings import get_settings

    db = Database(get_settings())
    try:
        async with db.sessionmaker() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            report = await coverage(session, args.target)
            await session.rollback()
    finally:
        await db.dispose()
    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0
    if args.markdown:
        print(markdown(report))
        return 1 if report["counter_drift"] else 0
    topics = report["topics"]
    print(f"target: {report['target']} approved questions per topic")
    print("topics by status:", dict(Counter(row["status"] for row in topics)) or "none")
    chapters = {row["chapter_id"]: row for row in topics}
    for chapter in chapters.values():
        print(
            f"{chapter['book_id']} ({chapter['language']}) ch {chapter['chapter_number']} {chapter['chapter_id']}: "
            f"{chapter['question_count']}/{chapter['max_questions']} questions stored"
        )
    for row in topics:
        if row["topic_id"] is not None:
            print(
                f"  {row['topic_id']}: {row['status']}, stored {row['stored']}, approved {row['approved']} "
                f"(easy {row['approved_easy']}, medium {row['approved_medium']}, hard {row['approved_hard']}), "
                f"unreviewed {row['unreviewed']}, shortfall {row['shortfall']}"
            )
    if report["counter_drift"]:
        print("COUNTER DRIFT:", ", ".join(report["counter_drift"]))
        return 1
    return 0


def _difficulties(row: dict, kind: str) -> str:
    return f"{row[kind]} ({row[kind + '_easy']}/{row[kind + '_medium']}/{row[kind + '_hard']})"


def markdown(report: dict) -> str:
    """Every class, subject, book, chapter and topic in the bank, with counts by difficulty and review
    status, and every gap."""
    rows, target = report["topics"], report["target"]
    chapters: dict[str, list[dict]] = {}
    for row in rows:
        chapters.setdefault(row["chapter_id"], []).append(row)
    per_subject: dict[tuple, Counter] = {}
    for chapter_rows in chapters.values():
        first = chapter_rows[0]
        tally = per_subject.setdefault((first["class_level"], first["subject_code"]), Counter())
        tally["chapters"] += 1
        with_topics = [row for row in chapter_rows if row["topic_id"] is not None]
        tally["chapters_with_topics"] += bool(with_topics)
        tally["chapters_complete"] += bool(with_topics) and all(row["status"] == "complete" for row in with_topics)
        tally["topics"] += len(with_topics)
        tally["topics_complete"] += sum(row["status"] == "complete" for row in with_topics)
        tally["stored"] += sum(row["stored"] for row in chapter_rows)
        tally["approved"] += sum(row["approved"] for row in chapter_rows)
        tally["unreviewed"] += sum(row["unreviewed"] for row in chapter_rows)
    books = {row["book_id"] for row in rows}
    total = sum(per_subject.values(), Counter())
    out = [
        "# Question bank coverage",
        "",
        f"Generated from the database by `backend/scripts/qbank_coverage.py --markdown`. A topic is complete "
        f"only with at least {target} approved, active questions; unreviewed questions never count. Stored "
        "counts are shown as total (easy/medium/hard).",
        "",
        f"**Totals:** {len(books)} books, {total['chapters']} chapters, of which {total['chapters_with_topics']} "
        f"have topics and {total['chapters_complete']} are complete; {total['topics']} topics, "
        f"{total['topics_complete']} complete; {total['stored']} questions stored, {total['approved']} approved, "
        f"{total['unreviewed']} awaiting review.",
        "",
        "Topic statuses: "
        + ", ".join(f"{status} {count}" for status, count in Counter(r["status"] for r in rows).items()),
        "",
        "## By class and subject",
        "",
        "| Class | Subject | Chapters | With topics | Complete | Topics | Complete topics | Stored | Approved |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for (level, subject), tally in sorted(per_subject.items()):
        out.append(
            f"| {level} | {subject} | {tally['chapters']} | {tally['chapters_with_topics']} | "
            f"{tally['chapters_complete']} | {tally['topics']} | {tally['topics_complete']} | {tally['stored']} | "
            f"{tally['approved']} |"
        )
    current = None
    for chapter_rows in chapters.values():
        first = chapter_rows[0]
        if (first["class_level"], first["subject_code"], first["book_id"]) != current:
            current = (first["class_level"], first["subject_code"], first["book_id"])
            out += [
                "",
                f"## Class {first['class_level']} · {first['subject_code']} · {first['book_title']} "
                f"(`{first['book_id']}`, {first['language']})",
                "",
                "| Chapter | Topic | Stored | Approved | Unreviewed | Status | Gap |",
                "|---|---|---|---|---|---|---|",
            ]
        title = (
            f"{first['chapter_number']}. {first['chapter_title']} ({first['question_count']}/{first['max_questions']})"
        )
        if first["topic_id"] is None:
            out.append(f"| {title} | — | 0 | 0 | 0 | topics missing | topics and all questions |")
            continue
        for row in chapter_rows:
            gap = "" if row["status"] == "complete" else f"{row['shortfall']} approved"
            out.append(
                f"| {title} | {row['topic_number']}. {row['topic_title']} | {_difficulties(row, 'stored')} | "
                f"{_difficulties(row, 'approved')} | {row['unreviewed']} | {row['status']} | {gap} |"
            )
            title = ""
    if report["counter_drift"]:
        out += ["", "**COUNTER DRIFT:** " + ", ".join(report["counter_drift"])]
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true", help="the full report: every class to every topic")
    parser.add_argument("--target", type=int, default=5, help="approved questions a topic needs (default 5)")
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
