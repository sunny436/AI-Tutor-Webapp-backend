"""Progress: active time and questions per local day.

Revision ID: 0005_progress
Revises: 0004_learning
Create Date: 2026-09-25

Additive only: one new table, owned by a user (cascade on delete). Streaks count from the
release that ships this; nothing is backfilled. Constraint names go through op.f() (final).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0005_progress"
down_revision = "0004_learning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activity_days",
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("active_seconds", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("questions", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_minute_utc", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_activity_days_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", "local_date", name=op.f("pk_activity_days")),
        sa.CheckConstraint("active_seconds BETWEEN 0 AND 86400", name=op.f("ck_activity_days_active_seconds")),
        sa.CheckConstraint("questions >= 0", name=op.f("ck_activity_days_questions")),
    )


def downgrade() -> None:
    op.drop_table("activity_days")
