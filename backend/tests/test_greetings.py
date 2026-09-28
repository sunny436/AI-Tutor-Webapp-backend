"""Study greetings: one per week, the same for everyone, a different one every week.

The pick is tested as a product rule (never the same greeting two weeks running while two or more
are live, whatever is added or retired), and through the real chain: clock -> week in
DEFAULT_TIMEZONE -> database -> live filter -> pick -> response, read-only.
"""

import asyncio
import importlib.util
import logging
import random
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event, text

from app.db.models import StudyGreeting
from app.greetings import refresh as greeting_refresh
from app.greetings.refresh import usable_lines
from app.greetings.router import EPOCH_MONDAY, Greeting, get_clock, pick
from app.llm.base import LLMUnavailable
from tests.conftest import register

MONDAY = date(2026, 9, 28)


def live(count: int, start: date = MONDAY) -> list[Greeting]:
    return [Greeting(index + 1, f"Greeting {index + 1}", start, None) for index in range(count)]


def picks(rows: list[Greeting], weeks: int, start: date = MONDAY) -> list[int | None]:
    return [(chosen.id if (chosen := pick(rows, start + timedelta(weeks=week))) else None) for week in range(weeks)]


def no_repeats(ids: list[int | None]) -> bool:
    return all(a is None or a != b for a, b in zip(ids, ids[1:], strict=False))


# ------------------------------------------------------------------ the rule


def test_twelve_greetings_change_every_week_and_all_come_round():
    ids = picks(live(12), 100)
    assert no_repeats(ids)
    for start in range(0, 88):  # any 12 weeks in a row show all 12
        assert sorted(ids[start : start + 12]) == list(range(1, 13))


def test_two_greetings_alternate():
    ids = picks(live(2), 20)
    assert no_repeats(ids)
    assert set(ids) == {1, 2}


def test_one_greeting_is_shown_every_week():
    assert picks(live(1), 5) == [1, 1, 1, 1, 1]


def test_nothing_live_is_none():
    assert pick([], MONDAY) is None
    assert pick(live(3, start=MONDAY + timedelta(weeks=2)), MONDAY) is None  # not live yet
    assert pick([Greeting(1, "Old", MONDAY - timedelta(weeks=2), MONDAY)], MONDAY) is None  # retired


def test_retired_and_future_greetings_are_never_shown():
    rows = [
        *live(3),
        Greeting(4, "Retired", MONDAY, MONDAY + timedelta(weeks=1)),
        Greeting(5, "Later", MONDAY + timedelta(weeks=50), None),
    ]
    for week, chosen in enumerate(picks(rows, 40)):
        if week >= 1:
            assert chosen != 4
        assert chosen != 5


