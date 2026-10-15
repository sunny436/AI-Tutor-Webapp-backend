"""Question bank: CBSE-pattern MCQs for Classes 6-12, and the practice sets that serve them (app/qbank).

Revision ID: 0015_question_bank
Revises: 0014_study_time
Create Date: 2026-10-15

Schema only: content arrives through scripts/import_questions.py from the text files in qbank/
(docs/question_bank.md). Hierarchy: syllabus version · book (class, subject, language) · chapter ·
topic · concept · question. What the database itself guarantees:
- a question agrees with its book, chapter, topic, concept and case (composite foreign keys), so
  English and Hindi content can never mix and a chapter number is unique only within its book;
- only an approved question carries the hash of the content its reviewer approved;
- at most max_questions (<= 1000) questions per chapter: a counter on the chapter row, kept by
  triggers on every insert, delete and move and checked by a constraint, so concurrent writers
  serialise on that row; nothing else may write the counter;
- an answer belongs to a question served to that student in one of their sets, is graded here from
  the key, and is final (trigger qb_set_items_answer).

Additive and backward compatible: new tables, functions and triggers only; the release before this
one never reads them. NOT rollback-safe in the destructive sense: the downgrade drops the bank and
every practice set, so it must never run without the owner's explicit authorization (a deploy never
downgrades).
"""

from alembic import op

revision = "0015_question_bank"
down_revision = "0014_study_time"
branch_labels = None
depends_on = None

