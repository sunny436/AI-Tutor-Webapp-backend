"""Import the question bank's text files (qbank/) into PostgreSQL, or only check them.

    python scripts/import_questions.py ../qbank                              # dry run
    python scripts/import_questions.py ../qbank --apply                      # write
    python scripts/import_questions.py ../qbank --apply --retire-missing     # also retire removed questions
    python scripts/import_questions.py ../qbank --hashes                     # for reviewers (no database)

A dry run checks every file and imports everything in a transaction that is rolled back, so it
reports exactly what --apply would do, the database's own checks included. All or nothing: any
error and nothing is written. Rerunning changes only what changed in the files. Prints counts,
errors and review notes, never question text (docs/question_bank.md). Uses DATABASE_URL from the
environment / .env; never point it at production without an approved plan. On the host:

    systemd-run --pipe --wait --collect -p EnvironmentFile=/etc/aichat/api.env \\
        -p WorkingDirectory=/opt/aichat/app/backend \\
        /opt/aichat/app/backend/.venv/bin/python scripts/import_questions.py ../qbank
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def hashes(root: Path) -> int:
    """For reviewers: each question's content hash, to record with an approval (review.hash).
    Reads the files only."""
    from app.qbank.validate import read_bank

    bank = read_bank(root)
    for error in bank.errors:
        print(f"ERROR   {error}")
    for row in bank.rows:
        print(row["question_id"], row["content_hash"])
    return 1 if bank.errors else 0


async def run(args: argparse.Namespace) -> int:
    if args.hashes:
        return hashes(Path(args.root))
    from app.db.session import Database
    from app.qbank.importer import import_bank
    from app.settings import get_settings

    db = Database(get_settings())
    try:
        async with db.sessionmaker() as session:
            report = await import_bank(session, Path(args.root), apply=args.apply, retire_missing=args.retire_missing)
    finally:
        await db.dispose()
    for error in report.errors:
        print(f"ERROR   {error}")
    for question_id, note in sorted(report.notes.items()):
        print(f"REVIEW  {question_id}: {note}")
    for table, counts in report.counts.items():
        print(f"{table}: {counts['inserted']} inserted, {counts['updated']} updated, {counts['unchanged']} unchanged")
    if report.missing:
        print(f"in the database, not in the files: {len(report.missing)} (retired: {report.retired})")
    print("APPLIED" if report.applied else "NOT APPLIED" + (" (dry run)" if not report.errors else ""))
    return 1 if report.errors else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root", help="the qbank directory (manifest/ and content/)")
    parser.add_argument("--apply", action="store_true", help="commit (default: a dry run)")
    parser.add_argument("--retire-missing", action="store_true", help="retire questions no longer in the files")
    parser.add_argument("--hashes", action="store_true", help="print each question's content hash (no database)")
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
