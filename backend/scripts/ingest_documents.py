"""Ingest .md/.txt files into the knowledge base (PostgreSQL + pgvector), or delete one document.

    python scripts/ingest_documents.py --source handbook --global docs/handbook/
    python scripts/ingest_documents.py --source my-notes --owner-email me@example.com notes.md
    python scripts/ingest_documents.py --source handbook --global --metadata lang=en docs/handbook/
    python scripts/ingest_documents.py --source handbook --delete guide/intro.md

Visibility is mandatory: --global (every signed-in user can retrieve it) or --owner-email
(only that user). URIs: files inside a directory argument are named relative to it; a file
argument is named by its file name. Re-running is safe: unchanged documents are skipped,
changed ones are re-embedded and replaced atomically. Prints counts only, never content.
Uses DATABASE_URL and EMBEDDING_* from the environment / .env. Never point it at
production without an approved plan.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _metadata(pairs: list[str]) -> dict[str, str]:
    result = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise SystemExit(f"--metadata expects key=value, got {pair!r}")
        result[key.strip()] = value.strip()
    return result


async def run(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from app.db.models import User
    from app.db.session import Database
    from app.rag.embeddings import build_embeddings
    from app.rag.errors import RagError
    from app.rag.ingestion import IngestionService, IngestReport, IngestResult, collect_files, parse_document
    from app.rag.store import KnowledgeStore
    from app.settings import get_settings

    settings = get_settings()
    db = Database(settings)
    store = KnowledgeStore(db, settings.rag_hnsw_ef_search)
    try:
        if args.delete:
            deleted = await store.delete_document(args.source, args.delete)
            print(f"deleted: {deleted}")
            return 0 if deleted else 1

        owner_id = None
        if args.owner_email:
            async with db.sessionmaker() as session:
                owner_id = await session.scalar(select(User.id).where(User.email == args.owner_email))
            if owner_id is None:
                print("no user with that email")
                return 1
        try:
            source = await store.get_or_create_source(args.source, owner_user_id=owner_id, description=args.description)
        except RagError as error:
            print(f"cannot use source: {error.code}")
            return 1

        service = IngestionService(store, build_embeddings(settings), settings)
        metadata = _metadata(args.metadata)
        report = IngestReport()
        for uri, path in collect_files([Path(p) for p in args.paths]):
            try:
                document = parse_document(
                    uri,
                    await asyncio.to_thread(path.read_bytes),
                    max_bytes=settings.rag_max_document_bytes,
                    metadata=metadata,
                )
            except RagError as error:
                report.results.append(
                    IngestResult(uri, "skipped" if error.code == "unsupported_type" else "failed", error.code)
                )
                continue
            report.results.append(await service.ingest(source.id, document))

        for result in report.results:
            if result.status in ("failed", "skipped"):
                print(f"{result.status:9} {result.uri}  ({result.reason})")
        counts = {s: report.count(s) for s in ("created", "replaced", "unchanged", "skipped", "failed")}
        chunks = sum(r.chunks for r in report.results)
        print(
            f"source={args.source} visibility={'private' if owner_id else 'global'} "
            + " ".join(f"{k}={v}" for k, v in counts.items())
            + f" chunks_written={chunks}"
        )
        return 0 if report.ok else 1
    finally:
        await db.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, help="knowledge source name")
    parser.add_argument("--description")
    visibility = parser.add_mutually_exclusive_group()
    visibility.add_argument("--global", dest="is_global", action="store_true", help="visible to every signed-in user")
    visibility.add_argument("--owner-email", help="visible only to this user")
    parser.add_argument("--metadata", action="append", default=[], help="document attribute key=value (repeatable)")
    parser.add_argument("--delete", metavar="URI", help="delete one document from the source")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    if not args.delete:
        if not (args.is_global or args.owner_email):
            parser.error("choose visibility explicitly: --global or --owner-email")
        if not args.paths:
            parser.error("give at least one file or directory")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
