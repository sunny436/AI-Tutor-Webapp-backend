"""Embeddings behind LangChain's `Embeddings` interface.

Nothing else in the application knows which provider produces vectors: ingestion
and retrieval depend only on `langchain_core.embeddings.Embeddings`, built here from
settings. Every vector is length-checked against the configured dimension, which
must equal the pgvector column (see `app.db.models.EMBEDDING_DIMENSIONS`).
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re

import httpx
import openai
from langchain_core.embeddings import Embeddings
from openai import AsyncOpenAI, OpenAI

from app.llm.openai_compatible import redact_secrets
from app.rag.errors import EmbeddingError
from app.settings import Settings


def _check(vectors: list[list[float]], dimensions: int) -> list[list[float]]:
    for vector in vectors:
        if len(vector) != dimensions:
            raise EmbeddingError("embedding_dimension_mismatch", f"got {len(vector)}, expected {dimensions}")
        if not all(math.isfinite(x) for x in vector):
            raise EmbeddingError("embedding_invalid", "non-finite value in embedding")
    return vectors


class OpenAICompatibleEmbeddings(Embeddings):
    """Any OpenAI-compatible `/embeddings` endpoint (OpenAI text-embedding-3-*, or compatible gateways)."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int,
        batch_size: int = 64,
        timeout_s: float = 20.0,
        send_dimensions: bool = True,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self.batch_size = max(1, batch_size)
        self.send_dimensions = send_dimensions
        self.configured = bool(api_key)
        timeout = httpx.Timeout(timeout_s, connect=min(10.0, timeout_s))
        self._async = AsyncOpenAI(
            api_key=api_key or "missing", base_url=base_url, max_retries=0, timeout=timeout, http_client=http_client
        )
        self._sync = OpenAI(api_key=api_key or "missing", base_url=base_url, max_retries=0, timeout=timeout)

    def _kwargs(self) -> dict:
        return {"dimensions": self.dimensions} if self.send_dimensions else {}

    @staticmethod
    def _error(error: Exception) -> EmbeddingError:
        detail = redact_secrets(f"{type(error).__name__}: {str(error)[:200]}")
        if isinstance(error, (openai.APITimeoutError, httpx.TimeoutException, asyncio.TimeoutError)):
            return EmbeddingError("embedding_timeout", detail)
        if isinstance(error, (openai.AuthenticationError, openai.PermissionDeniedError)):
            return EmbeddingError("embedding_unauthorized", detail)
        return EmbeddingError("embedding_failed", detail)

    def _require_configured(self) -> None:
        if not self.configured:
            raise EmbeddingError("embeddings_unconfigured", "no embedding API key configured")

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        self._require_configured()
        vectors: list[list[float]] = []
        try:
            for start in range(0, len(texts), self.batch_size):
                batch = texts[start : start + self.batch_size]
                response = await self._async.embeddings.create(model=self.model, input=batch, **self._kwargs())
                vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
        except EmbeddingError:
            raise
        except Exception as error:  # noqa: BLE001 - mapped to a typed, redacted error
            raise self._error(error) from error
        return _check(vectors, self.dimensions)

    async def aembed_query(self, text: str) -> list[float]:
        return (await self.aembed_documents([text]))[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self._require_configured()
        vectors: list[list[float]] = []
        try:
            for start in range(0, len(texts), self.batch_size):
                batch = texts[start : start + self.batch_size]
                response = self._sync.embeddings.create(model=self.model, input=batch, **self._kwargs())
                vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
        except EmbeddingError:
            raise
        except Exception as error:  # noqa: BLE001
            raise self._error(error) from error
        return _check(vectors, self.dimensions)

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


_TOKEN = re.compile(r"\w{2,}", re.UNICODE)


class KeywordHashEmbeddings(Embeddings):
    """Deterministic, offline embedder for tests and local development. NOT semantic.

    Each word is hashed (stable across processes) into one of `dimensions` buckets;
    vectors are L2-normalised, so cosine similarity measures shared vocabulary.
    It exercises the real pipeline (pgvector, filters, ranking thresholds) without a
    provider, but says nothing about real retrieval quality. Refused in production.
    """

    configured = True

    def __init__(self, dimensions: int, model: str = "keyword-hash") -> None:
        self.dimensions = dimensions
        self.model = model

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in _TOKEN.findall(text.lower()):
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        norm = math.sqrt(sum(x * x for x in vector))
        if norm == 0:
            vector[0] = 1.0  # no words: a fixed unit vector, similar to nothing in particular
            return vector
        return [x / norm for x in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        return self.embed_query(text)


def build_embeddings(settings: Settings) -> Embeddings:
    if settings.embedding_provider == "fake":
        return KeywordHashEmbeddings(settings.embedding_dimensions, model=f"fake:{settings.embedding_model}")
    return OpenAICompatibleEmbeddings(
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key.get_secret_value(),
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        batch_size=settings.embedding_batch_size,
        timeout_s=settings.embedding_timeout_s,
    )


def embedding_model_id(embeddings: Embeddings) -> str:
    """The identifier stored with every chunk; chunks from other models are never searched."""
    return getattr(embeddings, "model", type(embeddings).__name__)


def is_configured(embeddings: Embeddings) -> bool:
    return bool(getattr(embeddings, "configured", True))
