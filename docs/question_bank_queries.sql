-- PadhAI question bank: the selection contract as SQL (docs/question_bank.md).
-- Reference only: the app runs the same logic from backend/app/qbank/selection.py with named parameters.
-- $n are positional parameters. Every query that serves a question names its columns; none returns
-- correct_option or explanation before an answer. Filters are exact and never relaxed.

-- S1 · Eligible pool for one difficulty bucket. Exact filters; optional ones are NULL; never relaxed.
--      $1 user, $2 language, $3 class, $4 subject, $5 syllabus_version, $6 book, $7 chapter, $8 topic,
--      $9 format, $10 difficulty, $11 seed (the set id), $12 n, $13 unseen_only.
--      `available` is the whole pool before LIMIT, for the shortage report (no row = 0 available).
SELECT q.question_id, q.topic_id, count(*) OVER () AS available
FROM qb_questions q
WHERE q.review_status = 'approved' AND q.is_active
  AND q.language = $2 AND q.class_level = $3 AND q.subject_code = $4 AND q.syllabus_version = $5
  AND ($6::text IS NULL OR q.book_id = $6)
  AND ($7::text IS NULL OR q.chapter_id = $7)
  AND ($8::text IS NULL OR q.topic_id = $8)
  AND ($9::text IS NULL OR q.question_format = $9)
  AND q.difficulty = $10
  AND NOT ($13 AND EXISTS (SELECT 1 FROM qb_set_items i
                           WHERE i.user_id = $1 AND i.topic_id = q.topic_id AND i.question_id = q.question_id))
ORDER BY EXISTS (SELECT 1 FROM qb_set_items i
                 WHERE i.user_id = $1 AND i.topic_id = q.topic_id AND i.question_id = q.question_id),
         md5($11 || q.question_id)
LIMIT $12;

-- Create a test (one transaction; selection.create_set):
--   1. INSERT INTO qb_sets (user_id, request_id, mode, filters, requested) VALUES (…)
--        ON CONFLICT (user_id, request_id) DO NOTHING RETURNING id;
--      no row → the existing set: same filters → return it (replay); other filters → 409 request_reused.
--   2. S1 per bucket (easy, medium, hard as requested), seed = set id.
--   3. Any bucket short and not allow_partial → ROLLBACK; return {status: "shortage",
--      buckets: {difficulty: {requested, available}}}. Nothing is written, nothing substituted.
--   4. INSERT INTO qb_set_items (set_id, position, user_id, question_id, topic_id) … positions 1..n;
--      UPDATE qb_sets SET served = n WHERE id = …;  COMMIT.

-- S2 · ADAPTIVE NEXT (one transaction; selection.next_item)
-- S2a · Lock the set. A retry while a question is open gets that question back; never two open.
SELECT s.mode, s.requested, s.served, s.filters, s.closed_at,
       (SELECT i.position FROM qb_set_items i WHERE i.set_id = s.id AND i.answered_at IS NULL LIMIT 1) AS open_position
FROM qb_sets s
WHERE s.id = $2 AND s.user_id = $1
FOR UPDATE;
-- No row → 404. Closed, or served = requested → finished. open_position → return that item.
-- S2b · Pick, decided by the student's previous answer in the topic (any set):
--   no history → medium, weakest (untried) concept | wrong → one level easier, same concept
--   right with a hint → same level, same concept   | right, no hint → one level harder, weakest other concept
--   "weakest" = smoothed accuracy (right + 1) / (tries + 2), untried = 0.5. Unseen questions first; never twice
--   in one set; never the previous question while anything else exists; ties by md5(seed || question_id).
--   $1 user, $2 set, $3 topic, $4 language, $5 class, $6 subject, $7 syllabus_version.
WITH history AS (
    SELECT i.question_id, i.is_correct, i.hinted, i.answered_at, q.level, q.concept_tag
    FROM qb_set_items i JOIN qb_questions q ON q.question_id = i.question_id
    WHERE i.user_id = $1 AND i.topic_id = $3 AND i.answered_at IS NOT NULL
), last AS (
    SELECT * FROM history ORDER BY answered_at DESC LIMIT 1
), target AS (
    SELECT CASE WHEN l.level IS NULL THEN 2
                WHEN NOT l.is_correct THEN greatest(l.level - 1, 1)
                WHEN l.hinted THEN l.level
                ELSE least(l.level + 1, 3) END AS level,
           CASE WHEN NOT l.is_correct OR l.hinted THEN l.concept_tag END AS same_concept,
           CASE WHEN l.is_correct AND NOT l.hinted THEN l.concept_tag END AS other_than,
           l.question_id AS previous
    FROM (VALUES (1)) AS one (x) LEFT JOIN last l ON true
), accuracy AS (
    SELECT concept_tag, (count(*) FILTER (WHERE is_correct) + 1)::real / (count(*) + 2) AS score
    FROM history GROUP BY concept_tag
), seen AS (
    SELECT DISTINCT ON (question_id) question_id, is_correct AS last_correct, answered_at AS last_at
    FROM history ORDER BY question_id, answered_at DESC
)
SELECT q.question_id, q.topic_id
FROM qb_questions q
CROSS JOIN target t
LEFT JOIN accuracy a ON a.concept_tag = q.concept_tag
LEFT JOIN seen s ON s.question_id = q.question_id
WHERE q.review_status = 'approved' AND q.is_active
  AND q.topic_id = $3 AND q.language = $4 AND q.class_level = $5 AND q.subject_code = $6 AND q.syllabus_version = $7
  AND NOT EXISTS (SELECT 1 FROM qb_set_items x WHERE x.set_id = $2 AND x.question_id = q.question_id)
