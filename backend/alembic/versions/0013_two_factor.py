"""Two-step sign-in: an authenticator app (TOTP) and recovery codes (Better Auth's twoFactor).

Revision ID: 0013_two_factor
Revises: 0012_better_auth
Create Date: 2026-10-02

users.two_factor_enabled is Better Auth's flag: once true, every sign-in (password, email code or
Google) asks for the second step. auth_two_factors holds one row per user: the TOTP secret and the
recovery codes, both encrypted with BETTER_AUTH_SECRET, and the failure count that locks the
second step after repeated wrong codes. Only the web app's role (aichat_auth) is granted it.

Two security notices join the bell's kinds: two-step sign-in turned on, and turned off.

Backward compatible: the release before this one runs on this schema (it never reads the new
table, and the new column has a default). It does not ask for the second step, though, so a
rollback past this release turns two-step sign-in off until this release is deployed again
(docs/rollback.md).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0013_two_factor"
down_revision = "0012_better_auth"
branch_labels = None
depends_on = None

NOW = sa.text("clock_timestamp()")
IN_APP_KINDS_0012 = (
    "streak_milestone",
    "streak_reminder",
    "daily_reminder",
    "weekly_summary",
    "security_sign_in",
    "security_password_changed",
    "security_google_linked",
)
IN_APP_KINDS = (*IN_APP_KINDS_0012, "security_two_factor_on", "security_two_factor_off")


def upgrade() -> None:
    op.add_column("users", sa.Column("two_factor_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "auth_two_factors",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("secret", sa.Text(), nullable=False),
        sa.Column("backup_codes", sa.Text(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("failed_verification_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name="fk_auth_two_factors_user_id_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_two_factors"),
        sa.UniqueConstraint("user_id", name="uq_auth_two_factors_user_id"),
    )
    op.drop_constraint(op.f("ck_user_notifications_kind"), "user_notifications", type_="check")
    op.create_check_constraint(op.f("ck_user_notifications_kind"), "user_notifications", f"kind IN {IN_APP_KINDS}")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON auth_two_factors TO aichat_auth")


def downgrade() -> None:
    op.execute("REVOKE ALL ON auth_two_factors FROM aichat_auth")
    op.execute("DELETE FROM user_notifications WHERE kind IN ('security_two_factor_on', 'security_two_factor_off')")
    op.drop_constraint(op.f("ck_user_notifications_kind"), "user_notifications", type_="check")
    op.create_check_constraint(op.f("ck_user_notifications_kind"), "user_notifications", f"kind IN {IN_APP_KINDS_0012}")
    op.drop_table("auth_two_factors")
    op.drop_column("users", "two_factor_enabled")
