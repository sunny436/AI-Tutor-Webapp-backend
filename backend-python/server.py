"""
server.py
---------
The Python AI backend (FastAPI). It is a thin proxy in front of GraphRAG:

    GET  /            -> says what this host is
    POST /consult      -> one turn. Safety scan, then GraphRAG writes the reply.
    POST /consult/stream -> the same turn as Server-Sent Events
    POST /jobs/run      -> Convex sends a job; we answer and webhook back
    GET  /whoami        -> verify a Convex login token (JWT) via JWKS
    GET  /health         -> liveness + is GraphRAG reachable

There is no local model, no local knowledge base, and no local retrieval.
GraphRAG's own team owns retrieval and answer quality; this backend verifies
who is asking, refuses to forward a message that looks like a medical
emergency, and relays whatever GraphRAG says. See `src/graphrag.py` and
`src/safety.py` for what each of those two steps actually does.
"""

import asyncio
import json
import sys
from pathlib import Path

from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

import config
from src import graphrag, safety

# Make the logs UTF-8 before anything can write to them.
#
# On Windows, Python picks stdout's encoding from the ANSI codepage whenever
# stdout is NOT a console — which is exactly what a redirected production
# launch gives us. Every print() here logs user text, so a single Devanagari
# or emoji character raises UnicodeEncodeError inside a request handler,
# which becomes an HTTP 500. `errors="replace"` guarantees logging can never
# again take a request down, whatever arrives. `line_buffering=True` so a
# print() written during an incident is not sitting unflushed in an 8 KB
# buffer when someone goes looking for it.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except (AttributeError, ValueError):
        pass

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Ayurveda & Yoga AI Backend")

# Only the app's own origin may call this API from a browser. The browser
# sends the Convex JWT on the direct path, so any page the user happened to
# be visiting could otherwise script authenticated calls against this backend
# and read the replies. Wildcard origins cannot be combined with credentials,
# so nothing is lost by naming the origins explicitly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


# ---------- auth helpers ----------
def _check_service_key(x_service_key: str | None) -> None:
    if (x_service_key or "") != config.SERVICE_KEY:
        raise HTTPException(status_code=401, detail="bad service key")


def _bearer(authorization: str) -> str:
    return authorization[7:] if authorization.startswith("Bearer ") else ""


def require_user(authorization: str, service_key: str = "") -> str:
    """Verified user id, or 401 when `config.REQUIRE_AUTH` is on.

    A valid service key is accepted as an alternative credential — it
    identifies no user, so it unlocks admission without unlocking anybody's
    private data, and it is what lets `/jobs/run` and the test suite reach
    GraphRAG without minting a login.
    """
    user_id = verify_token(_bearer(authorization))
    if user_id:
        return user_id
    if service_key and config.SERVICE_KEY and service_key == config.SERVICE_KEY:
        return ""
    if config.REQUIRE_AUTH:
        raise HTTPException(status_code=401, detail="login required")
    return ""


_jwk_client = None


def _signing_key(token: str):
    """The public key Convex signed `token` with.

    Convex issues JWTs whose header is just `{"alg":"RS256"}` — there is no
    `kid` — and publishes a JWKS whose single key has no `kid` either, so this
    falls back to the sole signing key in the set when the token carries none.

    THE USER-AGENT IS LOAD-BEARING. `PyJWKClient` fetches over `urllib`,
    which sends `Python-urllib/3.x`, and the edge in front of
    CONVEX_SITE_URL answers that with 403 Forbidden — silently failing every
    login. A UA that identifies this service truthfully is both accurate and
    sufficient.
    """
    global _jwk_client
    import jwt  # PyJWT

    if _jwk_client is None:
        _jwk_client = jwt.PyJWKClient(
            f"{config.CONVEX_SITE_URL}/.well-known/jwks.json",
            cache_keys=True,
            headers={"User-Agent": "ayurveda-backend/1.0"},
        )

    if jwt.get_unverified_header(token).get("kid"):
        return _jwk_client.get_signing_key_from_jwt(token).key

    signing_keys = [k for k in _jwk_client.get_jwk_set().keys if k.key_type == "RSA"]
    if len(signing_keys) != 1:
        raise ValueError(f"expected exactly one RSA signing key, found {len(signing_keys)}")
    return signing_keys[0].key