ORDER BY s.question_id IS NOT NULL,
         q.question_id IS NOT DISTINCT FROM t.previous,
         abs(q.level - t.level),
         q.concept_tag IS DISTINCT FROM coalesce(t.same_concept, q.concept_tag),
         coalesce(q.concept_tag = t.other_than, false),
         coalesce(a.score, 0.5),
         s.last_correct NULLS FIRST,
         s.last_at NULLS FIRST,
         md5($2::text || q.question_id)
LIMIT 1;
-- No row → {status: "shortage", available: 0}; nothing is written.
-- S2c · INSERT INTO qb_set_items (set_id, position, user_id, question_id, topic_id) VALUES ($2, served + 1, $1, …);
--        UPDATE qb_sets SET served = served + 1 WHERE id = $2;  COMMIT (the lock from S2a is released).

-- S3 · Serve the item's content (no key). $1 user, $2 set, $3 position.
SELECT i.position, q.question_id, q.difficulty, q.question_format, c.title AS case_title, c.body AS case_body,
       q.stem, q.option_a, q.option_b, q.option_c, q.option_d, q.marks
FROM qb_set_items i
JOIN qb_questions q ON q.question_id = i.question_id
LEFT JOIN qb_cases c ON c.case_id = q.case_id
WHERE i.set_id = $2 AND i.position = $3 AND i.user_id = $1;

-- S4 · ANSWER: single use, graded by the database (trigger qb_set_items_answer). $1 user, $2 set,
--      $3 position, $4 chosen, $5 hinted.
UPDATE qb_set_items i SET chosen = $4, hinted = $5
WHERE i.set_id = $2 AND i.position = $3 AND i.user_id = $1 AND i.answered_at IS NULL
  AND EXISTS (SELECT 1 FROM qb_sets s WHERE s.id = i.set_id AND s.closed_at IS NULL)
RETURNING i.question_id, i.is_correct, i.answered_at;
-- No row → read the item (same user): none → 404; answered with the same chosen and hinted → the original
-- result (nothing written); answered otherwise, or the set closed → 409. A concurrent identical submit waits
-- on the row lock, finds it answered, and replays. Then the key and explanation (adaptive at once; a test
-- only in S6): SELECT correct_option, explanation FROM qb_questions WHERE question_id = $q;

-- S5 · Close a set (idempotent). $1 user, $2 set.
UPDATE qb_sets SET closed_at = clock_timestamp() WHERE id = $2 AND user_id = $1 AND closed_at IS NULL;

-- S6 · Results: an adaptive set any time; a test once closed or fully answered. $1 user, $2 set.
SELECT i.position, i.question_id, i.chosen, i.is_correct, q.correct_option, q.explanation
FROM qb_set_items i
JOIN qb_sets s ON s.id = i.set_id
JOIN qb_questions q ON q.question_id = i.question_id
WHERE i.set_id = $2 AND i.user_id = $1
  AND (s.mode = 'adaptive' OR s.closed_at IS NOT NULL
       OR NOT EXISTS (SELECT 1 FROM qb_set_items o WHERE o.set_id = s.id AND o.answered_at IS NULL))
ORDER BY i.position;

-- S7 · Smoothed accuracy per concept in a chapter, weakest first (not "mastery"). $1 user, $2 chapter.
SELECT q.topic_id, q.concept_tag, count(*) AS answered, count(*) FILTER (WHERE i.is_correct) AS correct,
       round((count(*) FILTER (WHERE i.is_correct) + 1)::numeric / (count(*) + 2), 2) AS smoothed_accuracy
FROM qb_set_items i JOIN qb_questions q ON q.question_id = i.question_id
WHERE i.user_id = $1 AND q.chapter_id = $2 AND i.answered_at IS NOT NULL
GROUP BY q.topic_id, q.concept_tag
ORDER BY smoothed_accuracy, q.topic_id, q.concept_tag;

