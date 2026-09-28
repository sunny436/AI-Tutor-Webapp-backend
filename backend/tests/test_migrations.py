"""Migration 0009 on a disposable database, the way production gets it: an existing schema with
data (at 0008) -> upgrade -> downgrade -> upgrade again. Nothing outside the new table changes.

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


async def _snapshot() -> dict[str, tuple]:
    """Every table but the new one: its columns, and a digest of its rows."""
    conn = await asyncpg.connect(DSN)
    try:
        tables = [
            row["tablename"]
            for row in await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'study_greetings'"
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

        alembic("upgrade", "head")
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

        alembic("upgrade", "head")
        assert len(run(_query("SELECT 1 FROM study_greetings"))) == 12
    finally:
        run(_admin('DROP DATABASE IF EXISTS "aichat_migrations_test" WITH (FORCE)'))
