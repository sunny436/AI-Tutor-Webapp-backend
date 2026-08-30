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
    # RETRIEVAL ONLY, again. This entry calls /v1/search and nothing else —
    # `answer()`/`answer_stream()` (the /v1/answer client that used to write
    # the final plan directly) have been DELETED from
    # src/retrieval/graphrag.py, not merely left unused, and a static test
    # (tests/test_reversal.py) greps for exactly that to catch a regression.
    # `write_plan` (src/consult/responder.py, using `prompts.PLAN_PROMPT`)
    # writes every final answer now, from whatever this pipeline assembles.
    # `GRAPHRAG_ENABLED` gates this one retrieval entry — there is no longer
    # a second thing for it to fail to gate.
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
