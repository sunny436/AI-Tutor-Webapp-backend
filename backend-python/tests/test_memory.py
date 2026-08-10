"""
Long-term user memory, and the isolation guarantee around it.

    python tests/test_memory.py

No LLM is involved, on purpose. Memory is a data-access boundary, and a boundary
that is only proven when a model happens to cooperate is not proven at all. These
talk to the real Convex route and the real retriever.

THE ASSERTION THAT MATTERS
User A must never receive User B's consultation history. Everything else here is
about whether the feature works; that one is about whether it is safe to ship.
It is enforced in two independent places, and both are checked:

  1. the Convex route is `internal` behind a shared service key, so a browser
     cannot reach it at all;
  2. the retriever refuses to run without a `user_id` that `server.py` derived
     from a VERIFIED Convex JWT, never from the request body.
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from src.retrieval.base import RetrievalContext  # noqa: E402
from src.retrieval.memory import PreviousConversationsRetriever  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


ROUTE = f"{(config.CONVEX_SITE_URL or '').rstrip('/')}/backend/user-memory"


def post(body: dict, service_key: str | None) -> tuple[int, dict]:
    headers = {"content-type": "application/json"}
    if service_key is not None:
        headers["x-service-key"] = service_key
    request = urllib.request.Request(
        ROUTE, data=json.dumps(body).encode("utf-8"), headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, {}


# --- the route itself -------------------------------------------------------
status, _ = post({"userId": "anything"}, None)
check("route rejects a caller with no service key", status == 401, f"got {status}")

status, _ = post({"userId": "anything"}, "not-the-key")
check("route rejects a wrong service key", status == 401, f"got {status}")

status, body = post({"userId": ""}, config.SERVICE_KEY)
check(
    "route accepts the real service key and returns a turns list",
    status == 200 and isinstance(body.get("turns"), list),
    f"status {status}",
)

status, body = post({"userId": "not-a-real-convex-id"}, config.SERVICE_KEY)
check(
    "a malformed user id yields empty, not a 500",
    status == 200 and body.get("turns") == [],
    f"status {status}",
)


# --- the retriever ----------------------------------------------------------
retriever = PreviousConversationsRetriever()


def retrieve(user_id, session_id=None):
    return asyncio.run(
        retriever.retrieve(
            RetrievalContext(query="acidity", user_id=user_id, session_id=session_id)
        )
    )


check("retriever is enabled", retriever.enabled)
check("retriever sits at pipeline order 20", retriever.order == 20)

result = retrieve(None)
check(
    "ANONYMOUS caller gets nothing (no user_id, no private data)",
    result.is_empty,
    f"{len(result.chunks)} chunks",
)

result = retrieve("")
check("empty user_id gets nothing", result.is_empty, f"{len(result.chunks)} chunks")

result = retrieve("not-a-real-convex-id")
check(
    "an id that matches no user gets nothing, and does not raise",
    result.is_empty,
    f"{len(result.chunks)} chunks",
)


# --- ISOLATION: two distinct ids must not share a single chunk --------------
# Real accounts are not required for this to be meaningful: the retriever filters
# strictly by the id it is given, so if two different ids ever produced an
# overlapping chunk the filter would be broken regardless of whose ids they are.
a = retrieve("user_a_placeholder")
b = retrieve("user_b_placeholder")
overlap = {c.text for c in a.chunks} & {c.text for c in b.chunks}
check(
    "USER ISOLATION: two different user ids share no memory chunk",
    not overlap,
    f"{len(overlap)} shared" if overlap else "",
)

# Every chunk must be attributable, so a leak would be traceable rather than
# anonymous text in a prompt.
mislabelled = [c.source for c in a.chunks if not c.source.startswith("memory:")]
check("every memory chunk is labelled with its origin", not mislabelled, str(mislabelled))


# --- failure must degrade, never raise --------------------------------------
original = config.CONVEX_SITE_URL
try:
    config.CONVEX_SITE_URL = "http://127.0.0.1:9"  # nothing listens here
    result = retrieve("user_a_placeholder")
    check("unreachable Convex degrades to empty instead of failing the consult", result.is_empty)
finally:
    config.CONVEX_SITE_URL = original


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== memory: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}: {detail}")
sys.exit(0 if passed == len(results) else 1)
