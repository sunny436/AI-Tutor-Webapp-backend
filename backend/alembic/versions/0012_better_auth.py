"""Identity on Better Auth: sign-in methods, verifications, session tokens, the rollback mirrors.

Revision ID: 0012_better_auth
Revises: 0011_notification_cleared_at
Create Date: 2026-10-01

The web app's Better Auth (frontend/apps/app/src/lib/auth) now signs people in; the API still
checks every request against auth_sessions. Better Auth's models map onto these tables:
user -> users, session -> auth_sessions, account -> auth_accounts (new),
verification -> auth_verifications (new). No user id changes: each user's existing argon2 hash
becomes their "credential" sign-in method.

Backward compatible: a rollback runs 0011's code on this schema, and the two releases agree.
- users.email_verified (Better Auth) and users.email_verified_at (older code) follow each
  other, both ways (trigger).
- The credential's password and users.password_hash follow each other, both ways, so the
  password in force is the same whichever release runs.
- auth_sessions.token_hash is the SHA-256 of Better Auth's token (trigger): the API finds a
  session by that hash in every release, old sessions included. It is nullable now: Better Auth
  never writes it, and refuses to start while a column it never writes is required (the trigger
  fills it on every insert of a token; a NULL matches no lookup).

The web app signs in to PostgreSQL as aichat_auth (AUTH_DATABASE_URL), which can reach the
identity tables only. In production the role is created beforehand with a password; here it
is created without a login when missing (development, tests).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0012_better_auth"
down_revision = "0011_notification_cleared_at"
branch_labels = None
depends_on = None

NOW = sa.text("clock_timestamp()")
# The bell's kinds before and after: a Google account linked is a new security notice.
IN_APP_KINDS_0008 = (
    "streak_milestone",
    "streak_reminder",
    "daily_reminder",
    "weekly_summary",
    "security_sign_in",
    "security_password_changed",
)
IN_APP_KINDS = (*IN_APP_KINDS_0008, "security_google_linked")

TRIGGERS = (
    # The API finds every session by the SHA-256 of its token, whichever release wrote it.
    """
    CREATE FUNCTION auth_sessions_token_hash() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.token IS NOT NULL THEN
            NEW.token_hash := encode(sha256(convert_to(NEW.token, 'UTF8')), 'hex');
        END IF;
        RETURN NEW;
    END $$
    """,
    """
    CREATE TRIGGER auth_sessions_token_hash BEFORE INSERT OR UPDATE OF token ON auth_sessions
        FOR EACH ROW EXECUTE FUNCTION auth_sessions_token_hash()
    """,
    # email_verified (Better Auth) and email_verified_at (older code): whichever one a writer
    # changed, the other follows.
    """
    CREATE FUNCTION users_email_verified_mirror() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'INSERT' THEN
            IF NEW.email_verified_at IS NOT NULL THEN
                NEW.email_verified := true;
            END IF;
        ELSIF NEW.email_verified IS NOT DISTINCT FROM OLD.email_verified
              AND NEW.email_verified_at IS DISTINCT FROM OLD.email_verified_at THEN
            NEW.email_verified := NEW.email_verified_at IS NOT NULL;
        END IF;
        IF NEW.email_verified THEN
            NEW.email_verified_at := coalesce(NEW.email_verified_at, clock_timestamp());
        ELSE
            NEW.email_verified_at := NULL;
        END IF;
        RETURN NEW;
    END $$
    """,
    """
    CREATE TRIGGER users_email_verified_mirror BEFORE INSERT OR UPDATE ON users
        FOR EACH ROW EXECUTE FUNCTION users_email_verified_mirror()
    """,
    # The password in force, both ways. Each side writes only when the value differs, so the two
    # triggers settle after one hop.
    """
    CREATE FUNCTION auth_accounts_password_mirror() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            IF OLD.provider_id = 'credential' THEN
                UPDATE users SET password_hash = NULL WHERE id = OLD.user_id AND password_hash IS NOT NULL;
            END IF;
            RETURN OLD;
        END IF;
        IF NEW.provider_id = 'credential' THEN
            -- A new password (not the first one) is a change: Settings shows when.
            UPDATE users SET password_hash = NEW.password,
                   password_changed_at = CASE WHEN TG_OP = 'UPDATE' THEN clock_timestamp()
                                              ELSE password_changed_at END
             WHERE id = NEW.user_id AND password_hash IS DISTINCT FROM NEW.password;
        END IF;
        RETURN NEW;
    END $$
    """,
    """
    CREATE TRIGGER auth_accounts_password_mirror AFTER INSERT OR UPDATE OF password OR DELETE ON auth_accounts
        FOR EACH ROW EXECUTE FUNCTION auth_accounts_password_mirror()
    """,
    """
    CREATE FUNCTION users_password_mirror() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.password_hash IS NULL THEN
            RETURN NEW;
        END IF;
        UPDATE auth_accounts SET password = NEW.password_hash, updated_at = clock_timestamp()
         WHERE user_id = NEW.id AND provider_id = 'credential' AND password IS DISTINCT FROM NEW.password_hash;
        IF NOT EXISTS (SELECT 1 FROM auth_accounts WHERE user_id = NEW.id AND provider_id = 'credential') THEN
            INSERT INTO auth_accounts (user_id, account_id, provider_id, password)
            VALUES (NEW.id, NEW.id::text, 'credential', NEW.password_hash);
        END IF;
        RETURN NEW;
    END $$
    """,
    """
    CREATE TRIGGER users_password_mirror AFTER INSERT OR UPDATE OF password_hash ON users
        FOR EACH ROW EXECUTE FUNCTION users_password_mirror()
    """,
)
# The web app's role: identity tables only (never conversations, files or learning data).
WEB_ROLE = (
    """
    DO $$ BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'aichat_auth') THEN
            CREATE ROLE aichat_auth NOLOGIN;
        END IF;
    END $$
    """,
    "GRANT USAGE ON SCHEMA public TO aichat_auth",
    "GRANT SELECT, INSERT, UPDATE ON users TO aichat_auth",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON auth_sessions, auth_accounts, auth_verifications TO aichat_auth",
    "GRANT SELECT, INSERT ON auth_attempts TO aichat_auth",
)


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("UPDATE users SET email_verified = (email_verified_at IS NOT NULL)")
    op.add_column("users", sa.Column("image", sa.Text()))
    op.alter_column("users", "password_hash", nullable=True)

    op.add_column("auth_sessions", sa.Column("token", sa.Text()))
    op.create_unique_constraint("uq_auth_sessions_token", "auth_sessions", ["token"])
    op.alter_column("auth_sessions", "token_hash", existing_type=sa.String(64), nullable=True)

    op.create_table(
        "auth_accounts",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("access_token", sa.Text()),
        sa.Column("refresh_token", sa.Text()),
        sa.Column("id_token", sa.Text()),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True)),
        sa.Column("refresh_token_expires_at", sa.DateTime(timezone=True)),
        sa.Column("scope", sa.Text()),
        sa.Column("password", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_auth_accounts_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_auth_accounts"),
        sa.UniqueConstraint("provider_id", "account_id", name="uq_auth_accounts_provider_id_account_id"),
    )
    op.create_index("ix_auth_accounts_user_id", "auth_accounts", ["user_id"])

    op.create_table(
        "auth_verifications",
        sa.Column("id", pg.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("identifier", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_auth_verifications"),
    )
    op.create_index("ix_auth_verifications_identifier", "auth_verifications", ["identifier"])
    op.create_index("ix_auth_verifications_expires_at", "auth_verifications", ["expires_at"])

    op.drop_constraint(op.f("ck_user_notifications_kind"), "user_notifications", type_="check")
    op.create_check_constraint(op.f("ck_user_notifications_kind"), "user_notifications", f"kind IN {IN_APP_KINDS}")

    # Every user's existing password becomes their credential sign-in method, unchanged.
    op.execute(
        """
        INSERT INTO auth_accounts (user_id, account_id, provider_id, password, created_at)
        SELECT id, id::text, 'credential', password_hash, created_at FROM users WHERE password_hash IS NOT NULL
        """
    )

    # Each statement on its own: asyncpg runs one statement per call.
    for statement in (*TRIGGERS, *WEB_ROLE):
        op.execute(statement)


def downgrade() -> None:
    for statement in (
        "DROP TRIGGER users_password_mirror ON users",
        "DROP FUNCTION users_password_mirror()",
        "DROP TRIGGER users_email_verified_mirror ON users",
        "DROP FUNCTION users_email_verified_mirror()",
        "DROP TRIGGER auth_sessions_token_hash ON auth_sessions",
        "DROP FUNCTION auth_sessions_token_hash()",
        "REVOKE ALL ON users, auth_sessions, auth_attempts FROM aichat_auth",
        "REVOKE USAGE ON SCHEMA public FROM aichat_auth",
    ):
        op.execute(statement)
    op.execute("DELETE FROM user_notifications WHERE kind = 'security_google_linked'")
    op.drop_constraint(op.f("ck_user_notifications_kind"), "user_notifications", type_="check")
    op.create_check_constraint(op.f("ck_user_notifications_kind"), "user_notifications", f"kind IN {IN_APP_KINDS_0008}")
    op.drop_table("auth_verifications")
    op.drop_table("auth_accounts")
    op.execute("DROP FUNCTION auth_accounts_password_mirror()")
    op.drop_constraint("uq_auth_sessions_token", "auth_sessions", type_="unique")
    op.drop_column("auth_sessions", "token")
    op.execute("DELETE FROM auth_sessions WHERE token_hash IS NULL")
    op.alter_column("auth_sessions", "token_hash", existing_type=sa.String(64), nullable=False)
    # Accounts made without a password (Google) get an unusable hash: older code refuses it, and
    # its "forgot password" sets a real one.
    op.execute("UPDATE users SET password_hash = '!' WHERE password_hash IS NULL")
    op.alter_column("users", "password_hash", nullable=False)
    op.drop_column("users", "image")
    op.drop_column("users", "email_verified")
