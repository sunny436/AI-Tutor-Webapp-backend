r"""
migrate_user_document_ids.py
----------------------------
Repoint uploaded-report chunks from the old `userId|sessionId` owner to `userId`.

WHY THIS EXISTS
`server.verify_token` used to return the WHOLE Convex Auth subject as the user
id. Convex Auth joins two ids with "|":

    "m572jrdvnt10jr7d25e9nhke098dg7rv|js7cfyj9z922v5j2f7kbbkfhkd8dhhhb"
     \______________ user ___________/ \____________ session ________/

`user_documents` stamps that value onto every chunk it indexes and filters every
search by it, so each chunk is owned by ONE LOGIN rather than by a person. Two
consequences, both already live:

  - a user who signs out and back in cannot see their own earlier reports;
  - re-uploading the same file then writes a SECOND copy, because
    `remove_document` also filters on the composite value and matches nothing.

Commit `fca0909` fixes `verify_token`. That alone leaves every previously
indexed chunk stranded under an owner nobody will ever present again. This
script moves them.

WHAT IT CHANGES, EXACTLY
One metadata field, `user_id`, on chunks whose value contains "|", in the
`user_documents` collection only. Nothing else: not the text, not the
embedding, not `filename`, not `chunk`, not the chunk id, and never the
`ayurveda_yoga` collection.

CHUNK IDS ARE DELIBERATELY LEFT ALONE. They are `sha1(user_id:filename:index)`,
so after this runs they no longer match what `_chunk_id` would compute. That is
harmless: ids only need to be unique and stable, and every path that removes or
replaces a document (`remove_document`, and `index_document` which calls it
first) selects by a `where` filter on the metadata, not by id. The next upload
of the same file therefore still replaces cleanly, and the ids converge on
their own.

    python scripts/migrate_user_document_ids.py            # dry run, default
    python scripts/migrate_user_document_ids.py --apply
    python scripts/migrate_user_document_ids.py --apply --dedup
    python scripts/migrate_user_document_ids.py --rollback <backup.json>

Reads VECTOR_DB_DIR the same way the app does, so it always operates on the
store the backend is actually using.
"""

from __future__ import annotations

import argparse
import collections
import datetime as _dt
import hashlib
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

import config  # noqa: E402

COLLECTION = "user_documents"
DIVIDER = "|"


def _open():
    """The collection, through chromadb directly.

    Not through `user_documents.get_store()`: that builds an embedding function
    and would need a live embeddings key to open a store this script only reads
    metadata from.
    """
    import chromadb

    client = chromadb.PersistentClient(path=config.VECTOR_DB_DIR)
    try:
        return client.get_collection(COLLECTION)
    except Exception:
        return None


def _load(collection, with_embeddings: bool = False):
    """Rows as (id, metadata, document) — plus the vector when asked.

    THE VECTOR IS NOT OPTIONAL FOR ANYTHING THAT DELETES. Restoring a chunk
    with `collection.add(...)` and no embedding makes Chroma compute one with
    its DEFAULT model (all-MiniLM-L6-v2, 384 dimensions) while this collection
    is bge-m3 at 1024, so the restore either errors outright —

        InvalidArgumentError: Collection expecting embedding with dimension
        of 1024, got 384

    — or, on a version that does not check, silently writes a vector from the
    wrong model into someone's medical index. Carrying the original vector in
    the backup makes rollback exact and independent of any embeddings key.
    """
    fields = ["metadatas", "documents"] + (["embeddings"] if with_embeddings else [])
    got = collection.get(include=fields)
    ids = got.get("ids") or []
    metas = got.get("metadatas") or []
    docs = got.get("documents") or []
    if not with_embeddings:
        return list(zip(ids, metas, docs))
    embs = got.get("embeddings")
    embs = [None] * len(ids) if embs is None else list(embs)
    return list(zip(ids, metas, docs, embs))


def _affected(rows):
    return [(i, m, d) for i, m, d in rows if DIVIDER in str((m or {}).get("user_id", ""))]


def _report(rows):
    affected = _affected(rows)
    print(f"collection            : {COLLECTION}")
    print(f"store                 : {config.VECTOR_DB_DIR}")
    print(f"chunks total          : {len(rows)}")
    print(f"chunks to migrate     : {len(affected)}")
    print(f"chunks already plain  : {len(rows) - len(affected)}")
    if not affected:
        return affected

    people = collections.defaultdict(lambda: {"sessions": set(), "files": set(), "chunks": 0})
    for _i, m, _d in affected:
        owner = str(m.get("user_id", ""))
        user, _, session = owner.partition(DIVIDER)
        entry = people[user]
        entry["sessions"].add(session)
        entry["files"].add(m.get("filename"))
        entry["chunks"] += 1

    print(f"distinct people       : {len(people)}")
    print()
    print(f"{'user id':34} {'sessions':>8} {'files':>6} {'chunks':>7}  filenames")
    for user, e in sorted(people.items(), key=lambda kv: -kv[1]["chunks"]):
        names = ", ".join(sorted(str(f) for f in e["files"]))
        print(f"{user:34} {len(e['sessions']):>8} {len(e['files']):>6} {e['chunks']:>7}  {names[:60]}")

    # What migrating would COLLIDE — the same file indexed under two logins.
    after = collections.defaultdict(list)
    for i, m, d in rows:
        owner = str(m.get("user_id", "")).split(DIVIDER)[0]
        after[(owner, m.get("filename"), m.get("chunk"))].append((i, d))
    dupes = {k: v for k, v in after.items() if len(v) > 1}
    identical = {k: v for k, v in dupes.items() if len({d for _i, d in v}) == 1}
    differing = {k: v for k, v in dupes.items() if len({d for _i, d in v}) > 1}
    print()
    print(f"post-migration collisions (same user+file+chunk): {len(dupes)}")
    print(f"  identical text (safe to de-duplicate) : {len(identical)}")
    print(f"  differing text (a real second version): {len(differing)}")
    if differing:
        print("  NOTE: differing text is NEVER removed, with or without --dedup.")
    return affected


