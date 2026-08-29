"""
graphrag.py
-----------
The ONLY source of consultation answers. Every question this backend receives
goes to GraphRAG's `/v1/answer` (or `/v1/answer/stream`) verbatim, and whatever
it says is what the user sees — unless `safety.py` has already stopped the turn
before this module is ever called.

This used to be one retriever among several, with a local alias index deciding
whether to trust GraphRAG's score, a Chroma vector store as a rollback, and an
offline fallback that rendered a static note when the service was down. All of
that management has been removed on purpose: GraphRAG's own team owns retrieval
and answer quality now, and this backend's job is to forward the question and
relay the reply, nothing more.

What that costs, stated plainly rather than discovered later:
  - No local knowledge base means no fallback when GraphRAG is unreachable.
    An outage is now a plain error, not a degraded-but-working answer.
  - Nothing here corrects a vague or Hinglish-heavy query before it is sent.
    Retrieval quality inside GraphRAG is now entirely GraphRAG's concern.
  - There is no conversation memory. `/v1/answer` takes only `query` and `k`,
    so every turn is answered on its own, with no history attached.
"""

from __future__ import annotations

import json
import re
import time
from typing import Iterator

import config

# The vendor validates 1-2000 and returns 422 outside it.
MAX_QUERY_CHARS = 2000

# ---------------------------------------------------------------------------
# Citation markers. GraphRAG's model sometimes writes its internal chunk/doc
# ids inline in the prose ("[chunk:doc:<uuid>:3]") instead of only in the
# structured `citations` array. Those ids must never reach a reader — kept
# here verbatim from the retriever that used to own this, because the model's
# habits did not change when the calling code did.
# ---------------------------------------------------------------------------
_ID_PREFIX = r"(?:chunk(?:_id)?|doc(?:ument)?(?:_id)?)\s*:\s*"
_UUIDISH = r"[0-9a-fA-F][0-9a-fA-F-]{7,}(?::\d+)?"
_CITATION_MARKER = re.compile(
    r"[ \t]*(?:"
    rf"[\[(]\s*(?:{_ID_PREFIX})?(?:{_ID_PREFIX})?{_UUIDISH}\s*[\])]"
    rf"|[\[(]\s*{_ID_PREFIX}\s*[\])]"
    rf"|{_ID_PREFIX}(?:{_ID_PREFIX})?{_UUIDISH}"
    r")"
)
_ORPHAN_SPACE = re.compile(r"[ \t]+([.,;:!?।])")
_MAX_MARKER_CHARS = 80
_RESIDUE = re.compile(r"(?:chunk(?:_id)?|doc(?:ument)?(?:_id)?)\s*:\s*\S{0,48}")


def strip_citation_markers(text: str) -> str:
    """Remove inline citation markers, so no internal id is ever shown to a user."""
    cleaned = _ORPHAN_SPACE.sub(r"\1", _CITATION_MARKER.sub("", text or ""))
    leftover = _RESIDUE.search(cleaned)
    if leftover:
        print(
            "[graphrag] CITATION SHAPE NOT STRIPPED: "
            f"{leftover.group(0)!r} - add it to _CITATION_MARKER"
        )
    return cleaned


# ---------------------------------------------------------------------------
# Health tracking, published on /health so an outage is visible without
# reading logs.
# ---------------------------------------------------------------------------
LAST_SUCCESS_AT: float | None = None
CONSECUTIVE_FAILURES = 0


def health() -> dict:
    return {
        "configured": bool(config.GRAPHRAG_BASE_URL and config.GRAPHRAG_API_KEY),
        "last_success_age_s": (
            None if LAST_SUCCESS_AT is None else round(time.monotonic() - LAST_SUCCESS_AT, 1)
        ),
        "consecutive_failures": CONSECUTIVE_FAILURES,
    }


def _stamp_success() -> None:
    global LAST_SUCCESS_AT, CONSECUTIVE_FAILURES
    LAST_SUCCESS_AT = time.monotonic()
    CONSECUTIVE_FAILURES = 0


