"""NCERT textbooks for the tutor: the NCERT Knowledge Service's search, as a LangChain retriever.

The service runs on its own (ncert-kb-api, 127.0.0.1:4200 in production) and owns its data; this
app only calls its versioned API, `POST /api/v1/retrieval/search`, never its database. On when
NCERT_KB_BASE_URL and NCERT_KB_API_KEY are set (app/main.py wires it instead of the pgvector
knowledge base, which is empty in production).

- **What is sent:** the question, with Classes 6-12 as a `strict` scope (SERVED_CLASSES: Classes 1-5
  are never searched, and a result outside it is dropped here too). The student's class and subjects
  never leave this app: they only rank the results here (their own books first). Never who the
  student is: no id, name or email.
- **Vector mode only:** one pass; the service's query encoder is most of its time (~0.6 s on the VM).
- **Fast failure:** one pooled client with keep-alive; a hard timeout (NCERT_KB_TIMEOUT_S); after
  FAILURES_TO_PAUSE failures in a row, calls are skipped for PAUSE_S. Every failure is a RagError,
  so the turn goes on without textbook context (app/rag/graph.py), never fails.
- **Untrusted input:** results are validated field by field; malformed ones are dropped and each
  passage is capped, so the prompt budget (app/rag/context.py) stays the only one that decides.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from langchain_core.callbacks import AsyncCallbackManagerForRetrieverRun, CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from app.logging import get_logger
from app.rag.errors import RagError

log = get_logger("app.rag.ncert")

SEARCH_PATH = "/api/v1/retrieval/search"
MAX_QUERY_CHARS = 2_000  # the service's own limit
MAX_PASSAGE_CHARS = 4_000
FAILURES_TO_PAUSE = 3
PAUSE_S = 30.0
# Owner decision (2026-10-14): the tutor serves Classes 6-12 only.
SERVED_CLASSES = (6, 7, 8, 9, 10, 11, 12)


def subject_id(name: str) -> str:
    """The service's subject ids are its names in slug form: "Social Science" -> "social-science"."""
    return "-".join(name.lower().replace("&", "and").split())


def citation_title(result: dict[str, Any]) -> str:
    """What a student sees for [n]: book, class, chapter and the printed page."""
    curriculum, source = result["curriculum"], result["source"]
    classes = curriculum.get("classes") or []
    chapter = curriculum["chapter"]
    number = chapter.get("number")
    title = f"NCERT {curriculum['book']['title']}"
    if classes:
        title += f" (Class {', '.join(str(c) for c in classes)})"
    title += f", Ch {number}: {chapter['title']}" if number is not None else f", {chapter['title']}"
    start, end = source.get("printed_page_start"), source.get("printed_page_end")
    if start:
        title += f", p. {start}" if not end or end == start else f", pp. {start}-{end}"
    return title


class NcertKnowledge:
    """One pooled HTTP client to the service, shared by every turn."""

    def __init__(
        self, base_url: str, api_key: str, timeout_s: float, transport: httpx.AsyncBaseTransport | None = None
    ):
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=httpx.Timeout(timeout_s, connect=min(timeout_s, 1.0)),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            transport=transport,
        )
        self._failures = 0
        self._paused_until = 0.0

    async def aclose(self) -> None:
        await self._client.aclose()

    def _failed(self, code: str, detail: str = "") -> RagError:
        self._failures += 1
        if self._failures >= FAILURES_TO_PAUSE:
            self._paused_until = time.monotonic() + PAUSE_S
        log.warning("ncert search failed", extra={"reason": code, "detail": detail[:120], "failures": self._failures})
        return RagError(code)

    async def search(self, query: str, k: int, classes: tuple[int, ...], subjects: tuple[str, ...]) -> list[Document]:
        if time.monotonic() < self._paused_until:
            raise RagError("ncert_paused")
        wanted = {subject_id(name) for name in subjects}
        body: dict[str, Any] = {
            "query": query[:MAX_QUERY_CHARS],
            "mode": "vector",
            # Over-fetched for a student with a curriculum, so their own books can rank first below.
            "top_k": max(1, min(k * 3 if classes or wanted else k, 50)),
            "filters": {"enforcement": "strict", "any_of": [{"classes": list(SERVED_CLASSES)}]},
        }
        try:
            response = await self._client.post(SEARCH_PATH, json=body)
        except httpx.TimeoutException as error:
            raise self._failed("ncert_timeout", type(error).__name__) from error
        except httpx.HTTPError as error:
            raise self._failed("ncert_unavailable", type(error).__name__) from error
        if response.status_code != 200:
            code = "ncert_unauthorized" if response.status_code in (401, 403) else "ncert_unavailable"
            raise self._failed(code, f"HTTP {response.status_code}")
        try:
            payload = response.json()
            results = payload["results"]
            kb_version = str((payload.get("meta") or {}).get("kb_version") or "")
        except (ValueError, KeyError, TypeError) as error:
            raise self._failed("ncert_bad_response", type(error).__name__) from error
        self._failures = 0
        documents = []
        for result in results if isinstance(results, list) else []:
            try:
                content = str(result["content"]).strip()[:MAX_PASSAGE_CHARS]
                curriculum = result["curriculum"]
                served = [c for c in curriculum.get("classes") or [] if c in SERVED_CLASSES]
                if not content or not served:
                    continue
                documents.append(
                    Document(
                        page_content=content,
                        metadata={
                            "chunk_id": str(result["chunk_id"]),
                            "document_id": str(result["curriculum"]["book"]["id"]),
                            "source_id": str(result["source"]["source_id"]),
                            "source": "NCERT",
                            "title": citation_title(result),
                            "uri": None,
                            "ordinal": int(result.get("rank") or len(documents) + 1),
                            "score": float(result["score"]),
                            "in_scope": (not classes or any(c in classes for c in served))
                            and (not wanted or curriculum["subject"]["id"] in wanted),
                            "kb_version": kb_version,
                        },
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue  # one malformed result never costs the others
        documents.sort(key=lambda document: not document.metadata["in_scope"])  # stable: service order within
        return documents[:k]


class NcertRetriever(BaseRetriever):
    """One turn's view of the service: the student's curriculum, k, and timings for the logs."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    knowledge: NcertKnowledge
    k: int = 5
    classes: tuple[int, ...] = ()
    subjects: tuple[str, ...] = ()
    last_timings: dict[str, int] = Field(default_factory=dict)

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        raise NotImplementedError("NcertRetriever is async-only; use `await retriever.ainvoke(query)`")

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun
    ) -> list[Document]:
        self.last_timings = {}
        query = (query or "").strip() if isinstance(query, str) else ""
        if not query:
            return []
        started = time.perf_counter()
        documents = await self.knowledge.search(query, self.k, self.classes, self.subjects)
        self.last_timings = {"search_ms": int((time.perf_counter() - started) * 1000)}
        return documents
