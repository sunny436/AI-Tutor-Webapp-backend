"""
Conversation identity, and the memory bug it fixes.

    python tests/test_conversation_id.py

No LLM is involved. This is plumbing: does the id the browser sends actually
reach the one place that needs it?

THE BUG THIS CLOSES
`retrieval/memory.py` fetches this user's EARLIER consultations and has always
forwarded `ctx.session_id` to Convex as `excludeSessionId`. Nothing ever filled
it in. So memory also returned the turns of the chat currently on screen, and
the model was handed its own transcript a second time under the heading "Earlier
consultations with this user" — which reads as the user having said everything
twice.

Every piece already existed: the frontend has `sessionId`, Convex keys messages
on it, `RetrievalContext.session_id` exists, and `memory.retrieve` accepts it.
The request body was the only missing link, so these tests follow it end to end.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from src.bots import get_bot  # noqa: E402
from src.consult import graph  # noqa: E402
from src.consult.schema import ConsultContext  # noqa: E402
from src.retrieval.base import RetrievalContext, RetrievalResult  # noqa: E402
from src.retrieval.memory import PreviousConversationsRetriever  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# --- 1. the id reaches RetrievalContext -------------------------------------
print("\nplumbing: request -> RetrievalContext")

captured: list[RetrievalContext] = []


class _CapturingPipeline:
    """Stands in for the real pipeline and records what it was handed."""

    async def run(self, ctx: RetrievalContext):
        captured.append(ctx)
        return []

    def to_prompt_block(self, _results) -> str:
        return ""

    def to_sources(self, _results) -> list:
        return []


def retrieve_with(conversation_id, principal):
    captured.clear()
    real = graph.get_pipeline
    graph.get_pipeline = lambda: _CapturingPipeline()
    try:
        asyncio.run(
            graph._retrieve(
                ConsultContext(problem="acidity"),
                principal,
                get_bot(None),
                conversation_id,
            )
        )
    finally:
        graph.get_pipeline = real
    return captured[0]


ctx = retrieve_with("conv-abc", {"user_id": "u1"})
check("conversation_id reaches RetrievalContext.session_id", ctx.session_id == "conv-abc", str(ctx.session_id))

ctx = retrieve_with(None, {"user_id": "u1", "sessionId": "from-principal"})
check(
    "falls back to principal.sessionId when no conversation_id is sent",
    ctx.session_id == "from-principal",
    str(ctx.session_id),
)

ctx = retrieve_with("conv-wins", {"user_id": "u1", "sessionId": "from-principal"})
check("an explicit conversation_id outranks principal", ctx.session_id == "conv-wins", str(ctx.session_id))

ctx = retrieve_with(None, {"user_id": "u1"})
check("absent everywhere stays None (today's behaviour)", ctx.session_id is None, str(ctx.session_id))

check("the bot is still threaded alongside it", ctx.bot.knowledge_collection == "ayurveda_yoga")


# --- 2. the retriever forwards it to Convex ---------------------------------
print("\nmemory retriever -> Convex excludeSessionId")

sent: list[dict] = []


class _FakeResponse:
    @staticmethod
    def raise_for_status() -> None:
        return None

    @staticmethod
    def json() -> dict:
        return {"turns": []}


def _fake_post(url, headers=None, json=None, timeout=None):  # noqa: A002
    sent.append(json or {})
    return _FakeResponse()


import httpx  # noqa: E402

real_post = httpx.post
real_site, real_key = config.CONVEX_SITE_URL, config.SERVICE_KEY
try:
    httpx.post = _fake_post
    # `_fetch` returns early unless both are configured, so give it values that
    # are never actually dialled — the transport is stubbed above.
    config.CONVEX_SITE_URL = "https://convex.invalid"
    config.SERVICE_KEY = "test-key"

    asyncio.run(
        PreviousConversationsRetriever(enabled=True).retrieve(
            RetrievalContext(query="acidity", user_id="u1", session_id="conv-abc")
        )
    )
    check(
        "THE FIX: the current conversation is excluded from its own memory",
        sent and sent[0].get("excludeSessionId") == "conv-abc",
        str(sent[0] if sent else "nothing sent"),
    )

    sent.clear()
    asyncio.run(
        PreviousConversationsRetriever(enabled=True).retrieve(
            RetrievalContext(query="acidity", user_id="u1")
        )
    )
    check(
        "with no id it degrades to today's behaviour, not an error",
        sent and sent[0].get("excludeSessionId") == "",
        str(sent[0] if sent else "nothing sent"),
    )
finally:
    httpx.post = real_post
    config.CONVEX_SITE_URL, config.SERVICE_KEY = real_site, real_key


# --- 3. the HTTP edge passes it on ------------------------------------------
print("\nHTTP edge")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

seen: list[dict] = []


async def _fake_turn(**kwargs):
    seen.append(kwargs)

    class _Result:
        @staticmethod
        def model_dump() -> dict:
            return {"kind": "chat", "condition": "", "message": "", "answer": "", "context": {}, "sources": []}

    return _Result()


real_turn = server.run_consult_turn
real_service_key = config.SERVICE_KEY
try:
    server.run_consult_turn = _fake_turn
    config.SERVICE_KEY = "p2-test-service-key"
    client = TestClient(server.app)
    headers = {"X-Service-Key": config.SERVICE_KEY}

    client.post("/consult", json={"problem": "hi", "conversationId": "conv-http"}, headers=headers)
    check(
        "POST /consult forwards conversationId to run_turn",
        seen and seen[0].get("conversation_id") == "conv-http",
        str(seen[0].get("conversation_id") if seen else "not called"),
    )

    seen.clear()
    client.post("/consult", json={"problem": "hi"}, headers=headers)
    check(
        "omitting it is still a valid request (None, not an error)",
        seen and seen[0].get("conversation_id") is None,
        str(seen[0].get("conversation_id") if seen else "not called"),
    )
finally:
    server.run_consult_turn = real_turn
    config.SERVICE_KEY = real_service_key


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== conversation id: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}: {detail}")
sys.exit(0 if passed == len(results) else 1)
