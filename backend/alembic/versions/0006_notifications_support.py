"""Notifications and support: preferences, the email outbox, support requests.

Revision ID: 0006_notifications_support
Revises: 0005_progress
Create Date: 2026-09-25

Additive only: three new tables, each owned by a user (cascade on delete). The live release
never reads them. Constraint names go through op.f() (final). The lists of statuses and kinds
are copied here, not imported, so this revision never changes.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0006_notifications_support"
down_revision = "0005_progress"
branch_labels = None
depends_on = None

NOW = sa.text("clock_timestamp()")
OUTBOX_STATUSES = ("pending", "sending", "sent", "failed", "unknown", "dry_run", "suppressed", "expired")
SUPPORT_KINDS = ("question", "bug", "feedback", "account")
SUPPORT_STATUSES = ("open", "closed")


def upgrade() -> None:
    op.create_table(
        "notification_preferences",
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("daily_reminder", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("streak_warning", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("weekly_summary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("security_alerts", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_notification_preferences_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_notification_preferences")),
    )
    for flag in ("daily_reminder", "streak_warning", "weekly_summary"):
        op.create_index(
            op.f(f"ix_notification_preferences_{flag}"),
            "notification_preferences",
            ["user_id"],
            postgresql_where=sa.text(flag),
        )

    op.create_table(
        "email_outbox",
        sa.Column("id", pg.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", pg.UUID(as_uuid=True)),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("dedup_key", sa.String(200)),
        sa.Column("to_address", sa.String(320), nullable=False),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("send_before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("final_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_email_outbox_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_outbox")),
        sa.UniqueConstraint("dedup_key", name=op.f("uq_email_outbox_dedup_key")),
        sa.CheckConstraint(f"status IN {OUTBOX_STATUSES}", name=op.f("ck_email_outbox_status")),
        sa.CheckConstraint("attempts BETWEEN 0 AND 10", name=op.f("ck_email_outbox_attempts")),
    )
    op.create_index(op.f("ix_email_outbox_status_next_attempt_at"), "email_outbox", ["status", "next_attempt_at"])
    op.create_index(op.f("ix_email_outbox_user_id"), "email_outbox", ["user_id"])
    op.create_index(op.f("ix_email_outbox_final_at"), "email_outbox", ["final_at"])

    op.create_table(
        "support_requests",
        sa.Column("id", pg.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("client_request_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("subject", sa.String(120), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'open'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_support_requests_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_support_requests")),
        sa.UniqueConstraint("user_id", "client_request_id", name=op.f("uq_support_requests_user_id_client_request_id")),
        sa.CheckConstraint(f"kind IN {SUPPORT_KINDS}", name=op.f("ck_support_requests_kind")),
        sa.CheckConstraint(f"status IN {SUPPORT_STATUSES}", name=op.f("ck_support_requests_status")),
        sa.CheckConstraint("char_length(message) <= 4000", name=op.f("ck_support_requests_message_length")),
    )
    op.create_index(op.f("ix_support_requests_user_id_created_at"), "support_requests", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("support_requests")
    op.drop_table("email_outbox")
    op.drop_table("notification_preferences")
