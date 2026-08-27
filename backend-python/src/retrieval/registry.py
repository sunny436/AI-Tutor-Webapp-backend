"""
retrieval/registry.py
---------------------
THE single edit point for RAG.

Adding a knowledge source to the consultation = write one retriever file, add one
line here. Nothing in `src/consult/` changes.

The `order` values encode the specified pipeline sequence:

    10  user history & knowledge
    20  previous conversations
    30  medical profile
    40  uploaded reports                             <- live
    45  external GraphRAG document service           <- AUTHORITATIVE
    50  vector search over the Ayurveda/Yoga notes   <- rollback only (LOCAL_RAG_ENABLED)

They run concurrently; `order` only decides where each lands in the final prompt.
"""

from __future__ import annotations

import config
from src.retrieval.base import Retriever
from src.retrieval.graphrag import GraphRagRetriever
from src.retrieval.knowledge import KnowledgeRetriever
from src.retrieval.memory import PreviousConversationsRetriever
from src.retrieval.pipeline import RetrievalPipeline
from src.retrieval.stubs import (
    MedicalProfileRetriever,
    UploadedReportsRetriever,
    UserHistoryRetriever,
)

RETRIEVERS: list[Retriever] = [
    UserHistoryRetriever(enabled=False),
    # LIVE. Reads earlier consultations from Convex via the service-key-guarded
    # /backend/user-memory route. Lives in its own module rather than stubs.py
    # now that it does real work.
    PreviousConversationsRetriever(enabled=True),
    MedicalProfileRetriever(enabled=False),
    UploadedReportsRetriever(enabled=True),
    # External document service, order 45. THIS IS THE AYURVEDA KNOWLEDGE SOURCE.
    #
    # This entry is retrieval only, and `GRAPHRAG_ENABLED` gates only this entry.
    #
    # It does NOT gate the vendor's /v1/answer. This comment used to claim that
    # /v1/answer "is never called, because a second unaudited model writing
    # health text would bypass every rule in prompts.py". That is now the exact
    # opposite of the truth, and it is worth being blunt about because it is a
    # safety-relevant fact that a reader would otherwise take on trust:
    #
    #   consult/graph.py:382 calls graphrag.answer() and returns its prose
    #   verbatim as the user's health answer, on every plan turn. The vendor
    #   picks that model; _answer_request sends no `model` field, so it cannot
    #   be named or pinned from here.
    #
    # The reasoning in the old comment still stands - which is exactly why
    # safety.scan and the gathering red-flag check run BEFORE that call rather
    # than relying on the vendor's prompt. See the comment at graph.py:936.
    GraphRagRetriever(enabled=config.GRAPHRAG_ENABLED),
    KnowledgeRetriever(enabled=config.LOCAL_RAG_ENABLED),
]

_pipeline: RetrievalPipeline | None = None


def get_pipeline() -> RetrievalPipeline:
    """The shared pipeline (built once, reused for every consultation)."""
    global _pipeline
    if _pipeline is None:
        _pipeline = RetrievalPipeline(RETRIEVERS)
    return _pipeline
