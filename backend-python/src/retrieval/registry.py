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
    50  vector search over the Ayurveda/Yoga notes   <- live

They run concurrently; `order` only decides where each lands in the final prompt.
"""

from __future__ import annotations

from src.retrieval.base import Retriever
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
    KnowledgeRetriever(enabled=True),
]

_pipeline: RetrievalPipeline | None = None


def get_pipeline() -> RetrievalPipeline:
    """The shared pipeline (built once, reused for every consultation)."""
    global _pipeline
    if _pipeline is None:
        _pipeline = RetrievalPipeline(RETRIEVERS)
    return _pipeline
