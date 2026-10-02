"""Migrations 0009 and 0010 on a disposable database, the way production gets them: an existing
schema with data -> upgrade -> downgrade -> upgrade again. Nothing outside the new tables changes.

Its own database (`aichat_migrations_test`, same server as the test database), created and
dropped here, so the shared test database is never downgraded.
"""

import asyncio
import subprocess
import sys
import threading

import asyncpg

from tests.conftest import ROOT, TEST_DATABASE_URL, _asyncpg_dsn

URL = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/aichat_migrations_test"
DSN = _asyncpg_dsn(URL)
ADMIN = DSN.rsplit("/", 1)[0] + "/postgres"
BEFORE = "0008_learning_notifications"
GREETINGS = "0009_study_greetings"
FILE_TABLES = ("user_files", "user_file_blobs", "file_chunks", "message_attachments")


def run(coroutine):
    """In a thread of its own, so this event loop never touches pytest-asyncio's."""
    result = {}
    worker = threading.Thread(target=lambda: result.setdefault("value", asyncio.run(coroutine)))
    worker.start()
    worker.join()
    return result.get("value")


def alembic(*args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"url={URL}", *args], cwd=ROOT, check=True, capture_output=True
    )


async def _admin(sql: str) -> None:
    conn = await asyncpg.connect(ADMIN)
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


async def _query(sql: str, *args):
    conn = await asyncpg.connect(DSN)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


async def _snapshot(new_tables: tuple[str, ...] = ("study_greetings",)) -> dict[str, tuple]:
    """Every table but the new ones: its columns, and a digest of its rows."""
    conn = await asyncpg.connect(DSN)
    try:
        tables = [
            row["tablename"]
            for row in await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> ALL($1::text[])",
                list(new_tables),
            )
        ]
        snapshot = {}
        for table in tables:
            columns = await conn.fetch(
                "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = $1 ORDER BY ordinal_position",
                table,
            )
            digest = await conn.fetchval(
                f"SELECT md5(coalesce(string_agg(t::text, ',' ORDER BY t::text), '')) FROM \"{table}\" t"
            )
            snapshot[table] = (tuple(tuple(column) for column in columns), digest)
        return snapshot
    finally:
        await conn.close()


def test_migration_0009_upgrades_downgrades_and_upgrades_again_without_touching_anything_else():
    run(_admin('DROP DATABASE IF EXISTS "aichat_migrations_test" WITH (FORCE)'))
    run(_admin('CREATE DATABASE "aichat_migrations_test"'))
    try:
        alembic("upgrade", BEFORE)
        # Existing data, as production has it.
        run(
            _query(
                "INSERT INTO users (email, password_hash, display_name) VALUES ($1, 'x', 'Existing student')",
                "existing@example.com",
            )
        )
        before = run(_snapshot())
        assert before["users"][1] != run(_query("SELECT md5('')"))[0][0]  # the row is really there

        alembic("upgrade", GREETINGS)
        rows = run(_query("SELECT text, active_from, retired_from FROM study_greetings ORDER BY id"))
        assert len(rows) == 12
        assert {str(row["active_from"]) for row in rows} == {"2026-09-28"}
        assert all(row["retired_from"] is None for row in rows)
        constraints = {
            row["conname"]: row["contype"]
            for row in run(
                _query(
                    "SELECT conname, contype::text AS contype FROM pg_constraint "
                    "WHERE conrelid = 'study_greetings'::regclass"
                )
            )
        }
        assert constraints == {
            "pk_study_greetings": "p",
            "uq_study_greetings_text": "u",
            "ck_study_greetings_text": "c",
            "ck_study_greetings_active_from_monday": "c",
            "ck_study_greetings_retired_from": "c",
        }
        after = run(_snapshot())
        assert {table: value for table, value in after.items() if table != "alembic_version"} == {
            table: value for table, value in before.items() if table != "alembic_version"
        }

        alembic("downgrade", BEFORE)
        assert run(_query("SELECT to_regclass('public.study_greetings') AS t"))[0]["t"] is None
        down = run(_snapshot())
        assert {t: v for t, v in down.items() if t != "alembic_version"} == {
            t: v for t, v in before.items() if t != "alembic_version"
        }

        alembic("upgrade", GREETINGS)
        assert len(run(_query("SELECT 1 FROM study_greetings"))) == 12
    finally:
        run(_admin('DROP DATABASE IF EXISTS "aichat_migrations_test" WITH (FORCE)'))


