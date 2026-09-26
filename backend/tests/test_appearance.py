"""Appearance: one versioned resource, the same on every device."""

import asyncio

from app.notifications.router import delivery_for
from tests.conftest import make_settings, register


async def test_appearance_starts_at_the_defaults(client, app):
    headers = (await register(client, app))["headers"]
    assert (await client.get("/v1/me/appearance", headers=headers)).json() == {
        "version": 0,
        "theme": "system",
        "fontSize": "medium",
        "highContrast": False,
        "reduceMotion": False,
        "readingComfort": False,
        "showStreak": True,
        "updatedAt": None,
    }


async def test_appearance_is_versioned_and_resettable(client, app):
    headers = (await register(client, app))["headers"]
    first = await client.patch(
        "/v1/me/appearance",
        json={"version": 0, "set": {"theme": "dark", "fontSize": "x_large", "highContrast": True}},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert (first.json()["theme"], first.json()["fontSize"], first.json()["version"]) == ("dark", "x_large", 1)
    reset = await client.patch("/v1/me/appearance", json={"version": 1, "reset": ["fontSize"]}, headers=headers)
    assert reset.json()["fontSize"] == "medium" and reset.json()["theme"] == "dark"
    stale = await client.patch("/v1/me/appearance", json={"version": 1, "set": {"theme": "light"}}, headers=headers)
    assert stale.status_code == 409 and stale.json()["error"]["current"]["theme"] == "dark"
    for bad in ({"theme": "sepia"}, {"fontSize": "huge"}, {"theme": None}, {"colour": "red"}):
        response = await client.patch("/v1/me/appearance", json={"version": 2, "set": bad}, headers=headers)
        assert response.status_code == 422, bad


async def test_two_devices_cannot_both_win_from_one_version(client, app):
    headers = (await register(client, app))["headers"]
    responses = await asyncio.gather(
        *(
            client.patch("/v1/me/appearance", json={"version": 0, "set": {"theme": theme}}, headers=headers)
            for theme in ("dark", "light")
        )
    )
    assert sorted(r.status_code for r in responses) == [200, 409]


async def test_appearance_is_per_user(client, app):
    alice = await register(client, app)
    bob = await register(client, app)
    await client.patch("/v1/me/appearance", json={"version": 0, "set": {"theme": "dark"}}, headers=alice["headers"])
    assert (await client.get("/v1/me/appearance", headers=bob["headers"])).json()["theme"] == "system"


def test_notification_delivery_follows_the_rollout():
    class User:
        id = "11111111-1111-4111-8111-111111111111"
        email = "Asha@Example.com"

    on = {"jobs_enabled": True, "public_app_url": "https://padhai.example"}
    assert delivery_for(make_settings(), User) == "paused"  # the worker is off
    assert delivery_for(make_settings(**on, notifications_mode="dry_run"), User) == "paused"
    assert delivery_for(make_settings(**on, notifications_mode="on"), User) == "active"
    assert delivery_for(make_settings(jobs_enabled=True, notifications_mode="on"), User) == "paused"  # no URL
    listed = make_settings(**on, notifications_mode="allowlist", notifications_allowlist="asha@example.com")
    assert delivery_for(listed, User) == "active"
    other = make_settings(**on, notifications_mode="allowlist", notifications_allowlist="someone@example.com")
    assert delivery_for(other, User) == "paused"
