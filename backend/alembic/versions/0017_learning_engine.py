"""The learning engine: tests in the chat join the practice ledger, a served question keeps its hash,
and a student may give their exam date.

Revision ID: 0017_learning_engine
Revises: 0016_practice_unreviewed
Create Date: 2026-10-22

- qb_sets.mode gains 'chat': one practice set per question-bank test in the chat
  (app/qbank/chat_tests.py), so its answers are evidence (app/progress/practice.py).
- qb_set_items.served_hash: the question's content_hash when it was served, filled by the trigger on
  insert and as final as the rest of a served row. An answer to a question edited since
  (served_hash <> content_hash) is set aside from mastery. Rows served before this release keep NULL
  and are treated as current.
- learner_profiles.exam_date: the student's exam (the practice plan's exam window).

Additive and backward compatible: the previous release never writes a 'chat' set or reads the new
columns, and its inserts get served_hash from the trigger. NOT rollback-safe in the destructive
sense: the downgrade deletes every chat set with its answers, so it must never run without the
owner's explicit authorization (a deploy never downgrades).
"""

from alembic import op

revision = "0017_learning_engine"
down_revision = "0016_practice_unreviewed"
branch_labels = None
depends_on = None

# One statement per op.execute: asyncpg prepares each one, and refuses several at once.
UPGRADE = (
    """
    ALTER TABLE qb_sets DROP CONSTRAINT ck_qb_sets_mode,
        ADD CONSTRAINT ck_qb_sets_mode CHECK (mode IN ('adaptive', 'test', 'chat'))
    """,
    "ALTER TABLE qb_set_items ADD COLUMN served_hash text",
    # 0015's function, and the question's content hash stored when it is served (then final).
    """
    CREATE OR REPLACE FUNCTION qb_set_items_answer() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'INSERT' THEN
            IF NEW.chosen IS NOT NULL OR NEW.is_correct IS NOT NULL OR NEW.answered_at IS NOT NULL THEN
                RAISE EXCEPTION 'a question is served unanswered' USING ERRCODE = 'check_violation';
            END IF;
            NEW.served_hash := (SELECT q.content_hash FROM qb_questions q WHERE q.question_id = NEW.question_id);
            RETURN NEW;
        END IF;
        IF OLD.answered_at IS NOT NULL THEN
            RAISE EXCEPTION 'set item %/% is already answered', OLD.set_id, OLD.position
                USING ERRCODE = 'check_violation';
        END IF;
        IF (NEW.set_id, NEW.position, NEW.user_id, NEW.question_id, NEW.topic_id, NEW.served_at, NEW.served_hash)
           IS DISTINCT FROM
           (OLD.set_id, OLD.position, OLD.user_id, OLD.question_id, OLD.topic_id, OLD.served_at, OLD.served_hash) THEN
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
    "ALTER TABLE learner_profiles ADD COLUMN exam_date date",
)

DOWNGRADE = (
    "ALTER TABLE learner_profiles DROP COLUMN exam_date",
    # 0015's function, exactly.
    """
    CREATE OR REPLACE FUNCTION qb_set_items_answer() RETURNS trigger LANGUAGE plpgsql AS $$
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
    "ALTER TABLE qb_set_items DROP COLUMN served_hash",
    "DELETE FROM qb_sets WHERE mode = 'chat'",  # destructive: the chat sets and their answers
    """
    ALTER TABLE qb_sets DROP CONSTRAINT ck_qb_sets_mode,
        ADD CONSTRAINT ck_qb_sets_mode CHECK (mode IN ('adaptive', 'test'))
    """,
)


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