def _stamp_failure(what: str, error: object) -> None:
    global CONSECUTIVE_FAILURES
    CONSECUTIVE_FAILURES += 1
    print(f"[graphrag] {what} failed ({CONSECUTIVE_FAILURES} in a row): {error}")


def _request(query: str) -> tuple[str, dict, dict]:
    """(base_url, headers, body) for a call, or raise if unconfigured."""
    base = (config.GRAPHRAG_BASE_URL or "").rstrip("/")
    if not base or not config.GRAPHRAG_API_KEY:
        raise RuntimeError("GraphRAG is not configured (base url or api key is empty)")
    body = {
        "query": (query or "").strip()[:MAX_QUERY_CHARS],
        "k": config.GRAPHRAG_TOP_K,
    }
    headers = {
        "Authorization": f"Bearer {config.GRAPHRAG_API_KEY}",
        "content-type": "application/json",
    }
    return base, headers, body


def answer(query: str) -> dict:
    """Blocking. POST /v1/answer -> {answer, citations, ...}. Runs off the event loop."""
    import httpx

    base, headers, body = _request(query)
    try:
        response = httpx.post(
            f"{base}/v1/answer",
            headers=headers,
            json=body,
            # NEVER verify=False: it leaves the connection encrypted but
            # unauthenticated, letting anyone on the network read the API key.
            verify=config.GRAPHRAG_CA_BUNDLE or True,
            timeout=config.GRAPHRAG_ANSWER_TIMEOUT_S,
        )
        response.raise_for_status()
        parsed = response.json()
    except Exception as error:
        _stamp_failure("answer", error)
        raise

    _stamp_success()
    if not isinstance(parsed, dict):
        return {"answer": "", "citations": []}
    parsed["answer"] = strip_citation_markers(parsed.get("answer") or "")
    return parsed


def answer_stream(query: str) -> Iterator[str]:
    """Blocking generator. Yields pieces of the reply as the model writes them.

    Frames are `data: {"t": "<piece>"}`, ending with a literal `data: [DONE]`.

    Markers cannot be stripped per frame — a marker is routinely split across
    several small frames — so this holds back a trailing `[...` until the
    bracket closes or the run is long enough to be certain it was ordinary
    prose, then releases it through `strip_citation_markers`.
    """
    import httpx

    base, headers, body = _request(query)
    seen_done = False
    buffer = ""

    def _flush(text: str) -> tuple[str, str]:
        opened, closed = text.rfind("["), text.rfind("]")
        if opened > closed and len(text) - opened <= _MAX_MARKER_CHARS:
            held = opened
            while held > 0 and text[held - 1] in " \t":
                held -= 1
            return text[:held], text[held:]
        safe = text.rstrip(" \t")
        return safe, text[len(safe):]

    try:
        with httpx.stream(
            "POST",
            f"{base}/v1/answer/stream",
            headers=headers,
            json=body,
            verify=config.GRAPHRAG_CA_BUNDLE or True,
            timeout=config.GRAPHRAG_ANSWER_TIMEOUT_S,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    seen_done = True
                    break
                try:
                    piece = json.loads(payload).get("t", "")
                except Exception:
                    continue
                if not piece:
                    continue
                buffer += piece
                ready, buffer = _flush(buffer)
                if ready:
                    cleaned = strip_citation_markers(ready)
                    if cleaned:
                        yield cleaned
    except Exception as error:
        _stamp_failure("answer/stream", error)
        raise

    if buffer:
        cleaned = strip_citation_markers(buffer)
        if cleaned:
            yield cleaned

    if not seen_done:
        # A plan cut off mid-way reads as complete when it is not — say so
        # rather than hand back a truncated reply silently.
        _stamp_failure("answer/stream", "stream ended without [DONE]")
        raise RuntimeError("GraphRAG stream ended before the answer was complete")

    _stamp_success()
