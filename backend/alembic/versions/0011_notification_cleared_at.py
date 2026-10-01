"""Notifications: "Clear all" in the bell.

Revision ID: 0011_notification_cleared_at
Revises: 0010_user_files
Create Date: 2026-10-01

Additive only: one nullable column, so older code runs unchanged on this schema (a rollback never
needs the downgrade). A cleared notification leaves the bell and counts as read; its row, with its
dedup_key, stays until retention deletes it with the other read notifications, so clearing never
lets a reminder or an alert happen twice.
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_notification_cleared_at"
down_revision = "0010_user_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_notifications", sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("user_notifications", "cleared_at")
