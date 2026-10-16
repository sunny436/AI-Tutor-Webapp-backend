# qbank: question bank content (text)

These files are the source of PadhAI's question bank. `backend/scripts/import_questions.py` checks them
and imports them into PostgreSQL. Rules and contract: [docs/question_bank.md](../docs/question_bank.md).

Content is written offline. Nothing here is generated at runtime, and the app serves only questions that
a reviewer has approved.

```
manifest/<syllabus version>/<book_id>.json       one book: its syllabus version, chapters, topics, concepts
content/<book_id>/<chapter_id>/cases.jsonl       shared passages (case- and source-based questions)
content/<book_id>/<chapter_id>/questions.jsonl   one question per line
```

## IDs
- **Book:** `<title>-c<class>-<en|hi|sa>`, e.g. `science-c10-en`. A Hindi or Sanskrit book has its own ID.
  The manifest also records NCERT's book code (`ncert_code`, e.g. `jesc1`).
- **Chapter:** `<NCERT code>-CH<nn>`, e.g. `JESC1-CH09`. It is unique across every class, subject, book
  and language, and matches NCERT's chapter PDF (`jesc109.pdf`, the manifest's `source_pdf`).
- **Topic:** `<chapter>-T<n>`.
- **Case:** `<topic>-CS<n>`.
- **Question:** `<topic>-<nnn>`.

IDs are permanent: never reuse one for different content.

**The inventory** (`manifest/cbse-2026-27/`) lists every NCERT book of Classes 6–12 in the app's subject
catalog, in English, Hindi and Sanskrit, with all their chapters. It was taken from NCERT's own textbook
index (books, codes, chapter counts).
- A chapter title read from the book's contents page has `"title_verified": true`.
- Any other title reads `Chapter <n> [title unverified]` until someone checks it against `source_pdf`.
  Titles are never guessed.

**Topics** are added to a chapter's manifest when its questions are written.

## A question (one JSON object per line)

```json
{"question_id": "JESC1-CH09-T7-001", "chapter_id": "JESC1-CH09", "topic_id": "JESC1-CH09-T7",
 "concept_tag": "power-of-lens", "difficulty": "easy", "format": "mcq", "competency": "application",
 "case_id": null, "stem": "…", "options": ["…", "…", "…", "…"], "answer": "B", "explanation": "Correct option: (B). …",
 "marks": 1, "source": {"kind": "original", "ref": "…", "url": null},
 "review": {"status": "needs_review", "note": "…"}, "active": true}
```

**Allowed values:**

| Field | Values |
|---|---|
| `difficulty` | `easy`, `medium`, `hard` |
| `format` | `mcq`, `assertion_reason` (CBSE's four options, verbatim), `case_based` / `source_based` (with a `case_id` of the same topic) |
| `competency` | `knowledge_understanding`, `application`, `analysis_evaluation` (CBSE's question-paper bands) |
| `source.kind` | `original` (written in the CBSE pattern; never call it official), `ncert_exercise`, `cbse_official` (needs `source.url`) |

## Reviewing
A reviewer checks:
- the key and the explanation;
- syllabus alignment, difficulty, competency and language;
- the near-duplicate notes the importer prints.

Then:
1. **To approve**, run `python scripts/import_questions.py ../qbank --hashes` from `backend/` and set:

   ```json
   "review": {"status": "approved", "by": "<name>", "at": "2026-10-20T10:00:00+05:30", "hash": "<that question's hash>"}
   ```

   If the content changes afterwards, the hash no longer matches and the import refuses the approval.
2. **To refuse**, set `"status": "rejected"` with a `note`.

## Importing
Run from `backend/`:

```sh
python scripts/import_questions.py ../qbank            # dry run: the exact report, nothing written
python scripts/import_questions.py ../qbank --apply    # one transaction, all or nothing
python scripts/qbank_coverage.py                       # real counts, statuses and shortfalls
```

## What is here (2026-10-15)
- **Manifest (the inventory):** 167 books, 1,442 chapters (CBSE 2026-27); 424 chapter titles verified.
- **Content:** Chapter 9 only, with topics and concepts: 147 questions and 14 cases, all `needs_review`.
- **Not yet in the bank:** every other chapter and every other book for Classes 6–12.
