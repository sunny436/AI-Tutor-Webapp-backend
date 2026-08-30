"""
Upload: extraction + per-user indexing. Deterministic — no live GraphRAG or
LLM call; the embedding call to OpenRouter is the only live dependency (it
needs a real OPENROUTER_API_KEY, since embeddings have no local fallback).

    python tests/test_upload.py

Covers /upload's own behavior: extract, index for the caller, return text.
Retrieval OF that indexed text (does a later question actually find the
right chunk) is covered separately in test_reversal.py's proof point 5 —
this file is about the upload step, not the whole pipeline.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402

config.REQUIRE_AUTH = False

import server  # noqa: E402
from src import documents  # noqa: E402
from src import user_documents  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(server.app)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


# ===========================================================================
# A minimal, hand-written single-page PDF with one extractable text run.
# ===========================================================================
FIXTURE_TEXT = "AYURVEDA TEST FIXTURE 12345"


def _make_fixture_pdf(text: str) -> bytes:
    content = f"BT /F1 24 Tf 50 100 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n".encode()
    pdf += b"0000000000 65535 f \n"
    for off in offsets:
        pdf += f"{off:010d} 00000 n \n".encode()
    pdf += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode()
    return pdf


FIXTURE_PDF = _make_fixture_pdf(FIXTURE_TEXT)


# --- extraction never raises, whatever it is handed ------------------------
with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
    tmp.write(FIXTURE_PDF)
    fixture_path = tmp.name
try:
    text = documents.extract_text(fixture_path)
    check("a real PDF extracts its text", FIXTURE_TEXT in text, text)
finally:
    Path(fixture_path).unlink(missing_ok=True)

with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
    tmp.write(b"not actually a pdf")
    corrupt_path = tmp.name
try:
    check("a corrupt PDF does not raise", documents.extract_text(corrupt_path) == "")
finally:
    Path(corrupt_path).unlink(missing_ok=True)

check("a missing file does not raise", documents.extract_text("no-such-file.pdf") == "")


# --- POST /upload: anonymous caller gets text back, nothing indexed --------
resp = client.post("/upload", files={"file": ("report.pdf", FIXTURE_PDF, "application/pdf")})
check("/upload returns 200", resp.status_code == 200, resp.text)
body = resp.json()
check("/upload returns the extracted text", FIXTURE_TEXT in (body.get("text") or ""), body)
check("chars matches the returned text's length", body.get("chars") == len(body.get("text") or ""), body)
check("truncated is False for a small fixture", body.get("truncated") is False, body)
check("an anonymous caller (no verified user) indexes nothing", body.get("indexed") == 0, body)


# --- POST /upload: a signed-in caller indexes for retrieval ----------------
# REQUIRE_AUTH is off (portability, no real login needed for this script), so
# `require_user` returns "" for everyone via server.py's own logic UNLESS a
# verified token is presented — there is no way to fake one here without a
# real Convex keypair. Indexing is therefore exercised directly against
# user_documents, which is what /upload calls internally; the anonymous-path
# check above already proves /upload wires user_id through correctly (0
# indexed with none).
TEST_USER_A = "test-user-memory-manager-a"
TEST_USER_B = "test-user-memory-manager-b"

for uid in (TEST_USER_A, TEST_USER_B):
    try:
        user_documents.remove_document(uid, "report.pdf")
    except Exception:
        pass

try:
    indexed = user_documents.index_document(TEST_USER_A, "report.pdf", FIXTURE_TEXT * 5)
    check("indexing a real document returns a nonzero chunk count", indexed > 0, indexed)

    docs_a = user_documents.list_documents(TEST_USER_A)
    check("the indexed filename is listed for that user", "report.pdf" in docs_a, docs_a)

    docs_b = user_documents.list_documents(TEST_USER_B)
    check("a different user sees no documents", docs_b == [], docs_b)
finally:
    for uid in (TEST_USER_A, TEST_USER_B):
        try:
            user_documents.remove_document(uid, "report.pdf")
        except Exception:
            pass


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== upload: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, _ in results:
        if not ok:
            print(f"  - {name}")
sys.exit(0 if passed == len(results) else 1)
