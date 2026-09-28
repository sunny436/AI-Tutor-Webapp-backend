"""GET /v1/greetings/current: the study greeting above a new chat's composer, this week.

App-level, not per user: the same greeting for everyone for a whole week (Monday to Sunday in
DEFAULT_TIMEZONE), a different one the next week whenever two or more are live. The pick is
REPLAYED from the table alone, week by week from the first greeting's Monday: no stored state, no
cron, no writes. A pick from only "this week and today's rows" could not promise a change every
week once greetings are added or retired, so each greeting records the Mondays it is live
(`active_from` .. `retired_from`), which fixes every past week's set and so every past pick.

Authenticated like every /v1 route (tests/test_route_auth.py), although the data is global.
"""

from __future__ import annotations

import zoneinfo
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import Principal, get_principal, get_settings_dep
from app.db.models import StudyGreeting
from app.db.session import get_session
from app.errors import NotFound
from app.logging import get_logger
from app.schemas import ApiModel
from app.settings import Settings

router = APIRouter(prefix="/v1/greetings", tags=["greetings"])
log = get_logger(__name__)

EPOCH_MONDAY = date(1970, 1, 5)
WEEK = timedelta(days=7)


@dataclass(frozen=True)
class Greeting:
    id: int
    text: str
    active_from: date
    retired_from: date | None

    def live_on(self, monday: date) -> bool:
        return self.active_from <= monday and (self.retired_from is None or monday < self.retired_from)


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def pick(greetings: Sequence[Greeting], week: date) -> Greeting | None:
    """This week's greeting (`week` is its Monday), or None when none is live.

    Each week takes the greeting at (weeks since 1970-01-05) modulo the number live that week, in
    id order, and steps to the next one if that is last week's greeting. So a week with two or
    more live greetings never repeats the week before, whatever was added or retired.
    """
    ordered = sorted(greetings, key=lambda greeting: greeting.id)
    if not ordered:
        return None
    monday = min(greeting.active_from for greeting in ordered)
    previous: Greeting | None = None
    while monday <= week:
        live = [greeting for greeting in ordered if greeting.live_on(monday)]
        chosen = None
        if live:
            index = ((monday - EPOCH_MONDAY).days // 7) % len(live)
            chosen = live[index]
            if len(live) > 1 and chosen == previous:
                chosen = live[(index + 1) % len(live)]
        previous = chosen
        monday += WEEK
    return previous


def get_clock() -> Callable[[], datetime]:
    """Now, in UTC. A dependency so tests can cross a week boundary."""
    return lambda: datetime.now(UTC)


class StudyGreetingResponse(ApiModel):
    text: str
    week_of: date


@router.get(
    "/current",
    response_model=StudyGreetingResponse,
    summary="This week's study greeting (the same for everyone; 404 when none is live)",
)
async def current_greeting(
    _: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
    clock: Callable[[], datetime] = Depends(get_clock),
) -> StudyGreetingResponse:
    week = monday_of(clock().astimezone(zoneinfo.ZoneInfo(settings.default_timezone)).date())
    rows = (
        await db.execute(
            select(
                StudyGreeting.id, StudyGreeting.text, StudyGreeting.active_from, StudyGreeting.retired_from
            ).order_by(StudyGreeting.id)
        )
    ).all()
    chosen = pick([Greeting(*row) for row in rows], week)
    if chosen is None:
        log.warning("no active study greeting", extra={"week_of": week.isoformat()})
        raise NotFound("No study greeting is live this week.")
    return StudyGreetingResponse(text=chosen.text, week_of=week)
