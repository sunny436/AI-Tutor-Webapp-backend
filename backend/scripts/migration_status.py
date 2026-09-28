"""Where the database schema stands relative to THIS code's migrations. Prints one JSON line.

    python scripts/migration_status.py

    {"database": "0001_initial", "head": "0002_knowledge_base",
     "pending": ["0002_knowledge_base"], "database_known": true}

`database` is null for an empty database. `database_known` is false when the database is at a
revision this code does not have (it was migrated by a NEWER release), in which case running
this code against it is only safe if that newer migration was backward compatible.

deploy/server/update.sh uses it, when a deploy brings new migration files, to decide whether
migrations must run and whether a rollback puts old code on a newer schema.
Reads DATABASE_URL from the environment, like the app. Never writes anything.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings import Settings  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


async def database_revision(url: str) -> str | None:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            if not await conn.scalar(text("select to_regclass('public.alembic_version') is not null")):
                return None
            return await conn.scalar(text("select version_num from alembic_version limit 1"))
    finally:
        await engine.dispose()


def main() -> int:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if len(heads) != 1:
        print(json.dumps({"error": f"expected one migration head, found {len(heads)}"}))
        return 2
    head = heads[0]
    database = asyncio.run(database_revision(Settings().database_url))

    pending: list[str] = []
    known = database is None
    for revision in script.walk_revisions(base="base", head=head):  # newest first
        if revision.revision == database:
            known = True
            break
        pending.append(revision.revision)
    if not known:
        pending = []  # the database is ahead of (or unrelated to) this code
    print(json.dumps({"database": database, "head": head, "pending": pending[::-1], "database_known": known}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
