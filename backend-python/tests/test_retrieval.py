"""
End-to-end retrieval quality. No server and no API key needed — this runs the
real `KnowledgeRetriever` against the real vector store.

    python tests/test_retrieval.py

This is the suite that guards answer relevance. Everything downstream (prompt,
model, phrasing) is wasted if the wrong note reaches it, and the failure is
invisible: the prompt labels whatever arrives as trusted knowledge, so a wrong
note produces a confident, well-written, wrong answer.

Measured per script, because the three fail differently and an aggregate number
hides it — the old embedder scored 0.96 on English and 0.52 on Hinglish, and
Hinglish is what users actually type.
"""

from __future__ import annotations

import asyncio
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.retrieval.base import RetrievalContext  # noqa: E402
from src.retrieval.knowledge import KnowledgeRetriever  # noqa: E402
from tests.retrieval_cases import DEVANAGARI, ENGLISH, HINGLISH, NEGATIVES  # noqa: E402

retriever = KnowledgeRetriever()
failures: list[str] = []
total = 0


def sources_for(query: str) -> list[str]:
    result = asyncio.run(retriever.retrieve(RetrievalContext(query=query)))
    return [c.source.replace("knowledge:", "") for c in result.chunks]


def check_positive(group: str, query: str, want: str) -> None:
    global total
    total += 1
    got = sources_for(query)
    if want in got:
        print(f"PASS  [{group}] {query} -> {want}")
        return
    failures.append(f"[{group}] {query!r} wanted {want}, got {got or 'EMPTY'}")
    print(f"FAIL  [{group}] {query} -> wanted {want}, got {got or 'EMPTY'}")


def check_negative(query: str) -> None:
    global total
    total += 1
    got = sources_for(query)
    if not got:
        print(f"PASS  [negative] {query} -> empty")
        return
    failures.append(f"[negative] {query!r} should retrieve nothing, got {got}")
    print(f"FAIL  [negative] {query} -> should be empty, got {got}")


for group, cases in (("devanagari", DEVANAGARI), ("hinglish", HINGLISH), ("english", ENGLISH)):
    for query, want in cases:
        check_positive(group, query, want)

# A retriever that never returns empty cannot be trusted on the questions it
# does answer, so these count exactly as much as the positives.
for query in NEGATIVES:
    check_negative(query)

print(f"\n===== retrieval: {total - len(failures)}/{total} passed =====")
if failures:
    print("\nFailing:")
    for line in failures:
        print(f"  - {line}")
sys.exit(1 if failures else 0)
