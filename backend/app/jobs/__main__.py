"""`python -m app.jobs`: one run of the jobs worker (app/jobs/runner.py), then exit.

Exit status 0 when the run finished, was disabled or found another run holding the lock; 1 when
it could not run at all (configuration, database). Failures inside a step are logged and do not
change the exit status: the next run, a minute later, tries again.
"""

from __future__ import annotations

import asyncio
import sys

from app.auth.emails import build_email_sender
from app.db.session import Database
from app.jobs.runner import run_once
from app.logging import configure_logging, get_logger
from app.settings import Settings


async def _run(settings: Settings) -> dict:
    db = Database(settings)
    try:
        return await run_once(settings, db, build_email_sender(settings))
    finally:
        await db.dispose()


def main() -> int:
    settings = Settings()
    configure_logging(settings.log_level)
    log = get_logger("app.jobs")
    try:
        settings.validate_for_env()
        report = asyncio.run(_run(settings))
    except Exception as error:  # noqa: BLE001 - reported, then a non-zero exit for systemd
        log.exception("jobs run could not run", extra={"error_type": type(error).__name__})
        return 1
    log.info("jobs run finished", extra={"report": report})
    return 0


if __name__ == "__main__":
    sys.exit(main())