def test_migration_0010_upgrades_downgrades_and_upgrades_again_without_touching_anything_else():
    run(_admin('DROP DATABASE IF EXISTS "aichat_migrations_test" WITH (FORCE)'))
    run(_admin('CREATE DATABASE "aichat_migrations_test"'))
    try:
        alembic("upgrade", GREETINGS)
        run(
            _query(
                "INSERT INTO users (email, password_hash, display_name) VALUES ($1, 'x', 'Existing student')",
                "existing@example.com",
            )
        )
        before = run(_snapshot(FILE_TABLES))

        alembic("upgrade", "0010_user_files")
        for table in FILE_TABLES:
            assert run(_query("SELECT to_regclass($1) AS t", f"public.{table}"))[0]["t"] is not None, table
        column = run(
            _query(
                "SELECT format_type(atttypid, atttypmod) AS t FROM pg_attribute "
                "WHERE attrelid = 'file_chunks'::regclass AND attname = 'embedding'"
            )
        )[0]["t"]
        assert column == "vector(1536)"
        after = run(_snapshot(FILE_TABLES))
        assert {t: v for t, v in after.items() if t != "alembic_version"} == {
            t: v for t, v in before.items() if t != "alembic_version"
        }

        alembic("downgrade", GREETINGS)
        for table in FILE_TABLES:
            assert run(_query("SELECT to_regclass($1) AS t", f"public.{table}"))[0]["t"] is None, table
        down = run(_snapshot(FILE_TABLES))
        assert {t: v for t, v in down.items() if t != "alembic_version"} == {
            t: v for t, v in before.items() if t != "alembic_version"
        }

        alembic("upgrade", "head")
        assert run(_query("SELECT count(*) AS n FROM user_files"))[0]["n"] == 0
    finally:
        run(_admin('DROP DATABASE IF EXISTS "aichat_migrations_test" WITH (FORCE)'))


AUTH_BEFORE = "0011_notification_cleared_at"
AUTH_AFTER = "0012_better_auth"


def test_migration_0012_keeps_every_account_and_both_releases_agree():
    """Better Auth's tables on the existing identity data: no user id changes, every password
    becomes the same hash in a credential account, and the mirrors keep 0011's code and 0012's in
    agreement in both directions (the rollback path). Its role, aichat_auth, is created without a
    login when missing; it stays in the cluster, inert."""
    run(_admin('DROP DATABASE IF EXISTS "aichat_migrations_test" WITH (FORCE)'))
    run(_admin('CREATE DATABASE "aichat_migrations_test"'))
    try:
        alembic("upgrade", AUTH_BEFORE)
        run(
            _query(
                "INSERT INTO users (email, password_hash, email_verified_at) VALUES "
                "('kept@example.com', '$argon2id$kept', now()), ('pending@example.com', '$argon2id$pending', NULL)"
            )
        )
        run(
            _query(
                "INSERT INTO auth_sessions (user_id, token_hash, expires_at) "
                "SELECT id, repeat('a', 64), now() + interval '1 day' FROM users WHERE email = 'kept@example.com'"
            )
        )
        ids = {row["email"]: row["id"] for row in run(_query("SELECT id, email FROM users"))}

        alembic("upgrade", AUTH_AFTER)
        users = {row["email"]: row for row in run(_query("SELECT * FROM users"))}
        assert {email: row["id"] for email, row in users.items()} == ids
        assert users["kept@example.com"]["email_verified"] and not users["pending@example.com"]["email_verified"]
        accounts = {
            row["user_id"]: row
            for row in run(_query("SELECT user_id, account_id, provider_id, password FROM auth_accounts"))
        }
        assert {accounts[ids[e]]["password"] for e in ids} == {"$argon2id$kept", "$argon2id$pending"}
        assert all(
            row["provider_id"] == "credential" and row["account_id"] == str(row["user_id"]) for row in accounts.values()
        )
        assert tuple(run(_query("SELECT token_hash, token FROM auth_sessions"))[0]) == ("a" * 64, None)

        # A Better Auth session: only the token is written; the trigger stores its SHA-256.
        run(
            _query(
                "INSERT INTO auth_sessions (user_id, token, expires_at) "
                "VALUES ($1, 'better-auth-token', now() + interval '1 day')",
                ids["kept@example.com"],
            )
        )
        hashed = run(_query("SELECT token_hash FROM auth_sessions WHERE token = 'better-auth-token'"))[0]["token_hash"]
        assert hashed == run(_query("SELECT encode(sha256('better-auth-token'::bytea), 'hex') AS h"))[0]["h"]

        # 0012's code changes a password (Better Auth): 0011's column follows, and the change is dated.
        run(_query("UPDATE auth_accounts SET password = '$argon2id$new' WHERE user_id = $1", ids["kept@example.com"]))
        kept = run(_query("SELECT password_hash, password_changed_at FROM users WHERE email = 'kept@example.com'"))[0]
        assert kept["password_hash"] == "$argon2id$new" and kept["password_changed_at"] is not None
        # 0011's code (after a rollback) changes one: the credential follows.
        run(_query("UPDATE users SET password_hash = '$argon2id$old-code' WHERE email = 'kept@example.com'"))
        assert run(_query("SELECT password FROM auth_accounts WHERE user_id = $1", ids["kept@example.com"]))[0][0] == (
            "$argon2id$old-code"
        )
        # 0011's code verifies an address and signs someone up: 0012's flag and credential follow.
        run(_query("UPDATE users SET email_verified_at = now() WHERE email = 'pending@example.com'"))
        assert run(_query("SELECT email_verified FROM users WHERE email = 'pending@example.com'"))[0][0] is True
        run(_query("INSERT INTO users (email, password_hash) VALUES ('old-code@example.com', '$argon2id$signup')"))
        assert (
            run(
                _query(
                    "SELECT a.password FROM auth_accounts a JOIN users u ON u.id = a.user_id "
                    "WHERE u.email = 'old-code@example.com' AND a.provider_id = 'credential'"
                )
            )[0][0]
            == "$argon2id$signup"
        )
        # Removing the credential (no password any more) clears 0011's column; deletion cascades.
        run(_query("DELETE FROM auth_accounts WHERE user_id = $1", ids["pending@example.com"]))
        assert run(_query("SELECT password_hash FROM users WHERE email = 'pending@example.com'"))[0][0] is None
        run(_query("DELETE FROM users WHERE email = 'kept@example.com'"))
        assert run(_query("SELECT count(*) FROM auth_accounts WHERE user_id = $1", ids["kept@example.com"]))[0][0] == 0

        # The web app's role reaches identity tables only.
        grants = {
            row["table_name"]
            for row in run(
                _query(
                    "SELECT DISTINCT table_name FROM information_schema.role_table_grants WHERE grantee = 'aichat_auth'"
                )
            )
        }
        assert grants == {"users", "auth_sessions", "auth_accounts", "auth_verifications", "auth_attempts"}

        alembic("downgrade", AUTH_BEFORE)
        assert run(_query("SELECT to_regclass('public.auth_accounts') AS t"))[0]["t"] is None
        # The account left without a password gets an unusable hash 0011's code refuses.
        assert run(_query("SELECT password_hash FROM users WHERE email = 'pending@example.com'"))[0][0] == "!"
        alembic("upgrade", AUTH_AFTER)
        assert run(_query("SELECT count(*) FROM auth_accounts"))[0][0] == 2
    finally:
        run(_admin('DROP DATABASE IF EXISTS "aichat_migrations_test" WITH (FORCE)'))


