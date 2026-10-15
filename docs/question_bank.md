# Question bank

The question bank holds CBSE-pattern multiple-choice questions for **Classes 6–12**. They are written
and reviewed in advance, then stored in PostgreSQL. Practice sets and tests serve them using SQL filters
and fixed rules.

**No model is involved** in any of this: not in retrieving or picking questions, not in assembling tests,
not in checking answers, and not in explaining them. `tests/test_architecture_guards.py` fails if
`app/qbank` or its scripts import `app.llm`, `app.rag`, `app.chat` or an HTTP client.

The tutor's own practice blocks in chat (`app/assessments`) are separate and unchanged.

- Code: `backend/app/qbank/`
- Schema: `backend/alembic/versions/0015_question_bank.py`
- Content: `qbank/` (see [qbank/README.md](../qbank/README.md))
- Reference SQL: [question_bank_queries.sql](question_bank_queries.sql)

## What it holds

Each level of the hierarchy is a table:

| Level | Table | Notes |
|---|---|---|
| Syllabus version | `qb_syllabus_versions` | e.g. `cbse-2026-27`, session `2026_27`, with the official source URL |
| Book | `qb_books` | The NCERT ID, e.g. `science-c10-en`. It fixes the class (6–12), the subject (an `app/learning/catalog.py` code) and the language of its content (`english`, `hindi` or `sanskrit`) |
| Chapter | `qb_chapters` | Unique by (book, number), so the same number can exist in another book or language. `old_chapter_number` keeps the pre-2023 numbering |
| Topic | `qb_topics` | |
| Concept | `qb_concepts` | A concept tag and its learning objective |
| Question | `qb_questions` | |

A question records:
- its **place**: book, class, subject, language, chapter, topic and concept, kept consistent by composite
  foreign keys;
- **difficulty** (easy, medium or hard) and **format** (`mcq`, `assertion_reason`, `case_based`,
  `source_based`);
- **competency**, using CBSE's question-paper bands: `knowledge_understanding`, `application`,
  `analysis_evaluation`;
- **content**: stem, four options, key, explanation and marks;
- **provenance**:
  - `original` means a practice question written in the CBSE pattern, never called official;
  - `ncert_exercise`;
  - `cbse_official`, which needs a source URL;
- **review**: `draft`, `needs_review`, `approved` or `rejected`, plus `is_active`;
- a **fingerprint** (duplicates) and a **content hash** (re-imports and approvals).

**Only approved, active questions are ever served.** An approval stores the reviewer, the time and the
content hash of exactly what was approved. A question edited after that goes back to `needs_review`, and
the database refuses an approval whose hash doesn't match.

## How content gets in

Content is produced offline, one book at a time:
1. **Manifest:** the book, its chapters (from the CBSE syllabus and the NCERT book), and its topics and
   concepts (from the textbook's sections).
2. **Write:** questions as JSONL.
3. **Check** with `scripts/import_questions.py ../qbank`. It looks at:
   - structure, enums, mapping to the manifest;
   - four distinct options; the key against the explanation; CBSE's assertion–reason options verbatim;
   - the case rule; the language script;
   - duplicates (refused) and near-duplicates (sent to review);
   - the chapter limit.

   Anything that needs subject judgment (is the key right? is it in the syllabus?) is left to the
   reviewer.
4. **Review:** the reviewer records `approved` together with `--hashes`' value, or `rejected`.
5. **Import** with `--apply`:
   - one transaction, all or nothing, under an advisory lock;
   - a rerun changes only what changed;
   - questions are never deleted, only retired (`--retire-missing`).
6. **Report** with `scripts/qbank_coverage.py`. It gives real counts per topic, a status (complete,
   awaiting_review, underfilled, missing, topics_missing), the shortfall to 5 approved questions (the owner's target, 2026-10-15), and
   each chapter's use of its limit.

Production imports are owner-authorised writes. Run them on the host with the API's environment (see
the script's docstring).

## Selection contract (`app/qbank/selection.py`)

**Filters.** Required: `language`, `class_level`, `subject_code`, `syllabus_version`. Optional:
`book_id`, `chapter_id`, `topic_id`, `question_format`, `unseen_only`.
- Every filter matches exactly and is never relaxed.
- A named book, chapter or topic must lie inside the requested class, subject and language, or the
  request is refused (422).

**Test** (`create_test`):
- It takes a count per difficulty.
- If any count is short of eligible questions, the result is a shortage report with nothing created:
  `{"status": "shortage", "buckets": {difficulty: {requested, available}}}`. A partial test is made only
  with `allow_partial`.
- The order is seeded by the set ID, and questions the student has seen come last.
- The key and the explanations come with the results, once the test is closed or fully answered.

**Adaptive practice** (`create_adaptive`, `next_item`): one topic, one question at a time. Each choice
depends on the student's previous answer in that topic:

| Previous answer | Next question |
|---|---|
| none | medium, the weakest (untried) concept |
| wrong | one level easier, same concept |
| right with a hint | same level, same concept |
| right, no hint | one level harder, the weakest other concept |

"Weakest" is smoothed accuracy, (right + 1) / (tries + 2): a practice signal, not a validated measure of
mastery. Questions are never repeated within a set. "Next" runs under the set's row lock, so a retry
returns the open question.

**Answers** (`answer`):
- An answer is accepted only for a question served in the student's own set; otherwise it is 404.
- The database grades it from the key and keeps it (trigger `qb_set_items_answer`).
- The same answer again returns the original result; a different answer, or one for a closed set, gets
  409.
- Creating a set is idempotent per (student, `request_id`).

## Invariants the database enforces

| Invariant | How |
|---|---|
| At most `max_questions` (≤ 1,000) questions per chapter | A counter on the chapter row, kept by triggers on insert, delete and move, and checked by `ck_qb_chapters_question_count`. Concurrent writers serialise on that row; lowering the limit below the count is refused; nothing else can write the counter. |
| Consistent identity | Composite foreign keys: a question cannot claim a language, class, subject or chapter other than its book's, cite another topic's case, or use another topic's concept. |
| Answers | Served unanswered, answered once, graded by the database, final. |
| Clean account deletion | A student's sets and answers are deleted with their account. |

## Status (2026-10-15)
- **Built** (not yet released): the schema, the importer, selection and coverage. They are verified on an
  isolated test database.
- **Inventory (`qbank/manifest/cbse-2026-27/`):** every NCERT book of Classes 6–12 in the app's subject
  catalog, taken from NCERT's own textbook index.
  - 167 books (80 English, 76 Hindi, 11 Sanskrit), 1,442 chapters.
  - 424 chapter titles are verified from the books' contents pages; 1,018 are marked unverified.
  - Not in the bank: subjects outside the catalog (e.g. Sociology, Informatics Practices, Home Science,
    Arts, Physical Education, vocational subjects), other mediums (Urdu and regional editions), and the
    superseded Class 8 books (NCF-2005 series).
- **Content:** one chapter, Class 10 Science (English) Ch 9 "Light – Reflection and Refraction"
  (`JESC1-CH09`): 7 topics, 147 questions, 14 cases.
  - None is reviewed yet, so **0 questions are servable**.
  - Topic 1 (plane mirrors) also awaits a syllabus decision: the 2026-27 Class X syllabus begins at
    reflection by curved surfaces.
- **Every other chapter (1,441)** has no topics and no questions yet. The full list is in
  [question_bank_coverage.md](question_bank_coverage.md), generated by `qbank_coverage.py --markdown`.
- **Not built:** the API and the web pages.
