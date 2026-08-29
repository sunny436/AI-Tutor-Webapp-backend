"""
Upload-and-ask. Deterministic — no live GraphRAG call, no network.

    python tests/test_upload.py

Covers the one feature this backend restored: extract a report's text and
hand it back (no storage), then fold that text into a later /consult
question. GraphRAG itself is monkeypatched here — this is about what THIS
backend does with the text before and after that call, not about GraphRAG's
answer quality.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402

# Portable on purpose: this test must not depend on real secrets or a real
# GraphRAG deployment to run. REQUIRE_AUTH off matches how test_safety.py's
# server-level checks call _safety_result directly rather than minting a
# login; the GraphRAG_* values are just enough to make is_graphrag_ready()
# true so /consult reaches the (monkeypatched) call.
config.REQUIRE_AUTH = False
config.GRAPHRAG_ENABLED = True
config.GRAPHRAG_BASE_URL = "https://example.invalid"
config.GRAPHRAG_API_KEY = "test-key"

import server  # noqa: E402
from src import documents  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(server.app)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


# ===========================================================================
# A minimal, hand-written single-page PDF with one extractable text run —
# the classic minimal-PDF object skeleton (catalog, pages, page, font,
# content stream). No binary fixture in git, no extra dependency to
# generate one.
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
# Ported from the pre-deletion test_documents.py — only the assertions that
# tested extract_text() itself. The other half of that old file exercised
# per-user indexing (user_documents.index_document), which no longer exists
# and is not being revived.
import tempfile  # noqa: E402

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
    text = documents.extract_text(corrupt_path)
    check("a corrupt PDF does not raise", text == "", repr(text))
finally:
    Path(corrupt_path).unlink(missing_ok=True)

check("a missing file does not raise", documents.extract_text("no-such-file.pdf") == "")

with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
    tmp.write(b"")
    empty_path = tmp.name
try:
    check("an empty file does not raise", documents.extract_text(empty_path) == "")
finally:
    Path(empty_path).unlink(missing_ok=True)


# --- POST /upload: extract and hand back, nothing stored -------------------
resp = client.post(
    "/upload",
    files={"file": ("report.pdf", FIXTURE_PDF, "application/pdf")},
)
check("/upload returns 200", resp.status_code == 200, resp.text)
body = resp.json()
check("/upload returns the extracted text", FIXTURE_TEXT in (body.get("text") or ""), body)
check("chars matches the returned text's length", body.get("chars") == len(body.get("text") or ""), body)
check("truncated is False for a small fixture", body.get("truncated") is False, body)


# --- the safety scan sees the FULL text of EVERY attached document --------
resp = client.post(
    "/consult",
    json={
        "freeText": "kya khana chahiye",
        "documents": [
            {"filename": "old.pdf", "text": "sab theek hai, koi dikkat nahi"},
            {"filename": "new.pdf", "text": "patient ne bataya ki ulti me khoon aa raha hai"},
        ],
    },
)
check("/consult returns 200 for a flagged document", resp.status_code == 200, resp.text)
body = resp.json()
check(
    "a red flag in the SECOND of two attached documents still escalates",
    body.get("kind") == "escalation",
    body,
)

resp = client.post(
    "/consult",
    json={
        "freeText": "mujhe acidity hai",
        "documents": [{"filename": "report.pdf", "text": "purana blood test, sab normal hai"}],
    },
)
body = resp.json()
check(
    "an ordinary question with a clean document is NOT stopped locally",
    body.get("kind") != "escalation",
    body,
)

check(
    "a malformed documents field (not a list) is ignored, not a 500",
    client.post("/consult", json={"freeText": "hi", "documents": "not-a-list"}).status_code == 200,
)


# --- the query GraphRAG receives: question first, documents fairly split ---
captured: dict = {}


def _stub_answer(query: str) -> dict:
    captured["query"] = query
    return {"answer": "stubbed reply", "citations": []}


from src import graphrag  # noqa: E402

_original_answer = graphrag.answer
graphrag.answer = _stub_answer
try:
    question = "yeh meri report hai, ismein kya problem hai?"
    long_document = "yeh ek purani health report hai. " * 300  # well over MAX_QUERY_CHARS
    resp = client.post(
        "/consult",
        json={"freeText": question, "documents": [{"filename": "a.pdf", "text": long_document}]},
    )
    body = resp.json()
    query = captured.get("query", "")

    check(
        "the captured query fits GraphRAG's own hard cap",
        len(query) <= graphrag.MAX_QUERY_CHARS,
        f"{len(query)} chars",
    )
    check("the question survives verbatim and unclipped in the query", question in query, query[:200])
    check("a long attached document reports documentTruncated: true", body.get("documentTruncated") is True, body)
    check("the reply itself is GraphRAG's (stubbed) answer", body.get("answer") == "stubbed reply", body)

    # --- the bug this replaced: a second document must not be starved -----
    captured.clear()
    doc_a = "REPORT-A " * 200   # long enough alone to eat the whole old single-file budget
    doc_b = "REPORT-B " * 200
    client.post(
        "/consult",
        json={
            "freeText": "dono reports dekh kar batao",
            "documents": [
                {"filename": "a.pdf", "text": doc_a},
                {"filename": "b.pdf", "text": doc_b},
            ],
        },
    )
    two_file_query = captured.get("query", "")
    check(
        "with two attachments, the SECOND file's content also reaches the query",
        "REPORT-B" in two_file_query,
        two_file_query[-300:],
    )
    check(
        "with two attachments, the first file no longer eats the whole budget",
        "REPORT-A" in two_file_query,
        two_file_query[:300],
    )
finally:
    graphrag.answer = _original_answer


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== upload: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, _ in results:
        if not ok:
            print(f"  - {name}")
sys.exit(0 if passed == len(results) else 1)
