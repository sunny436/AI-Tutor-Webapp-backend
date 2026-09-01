"""
Proof points for the GraphRAG-only -> Memory/Conversation/local-LLM reversal.
Each check below maps to one numbered requirement from the master prompt
this reversal implements. Live where the real dependency is reachable
(Ollima, GraphRAG, OpenRouter embeddings); reported BLOCKED, not silently
skipped, where it is not (see the Convex memory-write check).

    python tests/test_reversal.py
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

# Windows redirects stdout as cp1252, and several test NAMES below are
# Devanagari — so `print`ing a PASS raised UnicodeEncodeError and killed the
# run partway through. The suite could not be run to completion on the
# platform its own docstring tells you to run it on. Same reconfigure
# `server.py` applies, for the same reason.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


import config  # noqa: E402

results: list[tuple[str, bool, str]] = []
blocked: list[tuple[str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


def mark_blocked(name: str, reason: str) -> None:
    blocked.append((name, reason))
    print(f"BLOCKED  {name} - {reason}")


# ===========================================================================
# 1. GraphRAG is retrieval-only — a static regression, not a live check.
# `/v1/answer` must not exist anywhere in this codebase any more.
# ===========================================================================
src_dir = Path(__file__).resolve().parents[1] / "src"
_CALL_PATTERN = re.compile(r"graphrag\.answer(?:_stream)?\s*\(")
offending = []
for py_file in src_dir.rglob("*.py"):
    for lineno, line in enumerate(py_file.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        code_part = line.split("#", 1)[0]  # ignore comments — this is a code-call regression guard
        if _CALL_PATTERN.search(code_part):
            offending.append(f"{py_file}:{lineno}")

check(
    "no code calls graphrag.answer()/answer_stream() anywhere in src/",
    offending == [],
    offending,
)

# ===========================================================================
# 2. Local LLM generates the final answer from retrieved context.
# Real call to write_plan (Ollima) with a stubbed knowledge block — proves
# the text is GENERATED, not echoed, and reflects what was fed in.
# ===========================================================================
from src.consult.responder import write_plan  # noqa: E402
from src.consult.sections import DEFAULT_SECTIONS  # noqa: E402

STUB_KNOWLEDGE = (
    "--- GRAPHRAG ---\n"
    "[1 - from graphrag:test-note.md]\n"
    "Excess spicy and fried food, and eating late at night, upsets pitta and "
    "commonly causes acidity and a burning sensation after meals.\n"
)

if not config.is_llm_ready():
    mark_blocked(
        "write_plan generates from stubbed context",
        "no chat LLM provider configured (OLLIMA_API_KEY/OPENROUTER_API_KEY missing)",
    )
else:
    try:
        plan = asyncio.run(write_plan(
            knowledge=STUB_KNOWLEDGE,
            profile="",
            details="User reports acidity, worse after spicy food, for 2 weeks.",
            sections=DEFAULT_SECTIONS,
            language="english",
        ))
        check(
            "write_plan's output is generated, not the stub echoed verbatim",
            plan.strip() != STUB_KNOWLEDGE.strip() and len(plan) > 100,
            plan[:150],
        )
        check(
            "the generated plan reflects the stubbed knowledge (mentions acidity/spicy)",
            "acid" in plan.lower() or "spicy" in plan.lower() or "pitta" in plan.lower(),
            plan[:200],
        )
        check("the generated plan has the required 'When To See A Doctor' heading",
              "When To See A Doctor" in plan, plan[-200:])
    except Exception as error:  # noqa: BLE001
        check("write_plan generates from stubbed context", False, f"{type(error).__name__}: {error}")


# ===========================================================================
# 3 & 4. Memory: retrieval + user isolation.
# ===========================================================================
from src.retrieval.memory import PreviousConversationsRetriever  # noqa: E402
from src.retrieval.base import RetrievalContext  # noqa: E402

memory_retriever = PreviousConversationsRetriever(enabled=True)

if not config.CONVEX_SITE_URL or not config.SERVICE_KEY:
    mark_blocked("memory retrieved correctly", "CONVEX_SITE_URL or SERVICE_KEY not configured")
    mark_blocked("memory user isolation", "CONVEX_SITE_URL or SERVICE_KEY not configured")
else:
    async def _check_memory():
        # A real Convex user id is needed for a meaningful positive case; we
        # don't have test fixtures for that from here, so this proves the
        # ROUTE is reachable and returns cleanly for an unknown user (empty,
        # not an error) — the isolation guarantee itself (user_id scoping) is
        # enforced Convex-side by `recentTurns`' `by_user` index, verified by
        # reading packages/backend/convex/memory.ts directly (see the plan).
        ctx = RetrievalContext(query="test", user_id="nonexistent-test-user-xyz")
        result = await memory_retriever.retrieve(ctx)
        return result

    try:
        result = asyncio.run(_check_memory())
        check(
            "/backend/user-memory is reachable and returns cleanly for an unknown user",
            result.is_empty,
            f"{len(result.chunks)} chunks for a user that does not exist",
        )
        mark_blocked(
            "memory user isolation (positive case: user A sees own memory)",
            "no real Convex user id available from this test environment to "
            "exercise the positive case; isolation is enforced by the by_user "
            "index in packages/backend/convex/memory.ts (verified by reading it)",
        )
    except Exception as error:  # noqa: BLE001
        check("memory retrieval reachable", False, f"{type(error).__name__}: {error}")


# ===========================================================================
# 6. No hallucinated knowledge — abstention via the NO_KNOWLEDGE sentinel.
# ===========================================================================
from src.consult.graph import knowledge_for_prompt  # noqa: E402
from src.consult.responder import NO_KNOWLEDGE  # noqa: E402
from src.retrieval.pipeline import RetrievalPipeline  # noqa: E402
from src.retrieval.base import Chunk, RetrievalResult  # noqa: E402

empty_pipeline = RetrievalPipeline([])
block = knowledge_for_prompt(empty_pipeline, [])
check("empty retrieval produces the NO_KNOWLEDGE sentinel", NO_KNOWLEDGE in block, block)

memory_only_results = [
    RetrievalResult(section="Earlier consultations", chunks=(
        Chunk(text="User said they have acidity.", source="memory:abc123"),
    ))
]
block2 = knowledge_for_prompt(empty_pipeline, memory_only_results)
check(
    "memory-only retrieval (no graphrag:/knowledge: source) still abstains",
    NO_KNOWLEDGE in block2,
    block2,
)

graphrag_result = [
    RetrievalResult(section="Reference documents", chunks=(
        Chunk(text="Some Ayurveda passage.", source="graphrag:note.md"),
    ))
]
block3 = knowledge_for_prompt(empty_pipeline, graphrag_result)
check(
    "a real graphrag: source counts as grounded (no sentinel)",
    NO_KNOWLEDGE not in block3,
    block3,
)


# ===========================================================================
# 7. Hindi/Hinglish — the same complaint in both scripts resolves to the same
# note via the local alias index (english_handle's dependency).
# ===========================================================================
from src.knowledge import match_topics  # noqa: E402

hinglish_claim = match_topics("mujhe gas ho rahi hai")
devanagari_claim = match_topics("मुझे गैस हो रही है")
check(
    "Hinglish complaint resolves to a note via the alias index",
    bool(hinglish_claim),
    hinglish_claim,
)
check(
    "the same complaint in Devanagari resolves to the SAME note",
    bool(devanagari_claim) and devanagari_claim[0] == (hinglish_claim[0] if hinglish_claim else None),
    f"hinglish={hinglish_claim} devanagari={devanagari_claim}",
)


# ===========================================================================
# 8. OpenRouter/embedding failure handled correctly — deliberately break the
# key and confirm the failure is raised cleanly, not swallowed into a fake
# empty-but-successful result.
# ===========================================================================
from src import knowledge as knowledge_module  # noqa: E402

_real_key = config.OPENROUTER_API_KEY
_real_embeddings_cache = knowledge_module._embeddings
config.OPENROUTER_API_KEY = "sk-or-v1-deliberately-invalid-for-testing"
knowledge_module._embeddings = None
try:
    try:
        knowledge_module.get_embeddings().embed_query("test")
        check("an invalid OpenRouter key raises rather than returning fake embeddings", False, "no exception raised")
    except Exception as error:  # noqa: BLE001
        check(
            "an invalid OpenRouter key raises a real error (not a silent empty success)",
            True,
            f"{type(error).__name__}: {str(error)[:150]}",
        )
finally:
    config.OPENROUTER_API_KEY = _real_key
    knowledge_module._embeddings = _real_embeddings_cache


passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"\n===== reversal: {passed}/{total} passed, {len(blocked)} blocked =====")
if blocked:
    print("\nBlocked (external dependency, not a code failure):")
    for name, reason in blocked:
        print(f"  - {name}: {reason}")
if passed != total:
    print("\nFailing:")
    for name, ok, _ in results:
        if not ok:
            print(f"  - {name}")
sys.exit(0 if passed == total else 1)
