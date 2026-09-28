"""Study greetings: the app-level line above the composer of a new chat, one per week.

Revision ID: 0009_study_greetings
Revises: 0008_learning_notifications
Create Date: 2026-09-28

Additive only: one new table, not owned by any user. A greeting is live for whole weeks, from
`active_from` (a Monday) until `retired_from` (a later Monday, or never), so the set of any week is
fixed and the weekly pick can be replayed from this table alone (app/greetings). Retire a greeting
from a future Monday; never delete one. The seed never overwrites a row that already exists.
"""

from datetime import date

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0009_study_greetings"
down_revision = "0008_learning_notifications"
branch_labels = None
depends_on = None

GREETINGS = (
    "Ready to learn something new?",
    "What's puzzling you today?",
    "Let's solve this together.",
    "Ready for your next doubt?",
    "What are you studying today?",
    "Let's make this topic simple.",
    "Got a tough question today?",
    "Let's tackle your next question.",
    "Ready to understand it better?",
    "What should we learn today?",
    "Which chapter are we studying today?",
    "Bring me your toughest doubt today.",
)
LAUNCH_MONDAY = date(2026, 9, 28)


def upgrade() -> None:
    table = op.create_table(
        "study_greetings",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), nullable=False),
        sa.Column("text", sa.String(80), nullable=False),
        sa.Column("active_from", sa.Date(), nullable=False),
        sa.Column("retired_from", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_study_greetings")),
        sa.UniqueConstraint("text", name=op.f("uq_study_greetings_text")),
        sa.CheckConstraint("char_length(btrim(text)) BETWEEN 1 AND 80", name=op.f("ck_study_greetings_text")),
        sa.CheckConstraint("EXTRACT(ISODOW FROM active_from) = 1", name=op.f("ck_study_greetings_active_from_monday")),
        sa.CheckConstraint(
            "retired_from IS NULL OR (EXTRACT(ISODOW FROM retired_from) = 1 AND retired_from > active_from)",
            name=op.f("ck_study_greetings_retired_from"),
        ),
    )
    op.execute(
        pg.insert(table)
        .values([{"text": greeting, "active_from": LAUNCH_MONDAY} for greeting in GREETINGS])
        .on_conflict_do_nothing(index_elements=["text"])
    )


def downgrade() -> None:
    op.drop_table("study_greetings")
