"""Practice serves unreviewed questions too: the selection indexes cover approved and needs_review
questions (app/qbank/selection.py SERVABLE, the owner's decision of 2026-10-16).

Revision ID: 0016_practice_unreviewed
Revises: 0015_question_bank
Create Date: 2026-10-16

Additive and backward compatible: the two partial indexes are rebuilt with a wider predicate, which
still covers the previous release's approved-only queries. No data changes.
"""

from alembic import op

revision = "0016_practice_unreviewed"
down_revision = "0015_question_bank"
branch_labels = None
depends_on = None

NEW = "review_status IN ('approved', 'needs_review') AND is_active"
OLD = "review_status = 'approved' AND is_active"


def _indexes(predicate: str) -> None:
    op.execute("DROP INDEX ix_qb_questions_select")
    op.execute("DROP INDEX ix_qb_questions_adaptive")
    op.execute(
        "CREATE INDEX ix_qb_questions_select ON qb_questions "
        f"(language, class_level, subject_code, chapter_id, topic_id, difficulty) WHERE {predicate}"
    )
    op.execute(
        f"CREATE INDEX ix_qb_questions_adaptive ON qb_questions (topic_id, level, concept_tag) WHERE {predicate}"
    )


def upgrade() -> None:
    _indexes(NEW)


def downgrade() -> None:
    _indexes(OLD)