def _backup_path() -> Path:
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(config.VECTOR_DB_DIR).parent / f"user_document_ids-backup-{stamp}.json"


def apply(collection, rows, dedup: bool) -> Path:
    affected = _affected(rows)
    if not affected:
        print("nothing to migrate")
        return None

    backup = {
        "created_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "store": str(config.VECTOR_DB_DIR),
        "collection": COLLECTION,
        "updated": [{"id": i, "old_user_id": m["user_id"]} for i, m, _d in affected],
        "deleted": [],
    }

    ids = [i for i, _m, _d in affected]
    metas = [{**m, "user_id": str(m["user_id"]).split(DIVIDER)[0]} for _i, m, _d in affected]

    if dedup:
        # Vectors are needed so the backup can restore a deleted chunk exactly.
        with_vecs = {r[0]: r[3] for r in _load(collection, with_embeddings=True)}
        # Only where the TEXT is byte-identical. A second, different version of
        # a report is a document, not a copy, and is always kept.
        after = collections.defaultdict(list)
        for i, m, d in rows:
            owner = str(m.get("user_id", "")).split(DIVIDER)[0]
            after[(owner, m.get("filename"), m.get("chunk"))].append((i, d, m))
        drop = []
        for _key, group in after.items():
            if len(group) < 2:
                continue
            by_text = collections.defaultdict(list)
            for i, d, m in group:
                by_text[d].append(i)
            for _text, same in by_text.items():
                if len(same) > 1:
                    # Deterministic survivor: lowest id. Nothing depends on
                    # WHICH copy survives, only that the choice is repeatable.
                    drop.extend(sorted(same)[1:])
        if drop:
            keep_docs = {i: d for i, _m, d in rows}
            keep_meta = {i: m for i, m, _d in rows}
            backup["deleted"] = [
                {
                    "id": i,
                    "metadata": keep_meta[i],
                    "document": keep_docs[i],
                    "embedding": list(with_vecs[i]),
                }
                for i in drop
            ]

    path = _backup_path()
    path.write_text(json.dumps(backup, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"backup written        : {path}")

    collection.update(ids=ids, metadatas=metas)
    print(f"metadata updated      : {len(ids)} chunk(s)")

    if backup["deleted"]:
        collection.delete(ids=[d["id"] for d in backup["deleted"]])
        print(f"duplicates removed    : {len(backup['deleted'])} (identical text only)")

    return path


def rollback(collection, path: Path) -> None:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("collection") != COLLECTION:
        raise SystemExit(f"backup is for collection {data.get('collection')!r}, refusing")

    restored = data.get("deleted") or []
    if restored:
        # Re-add before repointing, so the restored rows are repointed too.
        missing = [r["id"] for r in restored if not r.get("embedding")]
        if missing:
            raise SystemExit(
                f"backup has no embedding for {len(missing)} deleted chunk(s); "
                "refusing to re-add them with a different model's vectors"
            )
        collection.add(
            ids=[r["id"] for r in restored],
            metadatas=[r["metadata"] for r in restored],
            documents=[r["document"] for r in restored],
            embeddings=[r["embedding"] for r in restored],
        )
        print(f"deleted chunks restored : {len(restored)}")

    current = {i: m for i, m, _d in _load(collection)}
    ids, metas = [], []
    for row in data.get("updated", []):
        meta = current.get(row["id"])
        if meta is None:
            print(f"  WARNING: chunk {row['id'][:12]} is gone; cannot restore its owner")
            continue
        ids.append(row["id"])
        metas.append({**meta, "user_id": row["old_user_id"]})
    if ids:
        collection.update(ids=ids, metadatas=metas)
    print(f"owners restored         : {len(ids)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="perform the migration")
    ap.add_argument("--dedup", action="store_true",
                    help="with --apply, also drop chunks whose text is byte-identical "
                         "to another chunk of the same user+file+index")
    ap.add_argument("--rollback", metavar="BACKUP_JSON")
    args = ap.parse_args()

    collection = _open()
    if collection is None:
        print(f"no {COLLECTION!r} collection at {config.VECTOR_DB_DIR} — nothing to do")
        return 0

    if args.rollback:
        rollback(collection, Path(args.rollback))
        return 0

    rows = _load(collection)
    affected = _report(rows)
    if not args.apply:
        print("\nDRY RUN — nothing was changed. Re-run with --apply to migrate.")
        return 0
    if not affected:
        return 0

    print()
    apply(collection, rows, dedup=args.dedup)
    print("\ndone. Re-run without --apply to confirm 'chunks to migrate' is now 0.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
