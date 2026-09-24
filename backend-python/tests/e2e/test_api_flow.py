"""End-to-end over real HTTP: a uvicorn server on a local port, real SSE streaming, real PostgreSQL.

The acceptance flow, API-level (the browser UI lives in the separate frontend repo):
 1 sign up + verify + sign in   2 new chat          3 send a message
 4 streamed reply               5 "refresh" (new session, reload)
 6 conversation still exists    7 open another conversation
 8 return to the first          9 rename it         10 delete it
"""

import asyncio
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from app.auth.emails import MemoryEmailSender
from app.llm.fake import FakeProvider
from app.main import create_app
from tests.conftest import PASSWORD, last_code, make_settings

pytestmark = pytest.mark.e2e


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server():
    app = create_app(make_settings(), llm=FakeProvider(token_delay_s=0.02), email_sender=MemoryEmailSender())
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    instance = uvicorn.Server(config)
    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not instance.started and time.time() < deadline:
        time.sleep(0.05)
    assert instance.started, "server did not start"
    yield app, f"http://127.0.0.1:{port}"
    instance.should_exit = True
    thread.join(timeout=10)


async def _stream(http, headers, body, url="/v1/chat/stream"):
    """Read SSE incrementally, as a browser would. Returns (events, first_token_s, done_s)."""
    events, first_token_at, done_at, started = [], None, None, time.monotonic()
    async with http.stream("POST", url, json=body, headers=headers) as response:
        assert response.status_code == 200, await response.aread()
        buffer = ""
        async for chunk in response.aiter_text():
            buffer += chunk
            while "\n\n" in buffer:
                frame, buffer = buffer.split("\n\n", 1)
                lines = dict(
                    line.split(": ", 1) for line in frame.splitlines() if ": " in line and not line.startswith(":")
                )
                if "event" in lines:
                    events.append((lines["event"], json.loads(lines["data"])))
                    if lines["event"] == "token" and first_token_at is None:
                        first_token_at = time.monotonic() - started
                    if lines["event"] in ("done", "error"):
                        done_at = time.monotonic() - started
    return events, first_token_at, done_at


async def test_full_chat_flow_over_http(server):
    app, base = server
    email = "e2e-user@example.com"
    async with httpx.AsyncClient(base_url=base, timeout=30) as http:
        # 1. sign up, verify, sign in
        assert (await http.post("/v1/auth/signup", json={"email": email, "password": PASSWORD})).status_code == 202
        verified = await http.post("/v1/auth/verify-email", json={"email": email, "code": last_code(app, email)})
        assert verified.status_code == 200
        login = await http.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
        headers = {"Authorization": f"Bearer {login.json()['session']['token']}"}

        # 2-4. new chat, send, receive a progressively streamed reply
        events, first_token, done_at = await _stream(http, headers, {"message": "What is 2 + 2?"})
        kinds = [k for k, _ in events]
        assert kinds[0] == "meta" and kinds[-1] == "done" and kinds.count("token") > 3
        # Progressive streaming: the first token reaches the client clearly before the end
        # (each fake token takes 20 ms). Timing-independent of machine load.
        assert first_token is not None and done_at is not None and first_token < done_at
        first_id = events[0][1]["conversationId"]
        assert events[-1][1]["message"]["content"] == "You said: What is 2 + 2?"

        # 5-6. "refresh": a brand-new session reloads everything from the server
        relogin = await http.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
        headers = {"Authorization": f"Bearer {relogin.json()['session']['token']}"}
        listed = (await http.get("/v1/conversations", headers=headers)).json()["items"]
        assert [c["id"] for c in listed] == [first_id]
        history = (await http.get(f"/v1/conversations/{first_id}/messages", headers=headers)).json()["items"]
        assert [m["role"] for m in history] == ["user", "assistant"]

        # 7. open another conversation
        events, _, _ = await _stream(http, headers, {"message": "A different topic"})
        second_id = events[0][1]["conversationId"]
        assert second_id != first_id
        listed = (await http.get("/v1/conversations", headers=headers)).json()["items"]
        assert [c["id"] for c in listed] == [second_id, first_id]

        # 8. return to the first one and continue it
        events, _, _ = await _stream(http, headers, {"conversationId": first_id, "message": "And 3 + 3?"})
        assert events[-1][0] == "done"
        history = (await http.get(f"/v1/conversations/{first_id}/messages", headers=headers)).json()["items"]
        assert [m["content"] for m in history if m["role"] == "user"] == ["What is 2 + 2?", "And 3 + 3?"]

        # 9. rename
        renamed = await http.patch(f"/v1/conversations/{first_id}", json={"title": "Arithmetic"}, headers=headers)
        assert renamed.json()["title"] == "Arithmetic"

        # 10. delete
        assert (await http.delete(f"/v1/conversations/{first_id}", headers=headers)).status_code == 204
        assert (await http.get(f"/v1/conversations/{first_id}", headers=headers)).status_code == 404
        assert [c["id"] for c in (await http.get("/v1/conversations", headers=headers)).json()["items"]] == [second_id]


async def test_client_disconnect_stops_generation_and_persists_partial(server):
    app, base = server
    email = "e2e-disconnect@example.com"
    async with httpx.AsyncClient(base_url=base, timeout=30) as http:
        await http.post("/v1/auth/signup", json={"email": email, "password": PASSWORD})
        verified = await http.post("/v1/auth/verify-email", json={"email": email, "code": last_code(app, email)})
        headers = {"Authorization": f"Bearer {verified.json()['session']['token']}"}
        app.state.llm.reply = lambda m: " ".join(f"w{i}" for i in range(400))
        conversation_id = None
        async with http.stream("POST", "/v1/chat/stream", json={"message": "long"}, headers=headers) as response:
            async for chunk in response.aiter_text():
                if conversation_id is None and '"conversationId"' in chunk:
                    conversation_id = json.loads(chunk.split("data: ", 1)[1].split("\n", 1)[0])["conversationId"]
                if chunk.count("event: token") and conversation_id:
                    break  # the user closes the tab mid-answer
        # the server notices, stops, and stores what was generated as `cancelled`
        for _ in range(100):
            items = (await http.get(f"/v1/conversations/{conversation_id}/messages", headers=headers)).json()["items"]
            if items[-1]["status"] != "streaming":
                break
            await asyncio.sleep(0.1)
        reply = items[-1]
        assert reply["status"] == "cancelled"
        assert 0 < len(reply["content"].split()) < 400
