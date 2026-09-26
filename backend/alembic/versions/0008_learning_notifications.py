"""Learning streak days (India time), in-app notifications, and the in-app reminder switch.

Revision ID: 0008_learning_notifications
Revises: 0007_appearance
Create Date: 2026-09-27

Additive only: two new tables owned by a user (cascade on delete) and one boolean column with a
default, so the release before this one keeps working on the new schema. Streak days count from
the release that ships this; nothing is backfilled. Constraint names go through op.f() (final);
the choices are copied here, not imported.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0008_learning_notifications"
down_revision = "0007_appearance"
branch_labels = None
depends_on = None

IN_APP_KINDS = (
    "streak_milestone",
    "streak_reminder",
    "daily_reminder",
    "weekly_summary",
    "security_sign_in",
    "security_password_changed",
)
NOW = sa.text("clock_timestamp()")


def upgrade() -> None:
    op.create_table(
        "learning_daily_activity",
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("activity_date", sa.Date(), nullable=False),
        sa.Column("interactions", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_learning_daily_activity_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", "activity_date", name=op.f("pk_learning_daily_activity")),
        sa.CheckConstraint("interactions >= 1", name=op.f("ck_learning_daily_activity_interactions")),
    )
    op.create_table(
        "user_notifications",
        sa.Column("id", pg.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("body", sa.String(400), nullable=False),
        sa.Column("link", sa.String(200)),
        sa.Column("dedup_key", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_user_notifications_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_notifications")),
        sa.UniqueConstraint("user_id", "dedup_key", name=op.f("uq_user_notifications_user_id_dedup_key")),
        sa.CheckConstraint(f"kind IN {IN_APP_KINDS}", name=op.f("ck_user_notifications_kind")),
    )
    op.create_index("ix_user_notifications_user_id_created_at", "user_notifications", ["user_id", "created_at"])
    op.add_column(
        "notification_preferences",
        sa.Column("in_app_reminders", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("notification_preferences", "in_app_reminders")
    op.drop_index("ix_user_notifications_user_id_created_at", table_name="user_notifications")
    op.drop_table("user_notifications")
    op.drop_table("learning_daily_activity")