-- E1 · The requested example: 5 Medium + 2 Hard, Class 10 Science (English), "Chapter 10" = the pre-2023
--      number of the current Ch 9, Topic 2. All or nothing: `available` below 5 / 2 → shortage, no rows used.
WITH ch AS (
    SELECT c.chapter_id FROM qb_chapters c JOIN qb_books b ON b.book_id = c.book_id
    WHERE b.curriculum = 'cbse' AND b.class_level = 10 AND b.subject_code = 'science' AND b.language = 'english'
      AND c.old_chapter_number = 10
), pool AS (
    SELECT q.question_id, q.difficulty,
           row_number() OVER (PARTITION BY q.difficulty ORDER BY md5($1 || q.question_id)) AS rn,
           count(*) OVER (PARTITION BY q.difficulty) AS available
    FROM qb_questions q
    JOIN qb_topics t ON t.topic_id = q.topic_id AND t.topic_number = 2
    WHERE q.chapter_id IN (SELECT chapter_id FROM ch)
      AND q.review_status = 'approved' AND q.is_active AND q.language = 'english'
      AND q.syllabus_version = 'cbse-2026-27' AND q.difficulty IN ('medium', 'hard')
)
SELECT p.available, q.question_id, q.difficulty, q.question_format, c.title AS case_title, c.body AS case_body,
       q.stem, q.option_a, q.option_b, q.option_c, q.option_d, q.marks
FROM pool p
JOIN qb_questions q ON q.question_id = p.question_id
LEFT JOIN qb_cases c ON c.case_id = q.case_id
WHERE (p.difficulty = 'medium' AND p.rn <= 5) OR (p.difficulty = 'hard' AND p.rn <= 2)
ORDER BY q.level, p.rn;

-- E2 · The requested example: 10 Assertion–Reason MCQs from that chapter (same rules; $1 = seed).
WITH ch AS (
    SELECT c.chapter_id FROM qb_chapters c JOIN qb_books b ON b.book_id = c.book_id
    WHERE b.curriculum = 'cbse' AND b.class_level = 10 AND b.subject_code = 'science' AND b.language = 'english'
      AND c.old_chapter_number = 10
)
SELECT count(*) OVER () AS available, q.question_id, q.topic_id, q.difficulty, q.stem,
       q.option_a, q.option_b, q.option_c, q.option_d, q.marks
FROM qb_questions q
WHERE q.chapter_id IN (SELECT chapter_id FROM ch) AND q.question_format = 'assertion_reason'
  AND q.review_status = 'approved' AND q.is_active AND q.language = 'english' AND q.syllabus_version = 'cbse-2026-27'
ORDER BY md5($1 || q.question_id)
LIMIT 10;

-- S8 · COVERAGE (scripts/qbank_coverage.py): class, subject, book, language, chapter, topic, difficulty.
--      complete = >= $1 (20) approved and active; awaiting_review = enough stored, not enough approved;
--      underfilled = fewer stored; missing = no questions; topics_missing = a chapter with no topics.
SELECT b.class_level, b.subject_code, b.book_id, b.title AS book_title, b.language, c.chapter_number,
       c.chapter_id, c.title AS chapter_title, c.question_count, c.max_questions, t.topic_number, t.topic_id,
       t.title AS topic_title,
       count(q.question_id) AS stored,
       count(*) FILTER (WHERE q.difficulty = 'easy') AS stored_easy,
       count(*) FILTER (WHERE q.difficulty = 'medium') AS stored_medium,
       count(*) FILTER (WHERE q.difficulty = 'hard') AS stored_hard,
       count(*) FILTER (WHERE q.review_status = 'approved' AND q.is_active) AS approved,
       count(*) FILTER (WHERE q.review_status IN ('draft', 'needs_review') AND q.is_active) AS unreviewed,
       count(*) FILTER (WHERE q.review_status = 'rejected') AS rejected,
       count(*) FILTER (WHERE q.review_status = 'approved' AND q.is_active AND q.difficulty = 'easy')
           AS approved_easy,
       count(*) FILTER (WHERE q.review_status = 'approved' AND q.is_active AND q.difficulty = 'medium')
           AS approved_medium,
       count(*) FILTER (WHERE q.review_status = 'approved' AND q.is_active AND q.difficulty = 'hard')
           AS approved_hard,
       CASE WHEN t.topic_id IS NULL THEN 'topics_missing'
            WHEN count(q.question_id) = 0 THEN 'missing'
            WHEN count(*) FILTER (WHERE q.review_status = 'approved' AND q.is_active) >= $1
                 THEN 'complete'
            WHEN count(*) FILTER (WHERE q.review_status IN ('approved', 'draft', 'needs_review')
                                    AND q.is_active) >= $1
                 THEN 'awaiting_review'
            ELSE 'underfilled' END AS status,
       greatest($1 - count(*) FILTER (WHERE q.review_status = 'approved' AND q.is_active), 0) AS shortfall
FROM qb_books b
JOIN qb_chapters c ON c.book_id = b.book_id
LEFT JOIN qb_topics t ON t.chapter_id = c.chapter_id
LEFT JOIN qb_questions q ON q.topic_id = t.topic_id
GROUP BY b.class_level, b.subject_code, b.book_id, b.title, b.language, c.chapter_number, c.chapter_id,
         c.title, c.question_count, c.max_questions, t.topic_number, t.topic_id, t.title
ORDER BY b.class_level, b.subject_code, b.language, b.book_id, c.chapter_number, t.topic_number
;
-- Invariant check (must return no rows): the counter equals the stored count.
SELECT c.chapter_id FROM qb_chapters c
WHERE c.question_count <> (SELECT count(*) FROM qb_questions q WHERE q.chapter_id = c.chapter_id);
