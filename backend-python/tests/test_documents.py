"""
tests/test_documents.py
-----------------------
Document extraction and, more importantly, per-user isolation.

Test 4 is the reason this file exists. Everything else here is about whether a
feature works; that one is about whether one person's blood report can be read
back to somebody else. It asserts the leak directly rather than trusting that
the filter is written correctly, because "I read the code and it looked right"
is exactly how this class of bug ships.

Run:  python -m tests.test_documents
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import user_documents  # noqa: E402
from src.documents import extract_text  # noqa: E402

passed = 0
failed: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    global passed
    if condition:
        passed += 1
        print(f"PASS  {label}" + (f" - {detail}" if detail else ""))
    else:
        failed.append(label)
        print(f"FAIL  {label}" + (f" - {detail}" if detail else ""))


def _write(suffix: str, content: bytes) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        return tmp.name


# =========================================================================
# 1. EXTRACTION NEVER RAISES
# =========================================================================
print("\n--- 1. extraction ---")

txt = _write(".txt", b"Haemoglobin 9.2 g/dL\nVitamin D 14 ng/mL\nTSH 5.8")
check(
    "a plain text report is read",
    "9.2" in extract_text(txt),
    extract_text(txt)[:40].replace("\n", " "),
)

corrupt = _write(".pdf", b"this is not really a pdf at all")
try:
    result = extract_text(corrupt)
    check("a corrupt PDF returns text rather than raising", isinstance(result, str))
except Exception as error:  # noqa: BLE001
    check("a corrupt PDF returns text rather than raising", False, str(error)[:60])

missing = str(Path(tempfile.gettempdir()) / "definitely-not-here-12345.pdf")
try:
    check("a missing file does not raise", isinstance(extract_text(missing), str))
except Exception as error:  # noqa: BLE001
    check("a missing file does not raise", False, str(error)[:60])

empty = _write(".txt", b"")
check("an empty file yields empty text", not extract_text(empty).strip())


# =========================================================================
# 2. INDEXING
# =========================================================================
print("\n--- 2. indexing ---")

ALICE = "test-user-alice"
BOB = "test-user-bob"
ALICE_FILE = "alice-blood-report.txt"
BOB_FILE = "bob-thyroid-report.txt"

ALICE_TEXT = (
    "Patient: Alice. Complete Blood Count. "
    "Haemoglobin 9.2 g/dL (low). Ferritin 8 ng/mL (low). "
    "Impression: iron deficiency anaemia. Advised dietary iron."
)
BOB_TEXT = (
    "Patient: Bob. Thyroid Function Test. "
    "TSH 7.9 mIU/L (high). T4 normal. "
    "Impression: subclinical hypothyroidism."
)

# Start clean, so a re-run does not measure leftovers from the previous one.
user_documents.remove_document(ALICE, ALICE_FILE)
user_documents.remove_document(BOB, BOB_FILE)

alice_chunks = user_documents.index_document(ALICE, ALICE_FILE, ALICE_TEXT)
bob_chunks = user_documents.index_document(BOB, BOB_FILE, BOB_TEXT)

check("a document is chunked and indexed", alice_chunks > 0, f"{alice_chunks} chunks")
check("a second user's document indexes too", bob_chunks > 0, f"{bob_chunks} chunks")
check(
    "an anonymous upload indexes nothing",
    user_documents.index_document("", "anon.txt", ALICE_TEXT) == 0,
)
check(
    "an empty document indexes nothing",
    user_documents.index_document(ALICE, "blank.txt", "   ") == 0,
)

before = user_documents.index_document(ALICE, ALICE_FILE, ALICE_TEXT)
check(
    "re-uploading replaces rather than duplicates",
    len(user_documents.list_documents(ALICE)) == 1,
    f"{user_documents.list_documents(ALICE)}, {before} chunks",
)


# =========================================================================
# 3. RETRIEVAL WORKS AT ALL
# =========================================================================
print("\n--- 3. retrieval ---")

hits = user_documents.search(ALICE, "meri report me haemoglobin kya hai")
check("a user finds their own report", len(hits) > 0, f"{len(hits)} hits")
check(
    "the retrieved text is the right document",
    any("9.2" in text for _, text, _ in hits),
    hits[0][1][:50] if hits else "no hits",
)
check(
    "an empty query returns nothing",
    user_documents.search(ALICE, "") == [],
)


# =========================================================================
# 4. ISOLATION - THE ONE THAT MATTERS
# =========================================================================
print("\n--- 4. isolation ---")

bob_asking = user_documents.search(BOB, "haemoglobin ferritin anaemia iron")
leaked = [text for _, text, _ in bob_asking if "Alice" in text or "9.2" in text]
check(
    "user B never sees user A's report, even asking for it by name",
    not leaked,
    f"{len(bob_asking)} hits, {len(leaked)} leaked",
)

alice_asking = user_documents.search(ALICE, "TSH thyroid hypothyroidism")
leaked_back = [text for _, text, _ in alice_asking if "Bob" in text or "7.9" in text]
check(
    "and it does not leak the other way either",
    not leaked_back,
    f"{len(alice_asking)} hits, {len(leaked_back)} leaked",
)

anon = user_documents.search("", "haemoglobin ferritin anaemia iron TSH thyroid")
check(
    "an anonymous caller sees nothing at all",
    anon == [],
    f"{len(anon)} hits",
)


# =========================================================================
# 5. DELETION
# =========================================================================
print("\n--- 5. deletion ---")

user_documents.remove_document(ALICE, ALICE_FILE)
check(
    "a deleted document stops answering questions",
    user_documents.search(ALICE, "haemoglobin ferritin") == [],
)
check(
    "and disappears from the listing",
    ALICE_FILE not in user_documents.list_documents(ALICE),
    str(user_documents.list_documents(ALICE)),
)

user_documents.remove_document(BOB, BOB_FILE)


total = passed + len(failed)
print(f"\n===== documents: {passed}/{total} passed =====")
if failed:
    print("\nFailing:")
    for name in failed:
        print(f"  - {name}")
    sys.exit(1)
