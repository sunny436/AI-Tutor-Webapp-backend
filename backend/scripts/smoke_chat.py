"""Live smoke test of a RUNNING local API with the REAL LLM provider.

    python scripts/smoke_chat.py [--base-url http://127.0.0.1:4000]

Writes a throwaway account and a session into the database the local API uses (sign-up itself
is the web app's Better Auth), streams a reply, stops a second reply mid-stream, regenerates,
leaves feedback, renames and deletes the conversation, then deletes the account. Prints one line
per step; exits 1 on failure. Never point this at production.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import secrets
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  - ' + detail) if detail else ''}")
    if not ok:
        raise SystemExit(1)


def throwaway_session(email: str) -> str:
    """A verified account without a password and a fresh session, as Better Auth writes them, in
    the database of this checkout's settings (backend/.env). Returns the session token."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.settings import get_settings

    async def write() -> str:
        token = secrets.token_urlsafe(24)
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                user_id = await conn.scalar(
                    text("INSERT INTO users (email, email_verified) VALUES (:e, true) RETURNING id"), {"e": email}
                )
                await conn.execute(
                    text(
                        "INSERT INTO auth_sessions (user_id, token, expires_at) "
                        "VALUES (:u, :t, now() + interval '1 day')"
                    ),
                    {"u": user_id, "t": token},
                )
        finally:
            await engine.dispose()
        return token

    return asyncio.run(write())


def stream(http: httpx.Client, url: str, headers: dict, body: dict | None = None, stop_after: int | None = None):
    events, started, first_token = [], time.monotonic(), None
    with http.stream("POST", url, json=body, headers=headers) as response:
        if response.status_code != 200:
            raise SystemExit(f"{url} -> HTTP {response.status_code}: {response.read()[:300]!r}")
        buffer = ""
        for chunk in response.iter_text():
            buffer += chunk
            while "\n\n" in buffer:
                frame, buffer = buffer.split("\n\n", 1)
                name = re.search(r"^event: (.+)$", frame, re.M)
                data = re.search(r"^data: (.+)$", frame, re.M)
                if not (name and data):
                    continue
                events.append((name.group(1), json.loads(data.group(1))))
                if name.group(1) == "token" and first_token is None:
                    first_token = time.monotonic() - started
                tokens = sum(1 for kind, _ in events if kind == "token")
                if stop_after is not None and tokens >= stop_after:
                    meta = events[0][1]
                    http.post(f"/v1/messages/{meta['assistantMessageId']}/cancel", headers=headers)
                    stop_after = None
    return events, first_token


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:4000")
    args = parser.parse_args()
    email = f"smoke-{uuid.uuid4().hex[:8]}@example.com"

    with httpx.Client(base_url=args.base_url, timeout=120) as http:
        step("ready", http.get("/ready").json().get("database") is True)
        headers = {"Authorization": f"Bearer {throwaway_session(email)}"}
        step("throwaway account and session", http.get("/v1/me", headers=headers).status_code == 200)

        events, ttft = stream(http, "/v1/chat/stream", headers, {"message": "In one sentence, what is a prime number?"})
        done = events[-1]
        step(
            "streamed reply (real LLM)",
            done[0] == "done" and done[1]["message"]["status"] == "complete",
            f"{sum(1 for k, _ in events if k == 'token')} chunks, first token after {ttft:.2f}s, "
            f"model={done[1]['message'].get('metadata', {}).get('model')}"
            if done[0] == "done"
            else json.dumps(done[1]),
        )
        cid = events[0][1]["conversationId"]

        events, _ = stream(
            http,
            "/v1/chat/stream",
            headers,
            {"conversationId": cid, "message": "Write a detailed 600-word essay about the history of mathematics."},
            stop_after=5,
        )
        final = events[-1]
        step(
            "stop generation",
            final[0] == "done" and final[1]["message"]["status"] == "cancelled",
            f"kept {len(final[1]['message']['content'])} characters" if final[0] == "done" else json.dumps(final[1]),
        )

        events, _ = stream(http, f"/v1/conversations/{cid}/regenerate/stream", headers)
        step("regenerate", events[-1][0] == "done" and events[0][1]["replacesMessageId"] is not None)
        reply_id = events[-1][1]["message"]["id"]

        fb = http.put(f"/v1/messages/{reply_id}/feedback", json={"rating": "up"}, headers=headers)
        step("feedback", fb.status_code == 200)
        step(
            "rename",
            http.patch(f"/v1/conversations/{cid}", json={"title": "Smoke"}, headers=headers).status_code == 200,
        )
        listed = http.get("/v1/conversations", headers=headers).json()["items"]
        step("history persisted", [c["title"] for c in listed] == ["Smoke"])
        step("delete conversation", http.delete(f"/v1/conversations/{cid}", headers=headers).status_code == 204)
        gone = http.request("DELETE", "/v1/me", json={}, headers=headers)  # no password: a fresh session
        step("delete account", gone.status_code == 204)
    return 0


if __name__ == "__main__":
    sys.exit(main())