def test_migration_0013_two_step_sign_in_is_additive_and_rolls_back_cleanly():
    """0013 adds a column with a default and a table: every existing row is untouched (the release
    before it runs on this schema), the web app's role can reach the new table, and a downgrade
    leaves exactly the 0012 schema again."""
    run(_admin('DROP DATABASE IF EXISTS "aichat_migrations_test" WITH (FORCE)'))
    run(_admin('CREATE DATABASE "aichat_migrations_test"'))
    try:
        alembic("upgrade", AUTH_AFTER)
        run(
            _query(
                "INSERT INTO users (email, password_hash, email_verified_at) VALUES ('two@example.com', '$a', now())"
            )
        )
        before = run(_snapshot(new_tables=()))

        alembic("upgrade", "0013_two_factor")
        assert run(_query("SELECT two_factor_enabled FROM users"))[0][0] is False
        user_id = run(_query("SELECT id FROM users"))[0][0]
        run(_query("INSERT INTO auth_two_factors (user_id, secret, backup_codes) VALUES ($1, 's', 'b')", user_id))
        run(
            _query(
                "INSERT INTO user_notifications (user_id, kind, title, body, dedup_key) "
                "VALUES ($1, 'security_two_factor_on', 't', 'b', 'k')",
                user_id,
            )
        )
        grants = {
            row["privilege_type"]
            for row in run(
                _query(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE grantee = 'aichat_auth' AND table_name = 'auth_two_factors'"
                )
            )
        }
        assert grants == {"SELECT", "INSERT", "UPDATE", "DELETE"}

        alembic("downgrade", AUTH_AFTER)
        assert run(_query("SELECT to_regclass('public.auth_two_factors') AS t"))[0]["t"] is None
        assert run(_snapshot(new_tables=())) == before
        alembic("upgrade", "0013_two_factor")
        assert run(_query("SELECT count(*) FROM users"))[0][0] == 1
    finally:
        run(_admin('DROP DATABASE IF EXISTS "aichat_migrations_test" WITH (FORCE)'))
