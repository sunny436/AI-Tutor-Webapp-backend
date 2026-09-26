"""Appearance: theme, text size, contrast, motion, reading comfort, streak visibility.

Revision ID: 0007_appearance
Revises: 0006_notifications_support
Create Date: 2026-09-26

Additive only: one new table, owned by a user (cascade on delete). Constraint names go through
op.f() (final); the choices are copied here, not imported.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0007_appearance"
down_revision = "0006_notifications_support"
branch_labels = None
depends_on = None

THEMES = ("system", "light", "dark")
FONT_SIZES = ("small", "medium", "large", "x_large")


def upgrade() -> None:
    op.create_table(
        "appearance_settings",
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("theme", sa.String(10), nullable=False, server_default=sa.text("'system'")),
        sa.Column("font_size", sa.String(10), nullable=False, server_default=sa.text("'medium'")),
        sa.Column("high_contrast", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reduce_motion", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reading_comfort", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("show_streak", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_appearance_settings_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_appearance_settings")),
        sa.CheckConstraint(f"theme IN {THEMES}", name=op.f("ck_appearance_settings_theme")),
        sa.CheckConstraint(f"font_size IN {FONT_SIZES}", name=op.f("ck_appearance_settings_font_size")),
    )


def downgrade() -> None:
    op.drop_table("appearance_settings")