def verify_token(token: str) -> str:
    """Return the Convex user id for a login token, or "" if it is not valid.

    Deliberately not a 401 on failure: an anonymous or expired session should
    still be able to consult; it just does not get past `require_user` on the
    endpoints that spend GraphRAG's quota.
    """
    if not token:
        return ""
    try:
        import jwt  # PyJWT

        payload = jwt.decode(
            token,
            _signing_key(token),
            algorithms=["RS256"],
            audience=config.CONVEX_AUDIENCE,
        )
        return str(payload.get("sub") or "")
    except Exception as error:  # noqa: BLE001
        detail = str(error)
        if "url" in detail.lower() or "fetch" in detail.lower():
            print(
                f"[auth] CANNOT FETCH SIGNING KEYS from {config.CONVEX_SITE_URL}"
                f"/.well-known/jwks.json - {detail}. This rejects EVERY login "
                "until it is fixed; the tokens themselves are fine."
            )
        else:
            print(f"[auth] token rejected: {detail}")
        return ""


async def _post_webhook(body: dict) -> None:
    import httpx

    url = f"{config.CONVEX_SITE_URL}/backend/webhook"
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(url, headers={"x-webhook-secret": config.WEBHOOK_SECRET}, json=body)


# ---------- the one thing this backend decides on its own ----------
def _query_text(data: dict) -> str:
    """What the user actually said this turn.

    `freeText` and `problem` are kept as separate request fields for
    compatibility with the existing frontend contract, but nothing here
    branches on which one arrived — every turn is answered on its own, with
    no server-side conversation state, so there is nothing left for the
    distinction to mean.
    """
    text = (data.get("freeText") or data.get("problem") or "").strip()
    profile = (data.get("profile") or "").strip()
    if profile and text:
        return f"{text}\n\n(About the person asking: {profile})"
    return text or profile


def _safety_result(message: str, context: dict) -> dict | None:
    """An escalation or supportive-care reply, or None if the message is clear
    to forward to GraphRAG. The ONLY local decision this backend still makes."""
    if safety.scan(message):
        return {
            "kind": "escalation",
            "condition": "",
            "message": "",
            "answer": safety.ESCALATION_MESSAGE,
            "intake": None,
            "context": context,
            "sources": [],
        }
    if safety.is_serious_condition(message):
        return {
            "kind": "chat",
            "condition": "",
            "message": "",
            "answer": safety.SERIOUS_CONDITION_MESSAGE,
            "intake": None,
            "context": context,
            "sources": [],
        }
    return None


def _sources_from_citations(citations) -> list[dict]:
    out = []
    for citation in citations or []:
        if not isinstance(citation, dict):
            continue
        name = citation.get("filename") or citation.get("document_id") or "unknown"
        out.append({
            "section": "Reference documents",
            "source": f"graphrag:{name}",
            "score": citation.get("score"),
        })
    return out


# ======================================================================
#  A) THE CONSULTATION
# ======================================================================
@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<title>Ayurveda API</title>"
        "<h1>Ayurveda &amp; Yoga API</h1>"
        "<p>This host serves the API only. The app is at "
        "<a href='https://ayur.namahos.com'>ayur.namahos.com</a>.</p>"
    )


@app.post("/consult")
async def consult(
    request: Request,
    authorization: str = Header(default=""),
    x_service_key: str = Header(default=""),
):
    """One turn. `context` is echoed back unchanged — there is no server-side
    conversation state to merge into it any more."""
    try:
        data = await request.json()
    except (UnicodeDecodeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=f"invalid JSON body: {error}")

    require_user(authorization, x_service_key)
    context = data.get("context") or {}

    message = _query_text(data)
    if not message:
        return {
            "kind": "chat", "condition": "", "message": "", "answer": "",
            "intake": None, "context": context, "sources": [],
        }

    flagged = _safety_result(message, context)
    if flagged:
        return flagged

    if not config.is_graphrag_ready():
        raise HTTPException(status_code=503, detail="service is not configured")

    try:
        body = await asyncio.to_thread(graphrag.answer, message)
    except Exception as error:  # noqa: BLE001
        print(f"[consult] GraphRAG call failed: {error}")
        return {
            "kind": "error", "condition": "", "message": "AI service unavailable, please try again.",
            "answer": "AI service unavailable, please try again.",
            "intake": None, "context": context, "sources": [],
        }

    answer_text = (body.get("answer") or "").strip()
    if not answer_text:
        return {
            "kind": "error", "condition": "", "message": "AI service unavailable, please try again.",
            "answer": "AI service unavailable, please try again.",
            "intake": None, "context": context, "sources": [],
        }

    return {
        "kind": "answer",
        "condition": "",
        "message": "",
        "answer": answer_text,
        "intake": None,
        "context": context,
        "sources": _sources_from_citations(body.get("citations")),
    }


