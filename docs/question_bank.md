# Question bank

The question bank holds CBSE-pattern multiple-choice questions for **Classes 6–12**. They are written
and reviewed in advance, then stored in PostgreSQL. Practice sets and tests serve them using SQL filters
and fixed rules.

**No model is involved** in any of this: not in retrieving or picking questions, not in assembling tests,
not in checking answers, and not in explaining them. `tests/test_architecture_guards.py` fails if
`app/qbank` or its scripts import `app.llm`, `app.rag`, `app.chat` or an HTTP client.

The tutor's own practice blocks in chat (`app/assessments`) are separate and unchanged.

- Code: `backend/app/qbank/`
- Schema: `backend/alembic/versions/0015_question_bank.py` (and 0016, 0017)
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

**Servable = approved or awaiting review (`needs_review`), and active** (`selection.SERVABLE`, the
owner's decision of 2026-10-16: students use the questions before anyone reviews them). Draft, rejected
and retired questions are never served. An approval stores the reviewer, the time and the content hash
of exactly what was approved. A question edited after that goes back to `needs_review`, and the database
refuses an approval whose hash doesn't match.

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

## Tests in the chat (`app/qbank/chat_tests.py`)

A practice test in the chat is always the bank's, never the model's (`QUESTION_BANK_TESTS`, on by default):
1. On a turn whose message asks for a test (its words do, or the intent router reads it as a test request:
   `INTENT_ROUTER=on`, `app/intents`), the tutor is given the chapters it may name: the class the message
   names, else the student's, else the last one named earlier in the chat; in the student's medium, plus
   the English, Hindi and Sanskrit books.
2. The tutor plans the test and writes one `question-bank` block: `{"chapter": "<chapter id>", "topics":
   ["...", 4], "count": 10, "difficulty": "easy|medium|hard|mixed"}`, or, for a mock test over up to three
   chapters of one class, subject and language, `{"chapters": ["<id>", "<id>"], "count": 25}` (whole
   chapters, no topics). For "test me on this" it uses what the chat covered; with no number asked, it
   chooses the count from how much the test covers (about 5 per topic, at most 30). It is taught never to
   write questions itself. A request it fences as JSON, writes inline (`::question-bank{...}`) or as a bare
   object is read the same way when it names chapter ids.
3. Before the reply is saved, the server replaces that block with a `quiz` block and opens the student's
   practice set for the test ("The practice ledger", below):
   - the pool is the servable questions of the named topics (each matched by number or clearly by its
     words), else of the whole chapters, of the asked difficulty; questions longer than the quiz card
     allows (187 case questions with long passages) are left out;
   - the test has as many questions as asked, at most 30 and at most what the pool has (fewer: a note says
     so); no question repeats in a test, and the same reply always starts with the same question (ties are
     seeded by the reply's id);
   - **adaptive** (`ADAPTIVE_CHAT_TESTS`, on by default): the block holds the first question, and each
     answer brings the next one, chosen from it (`selection.pick_next`, below). Off: every question is
     chosen when the test is set, by the same rules, and the test is fixed. It is a kill switch: turning it
     off needs no rollback, and those tests are recorded the same way.
4. The quiz is recorded, answered and graded like every chat test (`app/assessments/state.py`): answers
   are checked against the stored key, with no model call. The record also keeps `adaptive` and
   `source: {kind: "question_bank", chapterIds, topicIds, questionIds, setId}`, which clients never see.
5. A quiz or MCQ block the model writes itself is replaced by a note. An unknown chapter, chapters of
   different subjects, or a chapter with no stored questions gets a note instead of a test. A
   fill-in-the-blanks exercise the tutor writes is kept (the owner's decision, 2026-10-22): it is recorded
   and graded as before (`[[answer|alternative]]`, ignoring case, spacing and a trailing `.;,!`), and a
   malformed key (an empty alternative, a blank over 80 characters, more than 20 blanks, invalid JSON)
   refuses it whole, so it is shown read-only. Its key is the model's, so it is never practice evidence:
   no mastery, mistakes, revision or learning day. An exercise the model writes without its fence (as a
   `:::fill-blank` card, the study cards' form; as bare JSON; in a json or misnamed block; or as a card's
   plain text with `[[blanks]]`, often in Hindi) is put in its fill-blank fence first: on 2026-10-23 most
   exercises came that way and showed their answer key as text.

**Each answer** (`POST /v1/messages/{id}/assessment-responses`, `app/chat/router.py`) is one transaction,
under the reply's row lock: the response is checked and recorded on the reply; the answer is written to
the ledger and graded by the database; an adaptive test gets its next question chosen from that answer, or
the set is closed once the test is complete (or the bank has nothing left for it); the answer counts toward
the day's learning (5 answers make a learning day, `app/progress/learning.py`); then it commits. A response
names the hash of the questions it was shown, so a retry after a lost reply, a double tap or a second tab
is a replay of the test as it is now, never a second answer. A skip writes nothing to the ledger.

The model is still called once for the turn: it plans the test (chapter, topics, count, difficulty). It never
writes, picks, checks or scores a question.

### The practice ledger

- One `qb_sets` row per test in the chat (`mode = 'chat'`; `request_id` is the reply's id; `filters` hold
  the chapters, the topic pool, the named topics, the difficulty, the conversation and the title), and one
  `qb_set_items` row per question served, with `served_hash`: the question's `content_hash` when it was
  served (0017, set by the trigger and final).
- A set is closed when its test is complete (ended early when the bank ran out: `requested` becomes what was
  served), when its reply is regenerated or stopped as it is saved, or when its block can't be built.
- Deleting a chat keeps its sets and answers: they have no link to conversations, so the practice record
  outlives the chat (the owner's decision). Deleting the account deletes them. There is no API to delete a
  set.
- **A served question can't move to another topic**: the item's foreign key to (question, topic) has no ON
  UPDATE, so retire it and add it again. An edited question gets a new `content_hash`, so an answer given
  before the edit is set aside from mastery (`served_hash` <> `content_hash`); items served before 0017 have
  no `served_hash` and count as current.
- What the record says (`app/progress/practice.py`: mastery, mistakes, revision, the day's plan): see
  [api-contract.md](api-contract.md), "The practice record".

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

**Adaptive practice** (`create_adaptive`, `next_item`; and tests in the chat): one question at a time
(`pick_next`), from a pool of topics (adaptive practice: one). Each choice depends on the student's previous
answer: in that topic, for adaptive practice; in the test so far, for a test in the chat.

| Previous answer | Next question |
|---|---|
| none | medium, the weakest (untried) concept |
| wrong | one level easier, same concept |
| right with a hint | same level, same concept |
| right, no hint | one level harder, the weakest other concept |
| skipped (a test in the chat) | same level, another concept: a skip is not an answer, so no step down |

A concept is a topic's (topic, concept tag). "Weakest" is smoothed accuracy, (right + 1) / (tries + 2): a
practice signal, not a validated measure of mastery. Questions the student has not answered come first, and
none is repeated within a set. "Next" runs under the set's row lock, so a retry returns the open question.

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
| Answers | Served unanswered, answered once, graded by the database, final. A served item keeps the question's content hash of that moment (`served_hash`, 0017). |
| Clean account deletion | A student's sets and answers are deleted with their account (not with a chat). |

## Status (2026-10-16; 2026-10-22: adaptive tests in the chat, the practice ledger and record)
- **Released:** schema (0015, and 0016's servable indexes), importer, selection, coverage, and tests in the
  chat. 2026-10-22 (0017): tests in the chat are adaptive and recorded in the ledger, mock tests span up to
  three chapters, and the practice record (`GET /v1/progress/plan`, `/mastery`, `/revisions`, `/mistakes`,
  `/practice-tests`, `/practice-topics`) reads it. Tests in the chat set before then have no ledger rows:
  the record starts with this release.
- **Inventory (`qbank/manifest/cbse-2026-27/`):** every NCERT book of Classes 6–12 in the app's subject
  catalog, from NCERT's own textbook index: 167 books (80 English, 76 Hindi, 11 Sanskrit), 1,442 chapters.
  - Not in the bank: subjects outside the catalog (e.g. Sociology, Informatics Practices, Home Science,
    Arts, Physical Education, vocational subjects), other mediums (Urdu and regional editions), and the
    superseded Class 8 books (NCF-2005 series).
- **Content:** 1,418 chapters, 9,225 topics, 46,237 questions (5 per topic: 2 easy, 2 medium, 1 hard;
  21,767 English, 20,065 Hindi, 4,405 Sanskrit), written from each chapter's NCERT text.
  - **0 are approved**: all are `needs_review`, and all are servable by the owner's decision.
  - 24 chapters have no topics: NCERT has no text for them or they are not chapters (the list is in
    [question_bank_coverage.md](question_bank_coverage.md), generated by `qbank_coverage.py --markdown`).
- **Not built:** an API for practice outside the chat (`create_test`, `create_adaptive` and the `qb_sets`
  tables are ready for one; My Learning's practice picker starts a test in the chat), a way to delete a set,
  or to report a question.
