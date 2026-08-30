"""Pluggable retrieval layer — see `registry.py` to add a knowledge source."""

from src.retrieval.base import Chunk, RetrievalContext, RetrievalResult, Retriever
from src.retrieval.pipeline import RetrievalPipeline
from src.retrieval.registry import RETRIEVERS, get_pipeline

__all__ = [
    "Chunk",
    "RetrievalContext",
    "RetrievalResult",
    "Retriever",
    "RetrievalPipeline",
    "RETRIEVERS",
    "get_pipeline",
]
