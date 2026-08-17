"""
Actively trying to break it, plus the GraphRAG proof chain.

    python tests/test_failure_matrix.py

TWO HALVES, AND THE SECOND ONE IS THE HONEST ONE.

PART A — the failure matrix. Every input a real user or a broken dependency can
produce. The bar is not "returns 200"; it is that a failure NEVER produces a
fabricated answer. Empty retrieval must yield an honest "nothing covers this",
because the prompt labels whatever comes back as trusted knowledge and the model
will dutifully build an answer around it.

PART B — GraphRAG. ⚠ EVERY GRAPHRAG RESULT HERE IS PRODUCED BY A LOCAL STUB.

    THE REAL SERVICE HAS NEVER BEEN CONTACTED.

Two blockers, both outside this repo:
  1. `graphrag.internal` does not resolve from this machine, and the vendor doc
     forbids the raw IP because the certificate is issued for the name. Fixing it
     needs a DNS record or an Administrator hosts edit.
  2. The /v1/search RESPONSE BODY IS NOT DOCUMENTED. The brief shows the request
     and a response only for upload.

So what Part B proves is every hop EXCEPT the network call: that a passage
entering the retriever reaches the Context Builder, lands in the prompt under its
own heading, becomes a citation, and that a dead service degrades instead of
failing the consultation. It does NOT prove the real service returns anything of
this shape. Saying otherwise would be fabricating a live result.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from src import safety  # noqa: E402
from src.bots import BotConfig, get_bot  # noqa: E402
from src.consult import gathering, graph  # noqa: E402
from src.consult import state as ctx_state  # noqa: E402
from src.retrieval.base import Chunk, RetrievalContext, RetrievalResult  # noqa: E402
from src.retrieval.graphrag import GraphRagRetriever  # noqa: E402
from src.retrieval.knowledge import KnowledgeRetriever  # noqa: E402
from src.retrieval.pipeline import RetrievalPipeline  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def run(coro):
    return asyncio.run(coro)


# ===========================================================================
# PART A — the failure matrix
# ===========================================================================
print("\nA1. malformed and hostile input")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

real_key = config.SERVICE_KEY
config.SERVICE_KEY = "p8-test-service-key"
client = TestClient(server.app)
H = {"X-Service-Key": config.SERVICE_KEY}

r = client.post("/consult", content=b"{not json", headers={**H, "Content-Type": "application/json"})
check("malformed JSON body -> 400, not a 500 stack trace", r.status_code == 400, str(r.status_code))

r = client.post("/consult", content=b"\xff\xfe\x00bad", headers={**H, "Content-Type": "application/json"})
check("non-UTF-8 body -> 400", r.status_code == 400, str(r.status_code))

r = client.post("/consult", json={"bot_id": "no-such-bot", "problem": "hi"}, headers=H)
check("unknown bot_id -> 400", r.status_code == 400, str(r.status_code))
check("...and the 400 explains which ids exist", "ayurveda" in r.text, r.text[:80])

r = client.post("/consult", json={"problem": "hi", "context": "not-an-object"}, headers=H)
check("a context of the wrong TYPE does not 500", r.status_code < 500, str(r.status_code))

r = client.post("/consult", json={"problem": "hi"})
check("no credential at all -> 401, never an answer", r.status_code == 401, str(r.status_code))

config.SERVICE_KEY = real_key


print("\nA2. empty, enormous and repeated input")

# An empty send must not start a consultation about "".
empty = run(graph.run_turn(problem="", raw_context=None, answers=None, free_text=None))
check("empty message returns quietly, starting nothing", empty.kind == "chat" and not empty.answer)
check("...and does not enter a consultation", empty.context.phase == "idle", empty.context.phase)

# Bounded state. The context blob rides on EVERY request and is persisted, so an
# unbounded field is a slow-motion outage.
huge = ConsultContextHuge = ctx_state.load_context(
    {"v": 2, "phase": "gathering", "problem": "x" * 50_000, "symptoms": ["y" * 500] * 200}
)
check("a 50k-char problem still loads", huge.phase == "gathering")
merged = ctx_state._merge_symptoms([], ["z" * 500] * 200)
check(
    "symptoms stay bounded in COUNT no matter what arrives",
    len(merged) <= 10,
    f"{len(merged)} kept",
)
check(
    "symptoms stay bounded in LENGTH, so the vector query cannot be flooded",
    all(len(s) <= 40 for s in merged),
    f"longest {max((len(s) for s in merged), default=0)}",
)

long_history = ctx_state.load_context({"v": 2, "problem": "acidity"})
for i in range(50):
    long_history = ctx_state.remember_chat(long_history, f"message {i}", f"reply {i}")
check(
    "50 turns of chat stay capped",
    len(long_history.chat_history) <= 20,
    f"{len(long_history.chat_history)} turns",
)


print("\nA3. dependencies failing")

# The LLM is unreachable: gathering must FAIL SAFE, not write a plan from nothing.
real_invoke = gathering.llm_invoke
try:
    gathering.llm_invoke = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("503 overloaded"))
    dead = run(gathering.gather(problem="acidity", language="hinglish"))
    check("LLM outage: does NOT declare itself ready to write a plan", dead.ready is False)
    check("LLM outage: still says something rather than an empty bubble", bool(dead.reply))
    check("LLM outage: raises no red flag it cannot justify", dead.red_flag is False)
finally:
    gathering.llm_invoke = real_invoke

# Retrieval returning nothing must NOT be papered over.
empty_pipeline = RetrievalPipeline([])
block = empty_pipeline.to_prompt_block(run(empty_pipeline.run(RetrievalContext(query="x"))))
check("empty retrieval produces an EMPTY prompt block, not filler", block == "", repr(block[:40]))
check("empty retrieval produces no citations", empty_pipeline.to_sources([]) == [])


class _Exploding:
    name, section, order, enabled = "boom", "Boom", 10, True

    async def retrieve(self, ctx):
        raise RuntimeError("retriever exploded")


class _Slow:
    name, section, order, enabled = "slow", "Slow", 11, True

    async def retrieve(self, ctx):
        await asyncio.sleep(30)
        return RetrievalResult(section="Slow", chunks=())


# Warm the store first, exactly as `server.py` does at startup via
# `knowledge.warm_up()`. Without it the first query pays for loading a ~1.9GB
# embedding model and opening Chroma, blows any realistic per-retriever budget,
# and the healthy retriever gets timed out alongside the broken ones — which
# tests the cold-start cost, not the isolation this is about.
from src import knowledge as knowledge_store  # noqa: E402

knowledge_store.warm_up()

mixed = RetrievalPipeline(
    [_Exploding(), _Slow(), KnowledgeRetriever(enabled=True)],
    timeout_s=config.RETRIEVAL_TIMEOUT_S,
)
got = run(mixed.run(RetrievalContext(query="gas ki problem")))
check(
    "one retriever raising does not fail the consultation",
    any(not r.is_empty for r in got),
    f"{len(got)} non-empty results",
)
check(
    "one retriever HANGING does not hold up the others",
    any("Ayurveda" in r.section for r in got),
    ", ".join(r.section for r in got) or "nothing survived",
)


print("\nA4. safety never degrades open")

for hostile in [
    "mujhe vomit me blood aa raha hai",
    "ulti me khoon aaya",
    "seene me dard ho raha hai",
    "मुझे उल्टी में खून आ रहा है",
]:
    check(f"red flag still caught: {hostile[:34]!r}", safety.is_emergency(hostile))

check(
    "a red flag buried mid-conversation is caught",
    safety.scan(
        *ctx_state.safety_fragments(
            ctx_state.remember_chat(
                ctx_state.remember_chat(ctx_state.load_context({"v": 2, "problem": "acidity"}),
                                        "kal se", "kab se?"),
                "aaj stool me blood dikha", "",
            )
        )
    ),
)
check(
    "...and an ordinary conversation is still not flagged",
    not safety.scan(
        *ctx_state.safety_fragments(
            ctx_state.remember_chat(
                ctx_state.load_context({"v": 2, "problem": "acidity"}), "spicy khana khaya", "ok"
            )
        )
    ),
)


# ===========================================================================
# PART B — GraphRAG: STUB-BASED. The real service has never been contacted.
# ===========================================================================
print("\nB. GraphRAG proof chain  ⚠ STUB, NOT THE LIVE SERVICE")

PROOF_BOT = BotConfig(
    bot_id="proof", knowledge_collection="p1-bot-isolation-probe", graphrag_project_id="proj-proof"
)

# An INVENTED response. The real schema is NOT DOCUMENTED.
STUB_RESPONSE = {
    "results": [
        {
            "text": "Classical texts describe amlapitta as aggravated pitta in the stomach.",
            "document_name": "charaka-samhita.pdf",
            "score": 0.77,
        }
    ]
}


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._p


import httpx  # noqa: E402

captured: list[dict] = []
real_post, real_k, real_b = httpx.post, config.GRAPHRAG_API_KEY, config.GRAPHRAG_BASE_URL
try:
    httpx.post = lambda url, **kw: (captured.append({"url": url, **kw}), _Resp(STUB_RESPONSE))[1]
    config.GRAPHRAG_API_KEY = "stub-key-not-a-real-credential"
    config.GRAPHRAG_BASE_URL = "https://graphrag.stub.invalid"

    pipeline = RetrievalPipeline([GraphRagRetriever(enabled=True)])
    got = run(pipeline.run(RetrievalContext(query="mujhe acidity hai", bot=PROOF_BOT)))

    check("1. a passage enters the retriever", any(not r.is_empty for r in got))

    prompt_block = pipeline.to_prompt_block(got)
    check(
        "2. it reaches the CONTEXT BUILDER under its own heading",
        "--- REFERENCE DOCUMENTS ---" in prompt_block,
        prompt_block.splitlines()[0] if prompt_block else "empty",
    )
    check(
        "3. the passage text is in the assembled prompt",
        "de Laval" not in prompt_block and "amlapitta" in prompt_block,
    )
    check(
        "4. it is attributed, so the model can be told where it came from",
        "from graphrag:charaka-samhita.pdf" in prompt_block,
    )

    sources = pipeline.to_sources(got)
    check(
        "5. it becomes a citation the UI can render",
        any(s["source"] == "graphrag:charaka-samhita.pdf" for s in sources),
        json.dumps(sources[:1]),
    )
    check(
        "6. citations carry no passage text (safe to return to the browser)",
        all("text" not in s for s in sources),
    )
    check("7. /v1/search was called, never /v1/answer", captured[0]["url"].endswith("/v1/search"))
    check("8. TLS verification was never disabled", captured[0].get("verify") is not False)
    check(
        "9. the project id came from the BOT, preserving isolation",
        captured[0]["json"]["project_id"] == "proj-proof",
    )

    # 10. the service dies mid-flight
    httpx.post = lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("refused"))
    dead = run(pipeline.run(RetrievalContext(query="acidity", bot=PROOF_BOT)))
    check("10. a dead service yields nothing rather than an error", all(r.is_empty for r in dead))
    check("11. ...and the prompt is simply built without it", pipeline.to_prompt_block(dead) == "")

    # 12. a timeout must not hold up a consultation
    def _hang(*a, **k):
        import time

        time.sleep(30)

    httpx.post = _hang
    slow_pipeline = RetrievalPipeline([GraphRagRetriever(enabled=True)], timeout_s=1.0)
    hung = run(slow_pipeline.run(RetrievalContext(query="acidity", bot=PROOF_BOT)))
    check("12. a hanging service is cut off by the pipeline timeout", all(r.is_empty for r in hung))
finally:
    httpx.post, config.GRAPHRAG_API_KEY, config.GRAPHRAG_BASE_URL = real_post, real_k, real_b

check(
    "13. and it is STILL DISABLED by default, so none of the above runs in production",
    config.GRAPHRAG_ENABLED is False,
    f"GRAPHRAG_ENABLED={config.GRAPHRAG_ENABLED}",
)


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== failure matrix: {passed}/{len(results)} passed =====")
print("⚠ PART B USED A STUB. The real GraphRAG service has NOT been contacted:")
print("  - graphrag.internal does not resolve (needs DNS or an admin hosts edit)")
print("  - the /v1/search response schema is NOT DOCUMENTED")
print("  LIVE MAPPING REMAINS UNVERIFIED.")
if passed != len(results):
    print("\nFailing:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}: {detail}")
sys.exit(0 if passed == len(results) else 1)
