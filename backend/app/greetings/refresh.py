"""The weekly refresh of the study greetings by the LLM (app-level: one pool for everyone).

Lazy, not scheduled: the jobs timer is off in production, so the first GET /v1/greetings of a week
(Monday, DEFAULT_TIMEZONE) whose pool was written before that Monday starts ONE refresh in the
background and answers from the live pool at once. A request never waits on the model, startup
never touches it, and chat never depends on it.

- One refresh at a time across processes: a transaction-level advisory lock, then a re-check.
- A failure (model down or slow, unusable output, database error) keeps the live pool, is logged
  with a reason, and is retried at most once per RETRY_AFTER per process.
- The model's lines are untrusted: plain letters and basic punctuation, 3-8 words, deduplicated,
  at least MIN_POOL of them, or nothing is written.
- One transaction: the new lines are live from this Monday and the others retired from it. Lines
  are never deleted and a retired line is never revived, so every past week's set stays fixed
  (GET /v1/greetings/current, kept for older clients, replays them).
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from datetime import date, datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import StudyGreeting
from app.db.session import Database
from app.llm.base import ChatMessage, GenerationOptions
from app.logging import get_logger

log = get_logger(__name__)

LOCK_KEY = 0x67726565  # "gree": one advisory lock for the whole app
POOL_SIZE = 12
MIN_POOL = 10
RETRY_AFTER = timedelta(hours=1)
TIMEOUT_S = 30.0

PROMPT = (
    ChatMessage(
        role="system",
        content="You write the one-line greeting shown above the message box of a study app for school students.",
    ),
    ChatMessage(
        role="user",
        content=(
            f"Write {POOL_SIZE} different greetings that invite a student to ask a study question or doubt. "
            "Each is 4 to 7 words, friendly and encouraging, about studying only, and ends with a full stop, "
            "question mark or exclamation mark. Plain English, no emoji, no names, no quotes, no numbering. "
            "One greeting per line and nothing else."
        ),
    ),
)

_BULLET = re.compile(r"^\s*(?:[-*•]+|\d{1,2}[.)])\s*")
_PLAIN = re.compile(r"^[A-Za-z][A-Za-z0-9 ,'-]*[A-Za-z0-9][.!?]$")


def usable_lines(text: str) -> list[str]:
    """The model's reply as greetings we are willing to show: at most POOL_SIZE, maybe none."""
    lines: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = unicodedata.normalize("NFKC", raw).replace("’", "'")
        line = " ".join(_BULLET.sub("", line).strip().strip("\"'“”").split())
        if not (3 <= len(line.split()) <= 8 and 10 <= len(line) <= 60 and _PLAIN.match(line)):
            continue
        if line.lower() not in seen:
            seen.add(line.lower())
            lines.append(line)
    return lines[:POOL_SIZE]


def live_filter(week: date):
    return (StudyGreeting.active_from <= week) & or_(
        StudyGreeting.retired_from.is_(None), StudyGreeting.retired_from > week
    )


async def is_stale(session: AsyncSession, week: date) -> bool:
    """True when nothing live this week was written this week (or nothing is live at all)."""
    newest = await session.scalar(select(func.max(StudyGreeting.active_from)).where(live_filter(week)))
    return newest is None or newest < week


class GreetingRefresh:
    """Per app: at most one refresh task, and none within RETRY_AFTER of a failed one."""

    def __init__(self) -> None:
        self.task: asyncio.Task | None = None
        self.failed_at: datetime | None = None

    def start(self, db: Database, llm, week: date, now: datetime) -> None:
        if self.task is not None and not self.task.done():
            return
        if self.failed_at is not None and now - self.failed_at < RETRY_AFTER:
            return
        self.task = asyncio.create_task(self._run(db, llm, week, now))

    async def _run(self, db: Database, llm, week: date, now: datetime) -> None:
        if await refresh(db, llm, week) == "failed":
            self.failed_at = now

    async def stop(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


async def _generate(llm) -> str:
    stream = await llm.stream(list(PROMPT), GenerationOptions(temperature=0.9, max_output_tokens=600))
    return "".join([part.text async for part in stream.parts])


async def refresh(db: Database, llm, week: date) -> str:
    """Replace the pool live this week with new lines from the model: "ok", "skipped" or "failed"."""
    extra = {"week_of": week.isoformat()}
    try:
        async with db.sessionmaker() as session:
            if not await session.scalar(select(func.pg_try_advisory_xact_lock(LOCK_KEY))):
                log.info("greeting refresh skipped", extra={**extra, "reason": "busy"})
                return "skipped"
            if not await is_stale(session, week):
                log.info("greeting refresh skipped", extra={**extra, "reason": "fresh"})
                return "skipped"
            try:
                lines = usable_lines(await asyncio.wait_for(_generate(llm), TIMEOUT_S))
            except Exception as error:  # noqa: BLE001 - any model failure keeps the live pool
                log.warning(
                    "greeting refresh failed", extra={**extra, "reason": "llm", "error_type": type(error).__name__}
                )
                return "failed"
            rows = {row.text: row for row in await session.scalars(select(StudyGreeting))}
            # A line already live stays live; a retired one is not revived (its weeks stay as they were).
            keep = [line for line in lines if line not in rows or (rows[line].retired_from is None)]
            if len(keep) < MIN_POOL:
                log.warning("greeting refresh failed", extra={**extra, "reason": "unusable_output", "count": len(keep)})
                return "failed"
            session.add_all(StudyGreeting(text=line, active_from=week) for line in keep if line not in rows)
            await session.execute(
                update(StudyGreeting)
                .where(
                    StudyGreeting.retired_from.is_(None),
                    StudyGreeting.active_from < week,
                    StudyGreeting.text.not_in(keep),
                )
                .values(retired_from=week)
            )
            await session.commit()
            log.info("greeting refresh ok", extra={**extra, "count": len(keep)})
            return "ok"
    except Exception as error:  # noqa: BLE001 - never surfaces anywhere but the log
        log.error("greeting refresh failed", extra={**extra, "reason": "error", "error_type": type(error).__name__})
        return "failed"