# One statement per op.execute: asyncpg prepares each one, and refuses several at once.
UPGRADE = (
    """
    CREATE TABLE qb_syllabus_versions (
        code              text NOT NULL,
        curriculum        text NOT NULL,
        academic_session  text NOT NULL,
        title             text NOT NULL,
        source_url        text NOT NULL,
        CONSTRAINT pk_qb_syllabus_versions PRIMARY KEY (code),
        CONSTRAINT uq_qb_syllabus_versions_curriculum_academic_session UNIQUE (curriculum, academic_session),
        CONSTRAINT ck_qb_syllabus_versions_curriculum CHECK (curriculum IN ('cbse'))
    )
    """,
    """
    CREATE TABLE qb_books (
        book_id       text NOT NULL,
        curriculum    text NOT NULL,
        class_level   smallint NOT NULL,
        subject_code  text NOT NULL,
        language      text NOT NULL,
        title         text NOT NULL,
        edition       text NOT NULL,
        CONSTRAINT pk_qb_books PRIMARY KEY (book_id),
        CONSTRAINT uq_qb_books_book_id_class_level_subject_code_language
            UNIQUE (book_id, class_level, subject_code, language),
        CONSTRAINT ck_qb_books_curriculum CHECK (curriculum IN ('cbse')),
        CONSTRAINT ck_qb_books_class_level CHECK (class_level BETWEEN 6 AND 12),
        CONSTRAINT ck_qb_books_language CHECK (language IN ('english', 'hindi', 'sanskrit')),
        CONSTRAINT ck_qb_books_subject_code CHECK (subject_code ~ '^[a-z_]+$')
    )
    """,
    """
    CREATE TABLE qb_chapters (
        chapter_id          text NOT NULL,
        book_id             text NOT NULL,
        chapter_number      smallint NOT NULL,
        old_chapter_number  smallint,
        title               text NOT NULL,
        ncert_chapter_id    text,
        max_questions       smallint NOT NULL DEFAULT 1000,
        question_count      smallint NOT NULL DEFAULT 0,
        CONSTRAINT pk_qb_chapters PRIMARY KEY (chapter_id),
        CONSTRAINT uq_qb_chapters_book_id_chapter_number UNIQUE (book_id, chapter_number),
        CONSTRAINT uq_qb_chapters_chapter_id_book_id UNIQUE (chapter_id, book_id),
        CONSTRAINT fk_qb_chapters_book_id_qb_books FOREIGN KEY (book_id) REFERENCES qb_books (book_id),
        CONSTRAINT ck_qb_chapters_max_questions CHECK (max_questions BETWEEN 1 AND 1000),
        CONSTRAINT ck_qb_chapters_question_count CHECK (question_count BETWEEN 0 AND max_questions)
    )
    """,
    """
    CREATE TABLE qb_topics (
        topic_id        text NOT NULL,
        chapter_id      text NOT NULL,
        topic_number    smallint NOT NULL,
        title           text NOT NULL,
        ncert_sections  text,
        CONSTRAINT pk_qb_topics PRIMARY KEY (topic_id),
        CONSTRAINT uq_qb_topics_chapter_id_topic_number UNIQUE (chapter_id, topic_number),
        CONSTRAINT uq_qb_topics_topic_id_chapter_id UNIQUE (topic_id, chapter_id),
        CONSTRAINT fk_qb_topics_chapter_id_qb_chapters FOREIGN KEY (chapter_id) REFERENCES qb_chapters (chapter_id)
    )
    """,
    """
    CREATE TABLE qb_concepts (
        topic_id            text NOT NULL,
        concept_tag         text NOT NULL,
        learning_objective  text NOT NULL,
        CONSTRAINT pk_qb_concepts PRIMARY KEY (topic_id, concept_tag),
        CONSTRAINT fk_qb_concepts_topic_id_qb_topics FOREIGN KEY (topic_id) REFERENCES qb_topics (topic_id),
        CONSTRAINT ck_qb_concepts_concept_tag CHECK (concept_tag ~ '^[a-z0-9]+(-[a-z0-9]+)*$')
    )
    """,
    """
    CREATE TABLE qb_cases (
        case_id   text NOT NULL,
        topic_id  text NOT NULL,
        title     text NOT NULL,
        body      text NOT NULL,
        CONSTRAINT pk_qb_cases PRIMARY KEY (case_id),
        CONSTRAINT uq_qb_cases_case_id_topic_id UNIQUE (case_id, topic_id),
        CONSTRAINT fk_qb_cases_topic_id_qb_topics FOREIGN KEY (topic_id) REFERENCES qb_topics (topic_id),
        CONSTRAINT ck_qb_cases_body CHECK (length(body) BETWEEN 100 AND 4000)
    )
    """,
    """
    CREATE TABLE qb_questions (
        question_id       text NOT NULL,
        book_id           text NOT NULL,
        class_level       smallint NOT NULL,
        subject_code      text NOT NULL,
        language          text NOT NULL,
        chapter_id        text NOT NULL,
        topic_id          text NOT NULL,
        concept_tag       text NOT NULL,
        syllabus_version  text NOT NULL,
        difficulty        text NOT NULL,
        level             smallint NOT NULL GENERATED ALWAYS AS
                              (CASE difficulty WHEN 'easy' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END) STORED,
        question_format   text NOT NULL,
        competency        text NOT NULL,
        case_id           text,
        stem              text NOT NULL,
        option_a          text NOT NULL,
        option_b          text NOT NULL,
        option_c          text NOT NULL,
        option_d          text NOT NULL,
        correct_option    char(1) NOT NULL,
        explanation       text NOT NULL,
        marks             smallint NOT NULL DEFAULT 1,
        source_kind       text NOT NULL,
        source_ref        text NOT NULL,
        source_url        text,
        review_status     text NOT NULL DEFAULT 'draft',
        reviewed_by       text,
        reviewed_at       timestamptz,
        reviewed_hash     text,
        review_note       text,
        is_active         boolean NOT NULL DEFAULT true,
        fingerprint       text NOT NULL,
        content_hash      text NOT NULL,
        created_at        timestamptz NOT NULL DEFAULT clock_timestamp(),
        updated_at        timestamptz NOT NULL DEFAULT clock_timestamp(),
        CONSTRAINT pk_qb_questions PRIMARY KEY (question_id),
        CONSTRAINT uq_qb_questions_question_id_topic_id UNIQUE (question_id, topic_id),
        CONSTRAINT uq_qb_questions_fingerprint UNIQUE (fingerprint),
        CONSTRAINT fk_qb_questions_book_id_qb_books FOREIGN KEY (book_id, class_level, subject_code, language)
            REFERENCES qb_books (book_id, class_level, subject_code, language),
        CONSTRAINT fk_qb_questions_chapter_id_qb_chapters FOREIGN KEY (chapter_id, book_id)
            REFERENCES qb_chapters (chapter_id, book_id),
        CONSTRAINT fk_qb_questions_topic_id_qb_topics FOREIGN KEY (topic_id, chapter_id)
            REFERENCES qb_topics (topic_id, chapter_id),
        CONSTRAINT fk_qb_questions_topic_id_qb_concepts FOREIGN KEY (topic_id, concept_tag)
            REFERENCES qb_concepts (topic_id, concept_tag),
        CONSTRAINT fk_qb_questions_case_id_qb_cases FOREIGN KEY (case_id, topic_id)
            REFERENCES qb_cases (case_id, topic_id),
        CONSTRAINT fk_qb_questions_syllabus_version_qb_syllabus_versions FOREIGN KEY (syllabus_version)
            REFERENCES qb_syllabus_versions (code),
        CONSTRAINT ck_qb_questions_difficulty CHECK (difficulty IN ('easy', 'medium', 'hard')),
        CONSTRAINT ck_qb_questions_question_format
            CHECK (question_format IN ('mcq', 'assertion_reason', 'case_based', 'source_based')),
        CONSTRAINT ck_qb_questions_competency
            CHECK (competency IN ('knowledge_understanding', 'application', 'analysis_evaluation')),
        CONSTRAINT ck_qb_questions_case
            CHECK ((question_format IN ('case_based', 'source_based')) = (case_id IS NOT NULL)),
        CONSTRAINT ck_qb_questions_correct_option CHECK (correct_option IN ('A', 'B', 'C', 'D')),
        CONSTRAINT ck_qb_questions_distinct_options CHECK (
            lower(option_a) NOT IN (lower(option_b), lower(option_c), lower(option_d))
            AND lower(option_b) NOT IN (lower(option_c), lower(option_d))
            AND lower(option_c) <> lower(option_d)),
        CONSTRAINT ck_qb_questions_marks CHECK (marks BETWEEN 1 AND 5),
        CONSTRAINT ck_qb_questions_source_kind CHECK (source_kind IN ('original', 'ncert_exercise', 'cbse_official')),
        CONSTRAINT ck_qb_questions_official_source CHECK (source_kind <> 'cbse_official' OR source_url IS NOT NULL),
        CONSTRAINT ck_qb_questions_review_status
            CHECK (review_status IN ('draft', 'needs_review', 'approved', 'rejected')),
        CONSTRAINT ck_qb_questions_approved CHECK (review_status <> 'approved' OR (
            reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND reviewed_hash = content_hash)),
        CONSTRAINT ck_qb_questions_hashes
            CHECK (fingerprint ~ '^[0-9a-f]{64}$' AND content_hash ~ '^[0-9a-f]{64}$')
    )
    """,
    """
    CREATE INDEX ix_qb_questions_select ON qb_questions
        (language, class_level, subject_code, chapter_id, topic_id, difficulty)
        WHERE review_status = 'approved' AND is_active
    """,
    """
    CREATE INDEX ix_qb_questions_adaptive ON qb_questions (topic_id, level, concept_tag)
        WHERE review_status = 'approved' AND is_active
    """,
    # The chapter cap: every write that can break it updates the chapter row, whose constraint checks
    # it and whose row lock serialises concurrent writers.
    """
    CREATE FUNCTION qb_questions_count() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'INSERT' OR (TG_OP = 'UPDATE' AND NEW.chapter_id IS DISTINCT FROM OLD.chapter_id) THEN
            UPDATE qb_chapters SET question_count = question_count + 1 WHERE chapter_id = NEW.chapter_id;
        END IF;
        IF TG_OP = 'DELETE' OR (TG_OP = 'UPDATE' AND NEW.chapter_id IS DISTINCT FROM OLD.chapter_id) THEN
            UPDATE qb_chapters SET question_count = question_count - 1 WHERE chapter_id = OLD.chapter_id;
        END IF;
        RETURN NULL;
    END $$
    """,
    """
    CREATE TRIGGER qb_questions_count AFTER INSERT OR DELETE OR UPDATE OF chapter_id ON qb_questions
        FOR EACH ROW EXECUTE FUNCTION qb_questions_count()
    """,
    """
    CREATE FUNCTION qb_questions_truncated() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        UPDATE qb_chapters SET question_count = 0 WHERE question_count <> 0;
        RETURN NULL;
    END $$
    """,
    """
    CREATE TRIGGER qb_questions_truncated AFTER TRUNCATE ON qb_questions
        FOR EACH STATEMENT EXECUTE FUNCTION qb_questions_truncated()
    """,
    # Only those triggers (nested: depth 2 or more) may change the counter.
    """
    CREATE FUNCTION qb_chapters_count_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF pg_trigger_depth() < 2 THEN
            IF TG_OP = 'INSERT' THEN
                IF NEW.question_count <> 0 THEN
                    RAISE EXCEPTION 'qb_chapters.question_count is kept by the database'
                        USING ERRCODE = 'check_violation';
                END IF;
            ELSIF NEW.question_count IS DISTINCT FROM OLD.question_count THEN
                RAISE EXCEPTION 'qb_chapters.question_count is kept by the database' USING ERRCODE = 'check_violation';
            END IF;
        END IF;
        RETURN NEW;
    END $$
    """,
    """
    CREATE TRIGGER qb_chapters_count_guard BEFORE INSERT OR UPDATE ON qb_chapters
        FOR EACH ROW EXECUTE FUNCTION qb_chapters_count_guard()
    """,
    """
    CREATE TABLE qb_sets (
        id          uuid NOT NULL DEFAULT gen_random_uuid(),
        user_id     uuid NOT NULL,
        request_id  uuid NOT NULL,
        mode        text NOT NULL,
        filters     jsonb NOT NULL,
        requested   smallint NOT NULL,
        served      smallint NOT NULL DEFAULT 0,
        created_at  timestamptz NOT NULL DEFAULT clock_timestamp(),
        closed_at   timestamptz,
        CONSTRAINT pk_qb_sets PRIMARY KEY (id),
        CONSTRAINT uq_qb_sets_id_user_id UNIQUE (id, user_id),
        CONSTRAINT uq_qb_sets_user_id_request_id UNIQUE (user_id, request_id),
        CONSTRAINT fk_qb_sets_user_id_users FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
        CONSTRAINT ck_qb_sets_mode CHECK (mode IN ('adaptive', 'test')),
        CONSTRAINT ck_qb_sets_requested CHECK (requested BETWEEN 1 AND 100),
        CONSTRAINT ck_qb_sets_served CHECK (served BETWEEN 0 AND requested)
    )
    """,
    "CREATE INDEX ix_qb_sets_user_id_created_at ON qb_sets (user_id, created_at)",
    """
    CREATE TABLE qb_set_items (
        set_id       uuid NOT NULL,
        position     smallint NOT NULL,
        user_id      uuid NOT NULL,
        question_id  text NOT NULL,
        topic_id     text NOT NULL,
        served_at    timestamptz NOT NULL DEFAULT clock_timestamp(),
        chosen       char(1),
        hinted       boolean NOT NULL DEFAULT false,
        is_correct   boolean,
        answered_at  timestamptz,
        CONSTRAINT pk_qb_set_items PRIMARY KEY (set_id, position),
        CONSTRAINT uq_qb_set_items_set_id_question_id UNIQUE (set_id, question_id),
        CONSTRAINT fk_qb_set_items_set_id_qb_sets FOREIGN KEY (set_id, user_id)
            REFERENCES qb_sets (id, user_id) ON DELETE CASCADE,
        CONSTRAINT fk_qb_set_items_question_id_qb_questions FOREIGN KEY (question_id, topic_id)
            REFERENCES qb_questions (question_id, topic_id),
        CONSTRAINT ck_qb_set_items_position CHECK (position >= 1),
        CONSTRAINT ck_qb_set_items_chosen CHECK (chosen IN ('A', 'B', 'C', 'D')),
        CONSTRAINT ck_qb_set_items_answer
            CHECK ((chosen IS NULL) = (answered_at IS NULL) AND (chosen IS NULL) = (is_correct IS NULL)),
        CONSTRAINT ck_qb_set_items_order CHECK (answered_at IS NULL OR answered_at >= served_at)
    )
    """,
    "CREATE INDEX ix_qb_set_items_user_id_topic_id_answered_at ON qb_set_items (user_id, topic_id, answered_at)",
    # Served unanswered; answered once, graded from the key (no caller can set is_correct); then final.
    """
    CREATE FUNCTION qb_set_items_answer() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'INSERT' THEN
            IF NEW.chosen IS NOT NULL OR NEW.is_correct IS NOT NULL OR NEW.answered_at IS NOT NULL THEN
                RAISE EXCEPTION 'a question is served unanswered' USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END IF;
        IF OLD.answered_at IS NOT NULL THEN
            RAISE EXCEPTION 'set item %/% is already answered', OLD.set_id, OLD.position
                USING ERRCODE = 'check_violation';
        END IF;
        IF (NEW.set_id, NEW.position, NEW.user_id, NEW.question_id, NEW.topic_id, NEW.served_at)
           IS DISTINCT FROM (OLD.set_id, OLD.position, OLD.user_id, OLD.question_id, OLD.topic_id, OLD.served_at) THEN
            RAISE EXCEPTION 'a served question cannot change' USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.chosen IS NOT NULL THEN
            NEW.is_correct := (SELECT q.correct_option = NEW.chosen FROM qb_questions q
                               WHERE q.question_id = NEW.question_id);
            NEW.answered_at := clock_timestamp();
        ELSE
            NEW.is_correct := NULL;
            NEW.answered_at := NULL;
        END IF;
        RETURN NEW;
    END $$
    """,
    """
    CREATE TRIGGER qb_set_items_answer BEFORE INSERT OR UPDATE ON qb_set_items
        FOR EACH ROW EXECUTE FUNCTION qb_set_items_answer()
    """,
)

DOWNGRADE = (
    "DROP TABLE qb_set_items",
    "DROP FUNCTION qb_set_items_answer()",
    "DROP TABLE qb_sets",
    "DROP TABLE qb_questions",
    "DROP FUNCTION qb_questions_count()",
    "DROP FUNCTION qb_questions_truncated()",
    "DROP TABLE qb_cases",
    "DROP TABLE qb_concepts",
    "DROP TABLE qb_topics",
    "DROP TABLE qb_chapters",
    "DROP FUNCTION qb_chapters_count_guard()",
    "DROP TABLE qb_books",
    "DROP TABLE qb_syllabus_versions",
)


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
