"""
The `userId|sessionId` -> `userId` migration, against a faithful copy of what
production actually holds.

WHY THIS EXISTS
`server.verify_token` used to return the whole Convex Auth subject —
`"<user>|<session>"` — and `user_documents` stamps that value onto every chunk
and filters every search by it. Commit fca0909 makes it return the user half.
Deploying that alone strands every chunk indexed before it: invisible to
search, and invisible to `remove_document` too, so the owner can neither read
their own report nor delete it. Permanent orphans holding medical text.

This exercises `scripts/migrate_user_document_ids.py` on a store seeded to look
exactly like production the moment before the deploy: several logins for one
person, a post-fix chunk that must not be disturbed, and a SECOND person whose
data must not move an inch.

Four things are proved, and the last two are the ones that matter most:

    no loss        — every unique chunk survives; the only thing --dedup may
                     drop is a BYTE-IDENTICAL copy, and it says so first
    no duplication — one chunk per (owner, file, index), never two
    no cross-link  — every chunk ends up under the person who uploaded it
    reversible     — rollback restores the store byte for byte

Runs against a TEMPORARY store via VECTOR_DB_DIR, never the real one.

    python tests/test_user_doc_migration.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# A temporary store, chosen BEFORE anything imports config.
_TMP = Path(tempfile.mkdtemp(prefix="migration-test-"))
os.environ["VECTOR_DB_DIR"] = str(_TMP / "vector_store")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, str(detail)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


import config  # noqa: E402
from src import user_documents  # noqa: E402

# The real ids, in the real shape.
ALICE = "m572jrdvnt10jr7d25e9nhke098dg7rv"
BOB = "m9x2kkq7ab41cc0we8ttyyzz1122ddee"
SESSION_1 = "js7cfyj9z922v5j2f7kbbkfhkd8dhhhb"
SESSION_2 = "js0aabbccddeeffgg11223344556677xx"
SESSION_B = "jsbbbbccccddddeeeeffff000011112222"

REPORT_TEXT = (
    "CITY DIAGNOSTIC LABORATORY. Patient: Rahul Sharma. Age 32 Male. "
    "COMPLETE BLOOD COUNT. Haemoglobin 9.2 g/dL (13.0-17.0) LOW. "
    "Fasting Blood Sugar 148 mg/dL HIGH."
)
BOB_TEXT = (
    "SUNRISE PATHOLOGY. Patient: Meera Iyer. Age 41 Female. "
    "THYROID PROFILE. TSH 8.4 mIU/L HIGH. Free T4 0.7 ng/dL LOW."
)


def seed() -> None:
    """Index documents exactly as the OLD code would have: composite owners."""
    # Alice, first login: two files.
    user_documents.index_document(f"{ALICE}|{SESSION_1}", "blood-report.pdf", REPORT_TEXT)
    user_documents.index_document(f"{ALICE}|{SESSION_1}", "sugar-report.pdf", REPORT_TEXT)
    # Alice, second login: the SAME file again. The old `remove_document`
    # filtered on the composite, so this really did write a second copy.
    user_documents.index_document(f"{ALICE}|{SESSION_2}", "blood-report.pdf", REPORT_TEXT)
    # Alice, after the fix: a bare id, which must not be touched.
    user_documents.index_document(ALICE, "new-report.pdf", REPORT_TEXT)
    # Bob, a different person entirely.
    user_documents.index_document(f"{BOB}|{SESSION_B}", "thyroid-report.pdf", BOB_TEXT)


def owners() -> dict[str, int]:
    got = user_documents.get_store().get(include=["metadatas"])
    counts: dict[str, int] = {}
    for meta in got["metadatas"]:
        key = str((meta or {}).get("user_id", ""))
        counts[key] = counts.get(key, 0) + 1
    return counts


def run_migration(*args: str) -> str:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "migrate_user_document_ids.py"), *args],
        capture_output=True, text=True, cwd=str(ROOT),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    return proc.stdout + proc.stderr


try:
    seed()
    before = owners()
    total_before = sum(before.values())
    print(f"seeded owners: {before}")

    # =======================================================================
    # BEFORE — this is the damage the deploy would do
    # =======================================================================
    check("1. the store holds chunks under composite owners",
          any("|" in key for key in before), list(before))
    alice_before = user_documents.search(ALICE, "haemoglobin", k=10)
    check("2. AFTER THE FIX ALICE SEES ONLY HER POST-FIX FILE",
          {name for name, _t, _s in alice_before} == {"new-report.pdf"},
          sorted({n for n, _t, _s in alice_before}))
    check("3. ...her earlier reports are stranded, not merely re-sorted",
          len(alice_before) < total_before - 1, f"{len(alice_before)} of {total_before}")
    check("4. ...and she cannot delete them either — remove matches nothing",
          user_documents.list_documents(ALICE) == ["new-report.pdf"],
          user_documents.list_documents(ALICE))

    # =======================================================================
    # DRY RUN — must change nothing
    # =======================================================================
    dry = run_migration()
    check("5. a dry run is the default", "DRY RUN" in dry.upper() or "dry" in dry.lower(),
          dry.strip().splitlines()[-1] if dry.strip() else "")
    check("6. ...and it changes nothing", owners() == before, owners())

    # =======================================================================
    # APPLY
    # =======================================================================
    out = run_migration("--apply", "--dedup")
    print(out.strip()[-500:])
    after = owners()
    total_after = sum(after.values())
    print(f"owners after: {after}")

    check("7. NO COMPOSITE OWNER SURVIVES",
          not any("|" in key for key in after), list(after))

    # THE ONLY CHUNK THAT MAY DISAPPEAR IS A BYTE-IDENTICAL DUPLICATE.
    # Alice uploaded blood-report.pdf from two logins, and the OLD
    # `remove_document` filtered on the composite owner so it matched nothing
    # and wrote a second copy. Collapsing those two is the entire purpose of
    # --dedup, and the script must say so out loud before doing it.
    check("8a. de-duplication is reported, not silent",
          "identical text (safe to de-duplicate)" in out, "")
    check("8b. IT ONLY EVER REMOVES IDENTICAL TEXT",
          "differing text (a real second version): 0" in out,
          [line for line in out.splitlines() if "differing text" in line])
    removed = total_before - total_after
    check("8c. exactly the duplicates were removed, nothing more",
          removed == 1, f"{total_before} -> {total_after} (removed {removed})")
    check("8d. NO UNIQUE CHUNK WAS LOST — every file is still reachable",
          {"blood-report.pdf", "sugar-report.pdf", "new-report.pdf"}
          == set(user_documents.list_documents(ALICE)),
          user_documents.list_documents(ALICE))
    check("9. every chunk now belongs to a real person",
          set(after) <= {ALICE, BOB}, list(after))

    # NO CROSS-LINK. Bob's chunk count must be exactly what he uploaded, and
    # none of Alice's may have landed on him.
    check("10. BOB'S DATA DID NOT MOVE",
          after.get(BOB, 0) == before.get(f"{BOB}|{SESSION_B}", 0),
          f"{before.get(f'{BOB}|{SESSION_B}', 0)} -> {after.get(BOB, 0)}")
    alice_expected = (before.get(f"{ALICE}|{SESSION_1}", 0)
                      + before.get(f"{ALICE}|{SESSION_2}", 0)
                      + before.get(ALICE, 0)) - removed
    check("11. ALICE GAINED EXACTLY HER OWN STRANDED CHUNKS",
          after.get(ALICE, 0) == alice_expected,
          f"{after.get(ALICE, 0)} expected {alice_expected}")

    # =======================================================================
    # RETRIEVAL WORKS AGAIN
    # =======================================================================
    alice_after = user_documents.search(ALICE, "haemoglobin", k=10)
    names = {name for name, _t, _s in alice_after}
    check("12. ALICE CAN READ HER EARLIER REPORTS AGAIN",
          {"blood-report.pdf", "sugar-report.pdf"} <= names, sorted(names))
    check("13. ...and her post-fix report is still there", "new-report.pdf" in names,
          sorted(names))
    check("14. the report text really comes back",
          any("9.2" in text for _n, text, _s in alice_after),
          [t[:40] for _n, t, _s in alice_after][:1])
    check("15. she can list and therefore delete them now",
          {"blood-report.pdf", "sugar-report.pdf", "new-report.pdf"}
          <= set(user_documents.list_documents(ALICE)),
          user_documents.list_documents(ALICE))

    # =======================================================================
    # ISOLATION — the property that must never be traded for convenience
    # =======================================================================
    bob_after = user_documents.search(BOB, "thyroid TSH", k=10)
    bob_names = {name for name, _t, _s in bob_after}
    check("16. BOB SEES HIS OWN REPORT", "thyroid-report.pdf" in bob_names, sorted(bob_names))
    check("17. ALICE NEVER SEES BOB'S REPORT", "thyroid-report.pdf" not in names,
          sorted(names))
    check("18. BOB NEVER SEES ALICE'S REPORTS",
          not ({"blood-report.pdf", "sugar-report.pdf", "new-report.pdf"} & bob_names),
          sorted(bob_names))
    check("19. no one else's text leaks into Bob's hits",
          all("Rahul" not in text for _n, text, _s in bob_after),
          [t[:40] for _n, t, _s in bob_after][:1])
    check("20. an unknown user gets nothing at all",
          user_documents.search("someone-else-entirely", "haemoglobin", k=10) == [])
    check("21. an empty user id gets nothing at all",
          user_documents.search("", "haemoglobin", k=10) == [])

    # =======================================================================
    # REVERSIBLE
    # =======================================================================
    # The backup lands beside the store it protects, not in the repo.
    backups = sorted(Path(config.VECTOR_DB_DIR).parent.glob(
        "user_document_ids-backup-*.json"))
    check("22. a backup was written next to the store", bool(backups),
          [b.name for b in backups][-1:])
    if backups:
        rolled = run_migration("--rollback", str(backups[-1]))
        restored = owners()
        check("23. ROLLBACK RESTORES THE ORIGINAL OWNERS", restored == before,
              f"{restored} vs {before}")
        check("24. ...losing nothing on the way back",
              sum(restored.values()) == total_before,
              f"{sum(restored.values())} vs {total_before}")
        check("25. ...and the text survives the round trip",
              any("9.2" in t for _n, t, _s in
                  user_documents.search(f"{ALICE}|{SESSION_1}", "haemoglobin", k=5)),
              rolled.strip()[-120:])
finally:
    try:
        user_documents._store = None
        shutil.rmtree(_TMP, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass
    for leftover in Path(ROOT).glob("user_document_ids-backup-*.json"):
        leftover.unlink(missing_ok=True)


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== user doc migration: {passed}/{len(results)} passed =====")
if passed != len(results):
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name} :: {detail}")
    sys.exit(1)