def test_a_week_of_new_count_never_repeats_last_week_where_plain_modulo_would():
    # Find a Monday on which "index = week % live count" would show last week's greeting again after a
    # fourth greeting goes live, and prove the pick does not.
    three = live(3)
    for offset in range(1, 60):
        change = MONDAY + timedelta(weeks=offset)
        before = [greeting for greeting in three if greeting.live_on(change - timedelta(weeks=1))]
        weeks_before = ((change - EPOCH_MONDAY).days // 7) - 1
        naive_before = before[weeks_before % 3]
        after = [*three, Greeting(4, "Added", change, None)]
        naive_after = after[(weeks_before + 1) % 4]
        if naive_after == naive_before and pick(three, change - timedelta(weeks=1)) == naive_before:
            rows = after
            break
    else:
        pytest.fail("no week where plain modulo repeats: the scenario proves nothing")
    assert pick(rows, change) != pick(rows, change - timedelta(weeks=1))
    assert no_repeats(picks(rows, offset + 20))


def test_retiring_this_weeks_greeting_still_changes_next_week():
    rows = live(3)
    shown = pick(rows, MONDAY)
    rows = [Greeting(g.id, g.text, g.active_from, MONDAY + timedelta(weeks=1) if g == shown else None) for g in rows]
    assert pick(rows, MONDAY).id == shown.id
    next_week = pick(rows, MONDAY + timedelta(weeks=1))
    assert next_week is not None and next_week.id != shown.id


def test_any_schedule_of_additions_and_retirements_never_repeats_back_to_back():
    generator = random.Random(1729)  # a fixed schedule set: deterministic, not random selection
    for _ in range(300):
        rows = []
        for greeting_id in range(1, generator.randint(2, 9)):
            start = MONDAY + timedelta(weeks=generator.randint(0, 20))
            end = start + timedelta(weeks=generator.randint(1, 30)) if generator.random() < 0.5 else None
            rows.append(Greeting(greeting_id, f"G{greeting_id}", start, end))
        for week in range(1, 60):
            monday = MONDAY + timedelta(weeks=week)
            chosen, previous = pick(rows, monday), pick(rows, monday - timedelta(weeks=1))
            if chosen is not None:
                assert chosen.live_on(monday)
            if sum(greeting.live_on(monday) for greeting in rows) >= 2:
                assert chosen != previous, (rows, monday)


def test_the_seed_is_study_greetings_of_a_few_words():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0009_study_greetings.py"
    spec = importlib.util.spec_from_file_location("seed", path)
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    assert 10 <= len(seed.GREETINGS) <= 15
    assert len(set(seed.GREETINGS)) == len(seed.GREETINGS)
    for greeting in seed.GREETINGS:
        assert 4 <= len(greeting.split()) <= 7, greeting
        assert len(greeting) <= 80
        assert not any(generic in greeting.lower() for generic in ("good morning", "welcome back", "how are you"))
    assert seed.LAUNCH_MONDAY.weekday() == 0


# ------------------------------------------------------------------ the real chain


async def _insert(app, rows: list[Greeting]) -> None:
    async with app.state.db.sessionmaker() as session:
        session.add_all(
            StudyGreeting(text=row.text, active_from=row.active_from, retired_from=row.retired_from) for row in rows
        )
        await session.commit()


async def _rows(app) -> list[Greeting]:
    async with app.state.db.sessionmaker() as session:
        result = await session.execute(text("SELECT id, text, active_from, retired_from FROM study_greetings"))
        return [Greeting(*row) for row in result.all()]


def _at(app, moment: datetime) -> None:
    app.dependency_overrides[get_clock] = lambda: lambda: moment


async def test_every_user_gets_the_same_greeting_all_week_and_a_new_one_on_monday_in_india(client, app):
    await _insert(app, live(12))
    rows = await _rows(app)
    alice = (await register(client, app))["headers"]
    bob = (await register(client, app))["headers"]

    async def greeting(headers, moment: datetime) -> dict:
        _at(app, moment)
        response = await client.get("/v1/greetings/current", headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    # Monday 2026-10-05 00:00 IST is Sunday 18:30 UTC.
    monday_start = datetime(2026, 10, 4, 18, 30, tzinfo=UTC)
    sunday_end = monday_start - timedelta(minutes=1)  # Sunday 23:59 IST
    last_week = await greeting(alice, sunday_end)
    this_week = await greeting(alice, monday_start)
    assert last_week == {"text": pick(rows, date(2026, 9, 28)).text, "weekOf": "2026-09-28"}
    assert this_week == {"text": pick(rows, date(2026, 10, 5)).text, "weekOf": "2026-10-05"}
    assert this_week["text"] != last_week["text"]
    # The whole week, for everyone.
    for moment in (monday_start, monday_start + timedelta(days=3), monday_start + timedelta(days=7, minutes=-1)):
        assert await greeting(alice, moment) == this_week
        assert await greeting(bob, moment) == this_week


async def test_retired_greetings_are_skipped_and_none_live_is_404_and_logged(client, app, caplog):
    await _insert(app, [Greeting(0, "Only retired", MONDAY - timedelta(weeks=4), MONDAY)])
    headers = (await register(client, app))["headers"]
    _at(app, datetime(2026, 9, 30, 6, 0, tzinfo=UTC))
    with caplog.at_level(logging.WARNING, logger="app.greetings.router"):
        response = await client.get("/v1/greetings/current", headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert "no active study greeting" in caplog.text


async def test_signed_out_is_refused(client, app):
    await _insert(app, live(2))
    assert (await client.get("/v1/greetings/current")).status_code == 401


async def test_reading_the_greeting_writes_nothing_even_concurrently(client, app):
    await _insert(app, live(12))
    headers = (await register(client, app))["headers"]
    _at(app, datetime(2026, 10, 7, 6, 0, tzinfo=UTC))

    async def counts() -> dict[str, int]:
        async with app.state.db.sessionmaker() as session:
            names = (
                await session.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
                    )
                )
            ).scalars()
            return {
                name: (await session.execute(text(f'SELECT count(*) FROM "{name}"'))).scalar_one() for name in names
            }

    before, greetings_before = await counts(), await _rows(app)
    statements: list[str] = []
    listener = lambda *args: statements.append(args[2])  # noqa: E731  (conn, cursor, statement, ...)
    event.listen(app.state.db.engine.sync_engine, "before_cursor_execute", listener)
    try:
        responses = await asyncio.gather(*(client.get("/v1/greetings/current", headers=headers) for _ in range(10)))
    finally:
        event.remove(app.state.db.engine.sync_engine, "before_cursor_execute", listener)
    assert {response.status_code for response in responses} == {200}
    assert len({response.json()["text"] for response in responses}) == 1
    writes = [s for s in statements if s.lstrip().split(" ", 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}]
    assert writes == []
    assert await counts() == before
    assert await _rows(app) == greetings_before


# ------------------------------------------------------------------ the pool and its weekly refresh

SUBJECTS = "maths physics chemistry biology history geography civics economics english hindi science algebra"
FRESH = [f"Shall we study {subject} today?" for subject in SUBJECTS.split()]
NEXT_MONDAY = MONDAY + timedelta(weeks=1)
# Wednesday noon IST in the launch week, and in the week after it.
THIS_WEEK_NOON = datetime(2026, 9, 30, 6, 30, tzinfo=UTC)
NEXT_WEEK_NOON = datetime(2026, 10, 7, 6, 30, tzinfo=UTC)


async def _pool(client, app, headers, moment: datetime) -> dict:
    _at(app, moment)
    response = await client.get("/v1/greetings", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _refresh_done(app) -> None:
    task = app.state.greeting_refresh.task
    if task is not None:
        await asyncio.wait_for(task, 20)


def test_usable_lines_keep_only_plain_short_study_lines():
    reply = "\n".join(
        [
            "Sure! Here are twelve greetings:",
            "1. Ready to learn something new?",
            '- "What\'s puzzling you today?"',
            "• Let’s solve this together.",
            "2) Ready to learn something new?",  # a duplicate
            "Hi!",  # too short
            "Ready for your next doubt? 🎉",  # emoji
            "<b>Bring me your toughest doubt.</b>",  # markup
            "Visit https://example.com for help.",  # a link
            "This greeting is much too long to fit above a chat box nicely today.",
            "Which chapter are we studying today",  # no end punctuation
            "",
        ]
    )
    assert usable_lines(reply) == [
        "Ready to learn something new?",
        "What's puzzling you today?",
        "Let's solve this together.",
    ]
    assert len(usable_lines("\n".join(FRESH * 3 + [f"Extra line number {n} here." for n in range(20)]))) == 12


async def test_the_pool_is_this_weeks_live_greetings_for_everyone(client, app):
    await _insert(
        app,
        [
            *live(12),
            Greeting(0, "Retired already.", MONDAY - timedelta(weeks=3), MONDAY),
            Greeting(0, "Not live yet.", NEXT_MONDAY, None),
        ],
    )
    alice = (await register(client, app))["headers"]
    bob = (await register(client, app))["headers"]
    expected = {"weekOf": "2026-09-28", "items": [f"Greeting {n}" for n in range(1, 13)]}
    assert await _pool(client, app, alice, THIS_WEEK_NOON) == expected
    assert await _pool(client, app, bob, THIS_WEEK_NOON) == expected
    assert app.state.greeting_refresh.task is None  # written this week: nothing to refresh
    assert (await client.get("/v1/greetings")).status_code == 401


async def test_a_new_week_answers_at_once_and_one_llm_refresh_replaces_the_pool(client, app, fake_llm, caplog):
    await _insert(app, live(12))
    shown_last_week = pick(await _rows(app), MONDAY).text
    fake_llm.reply = lambda messages: "\n".join(FRESH)
    fake_llm.token_delay_s = 0.02  # the model is slow; the request must not wait for it
    headers = (await register(client, app))["headers"]

    caplog.set_level(logging.INFO, logger="app.greetings.refresh")
    started = asyncio.get_running_loop().time()
    responses = await asyncio.gather(*(_pool(client, app, headers, NEXT_WEEK_NOON) for _ in range(5)))
    assert asyncio.get_running_loop().time() - started < 1.0
    assert all(r == {"weekOf": "2026-10-05", "items": [f"Greeting {n}" for n in range(1, 13)]} for r in responses)

    await _refresh_done(app)
    assert len(fake_llm.calls) == 1  # five requests, one refresh
    assert (await _pool(client, app, headers, NEXT_WEEK_NOON))["items"] == FRESH
    rows = await _rows(app)
    assert {row.text for row in rows if row.retired_from == NEXT_MONDAY} == {f"Greeting {n}" for n in range(1, 13)}
    assert {row.text for row in rows if row.active_from == NEXT_MONDAY and row.retired_from is None} == set(FRESH)
    assert pick(rows, MONDAY).text == shown_last_week  # past weeks replay unchanged
    ok = [r for r in caplog.records if r.getMessage() == "greeting refresh ok"]
    assert [(r.count, r.week_of) for r in ok] == [(12, "2026-10-05")]
    assert "Shall we study" not in caplog.text  # counts and reasons only

    # Written this week now: later requests do not call the model again.
    await _pool(client, app, headers, NEXT_WEEK_NOON + timedelta(days=2))
    await _refresh_done(app)
    assert len(fake_llm.calls) == 1


async def test_the_week_turns_at_monday_midnight_in_india(client, app, fake_llm):
    await _insert(app, live(12))
    fake_llm.reply = lambda messages: "\n".join(FRESH)
    headers = (await register(client, app))["headers"]
    monday_start = datetime(2026, 10, 4, 18, 30, tzinfo=UTC)  # Monday 2026-10-05 00:00 IST
    assert (await _pool(client, app, headers, monday_start - timedelta(minutes=1)))["weekOf"] == "2026-09-28"
    assert app.state.greeting_refresh.task is None
    assert (await _pool(client, app, headers, monday_start))["weekOf"] == "2026-10-05"
    await _refresh_done(app)
    assert (await _pool(client, app, headers, monday_start))["items"] == FRESH


async def test_concurrent_refreshes_across_processes_run_once(app, fake_llm):
    await _insert(app, live(12))
    fake_llm.reply = lambda messages: "\n".join(FRESH)
    fake_llm.token_delay_s = 0.01
    outcomes = await asyncio.gather(*(greeting_refresh.refresh(app.state.db, fake_llm, NEXT_MONDAY) for _ in range(3)))
    assert sorted(outcomes) == ["ok", "skipped", "skipped"]
    assert len(fake_llm.calls) == 1
    assert await greeting_refresh.refresh(app.state.db, fake_llm, NEXT_MONDAY) == "skipped"  # fresh now


@pytest.mark.parametrize("failure", ["down", "garbage", "too_few", "slow"])
async def test_a_failed_refresh_keeps_the_pool_and_retries_at_most_hourly(
    client, app, fake_llm, caplog, monkeypatch, failure
):
    await _insert(app, live(12))
    rows_before = await _rows(app)
    if failure == "down":
        fake_llm.fail_before_first = LLMUnavailable("upstream 503")
    elif failure == "garbage":
        fake_llm.reply = lambda messages: "Sure!\n🎉🎉\n<script>x</script>\nhttps://example.com/a."
    elif failure == "too_few":
        fake_llm.reply = lambda messages: "\n".join(FRESH[:9])
    else:
        monkeypatch.setattr(greeting_refresh, "TIMEOUT_S", 0.2)
        fake_llm.reply = lambda messages: "\n".join(FRESH)
        fake_llm.token_delay_s = 0.1
    headers = (await register(client, app))["headers"]
    caplog.set_level(logging.INFO, logger="app.greetings.refresh")

    old = {"weekOf": "2026-10-05", "items": [f"Greeting {n}" for n in range(1, 13)]}
    assert await _pool(client, app, headers, NEXT_WEEK_NOON) == old
    await _refresh_done(app)
    assert await _pool(client, app, headers, NEXT_WEEK_NOON + timedelta(minutes=30)) == old
    await _refresh_done(app)
    assert len(fake_llm.calls) == 1  # not retried within the hour
    assert await _rows(app) == rows_before
    failed = [r for r in caplog.records if r.getMessage() == "greeting refresh failed"]
    assert len(failed) == 1 and failed[0].reason == ("unusable_output" if failure in {"garbage", "too_few"} else "llm")

    await _pool(client, app, headers, NEXT_WEEK_NOON + timedelta(minutes=61))
    await _refresh_done(app)
    assert len(fake_llm.calls) == 2  # retried after an hour


async def test_a_retired_greeting_is_never_revived_by_a_refresh(app, fake_llm):
    await _insert(app, [*live(12), Greeting(0, FRESH[0], MONDAY - timedelta(weeks=4), MONDAY)])
    fake_llm.reply = lambda messages: "\n".join(FRESH)
    assert await greeting_refresh.refresh(app.state.db, fake_llm, NEXT_MONDAY) == "ok"
    rows = {row.text: row for row in await _rows(app)}
    assert (rows[FRESH[0]].active_from, rows[FRESH[0]].retired_from) == (MONDAY - timedelta(weeks=4), MONDAY)
    assert {text for text, row in rows.items() if row.live_on(NEXT_MONDAY)} == set(FRESH[1:])


async def test_no_live_greeting_is_an_empty_pool_logged_not_an_error(client, app, caplog):
    headers = (await register(client, app))["headers"]
    with caplog.at_level(logging.WARNING, logger="app.greetings.router"):
        assert await _pool(client, app, headers, THIS_WEEK_NOON) == {"weekOf": "2026-09-28", "items": []}
    assert "no active study greeting" in caplog.text
    await _refresh_done(app)  # the fake model's reply is unusable: still empty, still 200
    assert (await _pool(client, app, headers, THIS_WEEK_NOON))["items"] == []