@app.post("/consult/stream")
async def consult_stream(
    request: Request,
    authorization: str = Header(default=""),
    x_service_key: str = Header(default=""),
):
    """The same turn as POST /consult, delivered as Server-Sent Events.

    Two event types:
      token: {"text": "..."}   a piece of GraphRAG's reply as it is written
      done:  <same JSON /consult would have returned>
    """
    try:
        data = await request.json()
    except (UnicodeDecodeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=f"invalid JSON body: {error}")

    require_user(authorization, x_service_key)
    context = data.get("context") or {}
    message = _query_text(data)

    flagged = None if not message else _safety_result(message, context)

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def run_blocking() -> None:
        try:
            pieces: list[str] = []
            for piece in graphrag.answer_stream(message):
                pieces.append(piece)
                loop.call_soon_threadsafe(queue.put_nowait, ("token", piece))
            answer_text = "".join(pieces).strip()
            result = {
                "kind": "answer", "condition": "", "message": "", "answer": answer_text,
                "intake": None, "context": context, "sources": [],
            }
            loop.call_soon_threadsafe(queue.put_nowait, ("done", result))
        except Exception as error:  # noqa: BLE001
            print(f"[consult] GraphRAG stream failed: {error}")
            loop.call_soon_threadsafe(
                queue.put_nowait, ("error", "AI service unavailable, please try again.")
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    async def run() -> None:
        if not message:
            await queue.put(("done", {
                "kind": "chat", "condition": "", "message": "", "answer": "",
                "intake": None, "context": context, "sources": [],
            }))
            await queue.put(None)
            return
        if flagged:
            await queue.put(("done", flagged))
            await queue.put(None)
            return
        if not config.is_graphrag_ready():
            await queue.put(("error", "service is not configured"))
            await queue.put(None)
            return
        await asyncio.to_thread(run_blocking)

    KEEPALIVE_SECONDS = 15

    async def events():
        task = asyncio.create_task(run())
        try:
            yield ": open\n\n"
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), KEEPALIVE_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if item is None:
                    break
                kind, payload = item
                yield f"event: {kind}\ndata: {json.dumps(payload if kind != 'token' else {'text': payload})}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ======================================================================
#  B) CONVEX INTEGRATION
# ======================================================================
@app.get("/health")
def health():
    return {
        "ok": True,
        "graphrag_ready": config.is_graphrag_ready(),
        "graphrag": graphrag.health(),
    }


@app.get("/whoami")
def whoami(authorization: str = Header(default="")):
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    sub = verify_token(token)
    if not sub:
        raise HTTPException(status_code=401, detail="invalid token")
    return {"verified": True, "sub": sub}


@app.post("/jobs/run")
async def jobs_run(request: Request, x_service_key: str = Header(default="")):
    """Convex hands us a consultation job; we answer and webhook the result back."""
    _check_service_key(x_service_key)
    body = await request.json()
    job_id = body.get("jobId")
    data = body.get("input", {}) or {}
    message = _query_text(data)

    if not message:
        await _post_webhook({"type": "job.result", "jobId": job_id, "result": None, "error": "empty problem"})
        return {"accepted": True, "jobId": job_id}

    flagged = _safety_result(message, {})
    if flagged:
        await _post_webhook({
            "type": "job.result", "jobId": job_id,
            "result": {"kind": flagged["kind"], "answer": flagged["answer"], "knowledge_used": ""},
        })
        return {"accepted": True, "jobId": job_id}

    if not config.is_graphrag_ready():
        await _post_webhook({"type": "job.result", "jobId": job_id, "result": None, "error": "GraphRAG not configured"})
        return {"accepted": True, "jobId": job_id}

    try:
        answer_body = await asyncio.to_thread(graphrag.answer, message)
        await _post_webhook({
            "type": "job.result", "jobId": job_id,
            "result": {"kind": "answer", "answer": answer_body.get("answer") or "", "knowledge_used": ""},
        })
    except Exception as e:
        await _post_webhook({"type": "job.result", "jobId": job_id, "result": None, "error": str(e)})
    return {"accepted": True, "jobId": job_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host=config.HOST, port=config.PORT, reload=config.RELOAD)
