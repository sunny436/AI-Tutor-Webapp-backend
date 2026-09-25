"""Identity: profile version, timezone, profile photo, email change codes, session cleanup index.

Revision ID: 0003_identity
Revises: 0002_knowledge_base
Create Date: 2026-09-25

Additive only, so the release that is live while this runs (before the switch) keeps working:
new nullable columns or columns with a constant default (no table rewrite), a new table, a
wider CHECK on email_codes.purpose, and a new index.

The first migration created the purpose CHECK through the naming convention a second time,
so databases have it as "ck_email_codes_ck_email_codes_purpose". Both possible names are
dropped with IF EXISTS and the constraint is re-added under its intended name.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0003_identity"
down_revision = "0002_knowledge_base"
branch_labels = None
depends_on = None

NOW = sa.text("clock_timestamp()")


def upgrade() -> None:
    op.add_column("users", sa.Column("profile_version", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("users", sa.Column("timezone", sa.String(64)))
    op.add_column("users", sa.Column("avatar_hash", sa.String(32)))
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True)))

    op.create_table(
        "user_avatars",
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("image", sa.LargeBinary(), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("hash", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_user_avatars_user_id_users"),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_avatars"),
        sa.CheckConstraint("octet_length(image) <= 65536", name="ck_user_avatars_image_size"),
        sa.CheckConstraint("content_type = 'image/webp'", name="ck_user_avatars_content_type"),
    )

    op.add_column("email_codes", sa.Column("user_id", pg.UUID(as_uuid=True)))
    op.create_foreign_key(
        "fk_email_codes_user_id_users", "email_codes", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_email_codes_user_id", "email_codes", ["user_id"])
    op.execute("ALTER TABLE email_codes DROP CONSTRAINT IF EXISTS ck_email_codes_ck_email_codes_purpose")
    op.execute("ALTER TABLE email_codes DROP CONSTRAINT IF EXISTS ck_email_codes_purpose")
    op.execute(
        "ALTER TABLE email_codes ADD CONSTRAINT ck_email_codes_purpose "
        "CHECK (purpose IN ('verify_email', 'reset_password', 'change_email'))"
    )
    # A change-email code always belongs to the user who asked for it.
    op.execute(
        "ALTER TABLE email_codes ADD CONSTRAINT ck_email_codes_change_email_user "
        "CHECK (purpose <> 'change_email' OR user_id IS NOT NULL)"
    )

    # Expired sessions (with their IP and user agent) are deleted by the retention job.
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.execute("DELETE FROM email_codes WHERE purpose = 'change_email'")
    op.execute("ALTER TABLE email_codes DROP CONSTRAINT IF EXISTS ck_email_codes_change_email_user")
    op.execute("ALTER TABLE email_codes DROP CONSTRAINT IF EXISTS ck_email_codes_purpose")
    op.execute(
        "ALTER TABLE email_codes ADD CONSTRAINT ck_email_codes_purpose "
        "CHECK (purpose IN ('verify_email', 'reset_password'))"
    )
    op.drop_index("ix_email_codes_user_id", table_name="email_codes")
    op.drop_constraint("fk_email_codes_user_id_users", "email_codes", type_="foreignkey")
    op.drop_column("email_codes", "user_id")
    op.drop_table("user_avatars")
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "avatar_hash")
    op.drop_column("users", "timezone")
    op.drop_column("users", "profile_version")
