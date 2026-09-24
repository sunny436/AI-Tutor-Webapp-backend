"""Typed RAG errors. `code` is safe to log and persist; messages never carry provider text or data."""


class RagError(Exception):
    code = "rag_error"

    def __init__(self, code: str | None = None, detail: str = "") -> None:
        super().__init__(detail or (code or self.code))
        if code:
            self.code = code


class EmbeddingError(RagError):
    """The embedding provider failed, timed out, is unconfigured, or returned wrong-sized vectors."""

    code = "embedding_failed"


class RetrievalError(RagError):
    """The knowledge store could not be searched (database unavailable, invalid filter, ...)."""

    code = "retrieval_failed"


class IngestionError(RagError):
    code = "ingestion_failed"
