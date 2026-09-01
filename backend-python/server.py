"""
server.py
---------
The Python AI backend (FastAPI). It does two jobs:

A) Answers consultations for the dashboard
   - GET  /            -> says what this host is
   - POST /consult     -> one turn of the consultation (also /consult/stream)
   - POST /upload      -> read text from an uploaded report (PDF/image),
                          index it for this user, and hand the text back too
   - GET  /documents, DELETE /documents/{filename} -> manage indexed reports

B) Talks to the Convex template (the "bring your own backend" paths):
   - POST /jobs/run    -> Convex sends a consult job; we answer and webhook back
   - POST /extract     -> read a report (protected by the shared service key)
   - GET  /whoami      -> verify a Convex login token (JWT) via JWKS
   - GET  /health      -> liveness + provider/GraphRAG/model status

RESTORED from the pre-`d7e6d42` architecture: this file is thin again —
`src.consult.run_turn` does the safety scan, routing, retrieval, memory, and
plan-writing. GraphRAG is one retriever among several now (see
src/retrieval/registry.py); it no longer writes the answer.
"""

import asyncio
import base64
import json
import sys
import tempfile
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Header, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

import config
from src.consult import run_turn as run_consult_turn
from src.documents import extract_text

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
#
# DELETE is in the list because the browser uses it for the report-removal
# button. X-Service-Key is deliberately NOT allowed: those routes are called
# server-to-server by Convex, where CORS does not apply.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.on_event("startup")
def _warm_up_on_startup():
    """Load the AI models once at startup so the first answer is already fast."""
    try:
        from src.knowledge import warm_up
        from src.llm import get_llm
        warm_up()          # loads embeddings + vector DB once
        get_llm(0.2)       # pre-build the LLM clients
        get_llm(0.5)
        print("Warm-up complete — answers will be fast now.")
    except Exception as e:
        print("Warm-up skipped:", e)


# ---------- helpers ----------
def _check_service_key(x_service_key: str | None) -> None:
    if (x_service_key or "") != config.SERVICE_KEY:
        raise HTTPException(status_code=401, detail="bad service key")


def _bearer(authorization: str) -> str:
    return authorization[7:] if authorization.startswith("Bearer ") else ""


_balance_cache: dict[str, float] = {}


def _openrouter_balance() -> float | None:
    """Remaining OpenRouter credit in USD, or None if it cannot be read.

    Refreshed at most every five minutes so a supervisor polling /health once
    a minute doesn't turn this into extra load, and a failed lookup never
    fails liveness — it is simply omitted.
    """
    if not config.OPENROUTER_API_KEY:
        return None

    now = time.monotonic()
    if _balance_cache and now - _balance_cache.get("at", 0.0) < 300:
        return _balance_cache.get("value")

    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(
                "https://openrouter.ai/api/v1/credits",
                headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
            )
            data = (response.json() or {}).get("data") or {}
        value = round(
            float(data.get("total_credits") or 0) - float(data.get("total_usage") or 0), 4
        )
    except Exception as error:  # noqa: BLE001
        print(f"[health] could not read OpenRouter balance: {type(error).__name__}")
        return None

    _balance_cache.update({"at": now, "value": value})
    return value


def require_user(authorization: str, service_key: str = "") -> str:
    """Verified user id, or 401 when `config.REQUIRE_AUTH` is on.

    A valid service key is accepted as an alternative credential — it
    identifies no user, so it unlocks admission without unlocking anybody's
    private data, and it is what lets `/jobs/run` and the test suite reach
    the flow without minting a login.
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


# Convex Auth puts BOTH ids in `sub`, joined by this character:
#
#     "m572jrdvnt10jr7d25e9nhke098dg7rv|js7cfyj9z922v5j2f7kbbkfhkd8dhhhb"
#      \______________ user ___________/ \____________ session ________/
#
# Its own `getAuthUserId` is literally `identity.subject.split("|")[0]`
# (@convex-dev/auth/dist/server/implementation/index.js), so this is the
# library's format rather than a guess.
TOKEN_SUB_CLAIM_DIVIDER = "|"


def verify_token(token: str) -> str:
    """Return the Convex user id for a login token, or "" if it is not valid.

    This is the ONLY thing allowed to establish who is asking. A client's own
    `principal` claim is never trusted for anything that selects private
    data — a forged principal must buy nothing.

    THE SESSION HALF OF `sub` IS DROPPED, and not dropping it broke every
    feature that remembers anybody. The whole composite was returned as the
    user id, which is wrong in two separate ways:

      1. It is not a `v.id("users")`. Convex answered every
         `patientProfile.get` and `patientProfile.upsert` with
         `ArgumentValidationError`, `http.ts` caught it and returned
         `{profile: null}` / `{saved: false}` with a 200, and
         `patient_profile.py` — which fails soft on purpose — recorded
         nothing. Silent, total, and permanent: the `patientProfiles` table
         was still EMPTY after a consultation in which the user gave their
         age, their diabetes and their metformin. Everything the product
         promises about remembering a patient was dead.
      2. THE SESSION ID CHANGES ON EVERY LOGIN. So even where an opaque
         string is all that is needed — `user_documents` filters Chroma
         chunks on exactly this value — a user's own uploaded reports became
         unreachable the moment they signed out and back in, and re-uploading
         wrote a second orphaned copy.

    Isolation is unchanged: this is still the subject of a signature-verified
    JWT, with one component removed. `""` on any failure, so a bad token buys
    nothing.
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
        subject = str(payload.get("sub") or "")
        # `split(...)[0]` and not a conditional strip: a subject with no
        # divider is returned whole, which is what an issuer that does not use
        # the composite form would send.
        return subject.split(TOKEN_SUB_CLAIM_DIVIDER)[0]
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
    url = f"{config.CONVEX_SITE_URL}/backend/webhook"
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(url, headers={"x-webhook-secret": config.WEBHOOK_SECRET}, json=body)


def _fold_documents_into_profile(profile: str, documents) -> str:
    """`documents: [{filename, text}]`, if the caller sends it, folded into
    `profile` — the same channel `/jobs/run` has always used for this.

    Kept for frontend compatibility (yesterday's upload contract). It is now
    a SUPPLEMENT, not the only path: `run_consult_turn`'s own retrieval
    pipeline also pulls from this user's indexed uploads automatically (see
    `UploadedReportsRetriever`), so a caller that stops sending this field
    loses nothing — the documents were already indexed at upload time.
    """
    if not isinstance(documents, list) or not documents:
        return profile
    blocks = []
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        text = str(doc.get("text") or "").strip()
        if not text:
            continue
        name = str(doc.get("filename") or "attachment")
        blocks.append(f"--- {name} ---\n{text}")
    if not blocks:
        return profile
    block = "\n\n".join(blocks)
    return f"{profile}\n\nInfo from uploaded documents:\n{block}" if profile else \
        f"Info from uploaded documents:\n{block}"


# ======================================================================
#  A) THE WEB APP
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
    """One turn of the consultation.

    Request : {problem, context, answers, freeText, profile, documents?, principal?}
    Response: {kind, condition, message, intake?, answer?, context, sources}

    Identity comes from the verified token and nowhere else — `principal` is
    threaded through for logging, but `user_id` (what retrievers filter
    private data on) is always overwritten from the JWT.
    """
    try:
        data = await request.json()
    except (UnicodeDecodeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=f"invalid JSON body: {error}")

    token = _bearer(authorization)
    principal = {**(data.get("principal") or {}), "token": token}
    principal["user_id"] = require_user(authorization, x_service_key)

    profile = _fold_documents_into_profile(data.get("profile", ""), data.get("documents"))

    result = await run_consult_turn(
        problem=data.get("problem", ""),
        raw_context=data.get("context"),
        answers=data.get("answers"),
        free_text=data.get("freeText"),
        profile=profile,
        principal=principal,
        conversation_id=data.get("conversationId"),
    )
    return result.model_dump()


@app.post("/consult/stream")
async def consult_stream(
    request: Request,
    authorization: str = Header(default=""),
    x_service_key: str = Header(default=""),
):
    """The same turn as POST /consult, delivered as Server-Sent Events.

    Two event types:
      token: {"text": "..."}   a piece of a prose answer, as the model writes it
      done:  <ConsultResult>   the identical JSON /consult would have returned
    """
    try:
        data = await request.json()
    except (UnicodeDecodeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=f"invalid JSON body: {error}")

    token = _bearer(authorization)
    principal = {**(data.get("principal") or {}), "token": token}
    principal["user_id"] = require_user(authorization, x_service_key)
    profile = _fold_documents_into_profile(data.get("profile", ""), data.get("documents"))

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def on_token(piece: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, piece)

    async def run() -> None:
        try:
            result = await run_consult_turn(
                problem=data.get("problem", ""),
                raw_context=data.get("context"),
                answers=data.get("answers"),
                free_text=data.get("freeText"),
                profile=profile,
                principal=principal,
                on_token=on_token,
                conversation_id=data.get("conversationId"),
            )
            await queue.put(("done", result.model_dump()))
        except Exception as error:  # noqa: BLE001
            print(f"[consult] stream turn failed: {error}")
            await queue.put(("error", str(error)))
        finally:
            await queue.put(None)

    # Cloudflare gives up on an origin that has sent NOTHING and returns 524.
    # These are SSE COMMENTS — a line starting with ":" is ignored by every
    # conforming reader — so they keep the connection demonstrably alive at
    # no cost to the frontend.
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
                if isinstance(item, str):
                    yield f"event: token\ndata: {json.dumps({'text': item})}\n\n"
                    continue
                kind, payload = item
                yield f"event: {kind}\ndata: {json.dumps(payload)}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


MAX_UPLOAD_BYTES = 20 * 1024 * 1024
# Cap on the `text` handed back in the response. Indexing (below) always uses
# the FULL extracted text regardless of this cap — this only bounds what
# round-trips over HTTP for a frontend that still folds it into `documents`.
MAX_EXTRACTED_CHARS = 40_000


@app.post("/upload")
async def upload(
    file: UploadFile = File(...),
    authorization: str = Header(default=""),
):
    """Read a report, index it for this user, and hand the text back too.

    Indexed so later questions can retrieve just the relevant chunk of a long
    report (see `UploadedReportsRetriever`), not only the first ~1200
    characters. `text` is still returned — unindexed callers (or a caller
    still on yesterday's `documents: [...]` contract) keep working unchanged.

    Requires a signed-in caller (see `config.REQUIRE_AUTH`) — an anonymous
    upload still gets its text back but is not indexed (`user_id` is empty,
    and `user_documents` fails closed on that).
    """
    user_id = require_user(authorization)
    filename = file.filename or "upload.bin"
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large (max 20 MB)")

    suffix = Path(filename).suffix or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name
    try:
        # extract_text is blocking (pypdf, and Tesseract shelling out for
        # OCR), so it must not run on the event loop.
        text = await asyncio.to_thread(extract_text, tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    text = text or ""
    indexed = 0
    if user_id and text:
        from src import user_documents

        try:
            indexed = await asyncio.to_thread(
                user_documents.index_document, user_id, filename, text
            )
        except Exception as error:  # noqa: BLE001
            # Extraction already succeeded — an embedding failure (bad or
            # exhausted OpenRouter key, timeout) must not turn a working
            # extraction into a 500. `indexed` stays 0, which is honest: it
            # tells the caller retrieval over this document will not work,
            # without pretending the whole upload failed.
            print(f"[upload] indexing failed for {filename!r} ({type(error).__name__}): {error}")

    truncated = len(text) > MAX_EXTRACTED_CHARS
    response_text = text[:MAX_EXTRACTED_CHARS] if truncated else text
    return {
        "filename": filename,
        "chars": len(response_text),
        "text": response_text,
        "truncated": truncated,
        "indexed": indexed,
    }


@app.get("/documents")
async def list_documents(authorization: str = Header(default="")):
    """Filenames this caller has indexed. Empty when logged out."""
    user_id = verify_token(_bearer(authorization))
    if not user_id:
        return {"documents": []}

    from src import user_documents

    names = await asyncio.to_thread(user_documents.list_documents, user_id)
    return {"documents": names}


@app.delete("/documents/{filename}")
async def delete_document(filename: str, authorization: str = Header(default="")):
    """Remove a document and everything embedded from it.

    Deleting the file without deleting its chunks would leave the report
    quietly answering questions after the user believed it was gone.
    """
    user_id = verify_token(_bearer(authorization))
    if not user_id:
        raise HTTPException(status_code=401, detail="login required")

    from src import user_documents

    await asyncio.to_thread(user_documents.remove_document, user_id, filename)
    return {"ok": True, "filename": filename}


# ======================================================================
#  B) CONVEX INTEGRATION
# ======================================================================
@app.get("/health")
def health():
    """Liveness, plus provider/model/retrieval status and remaining AI credit.

    Cached and best-effort throughout: this is hit every minute by the
    supervisor and must never be slower or less reliable than what it
    reports on, so any one lookup failing is simply omitted.
    """
    from src.llm import _available_models, split_provider

    chain = _available_models("")
    head = chain[0] if chain else ""
    provider, model = split_provider(head) if head else (config.LLM_PROVIDER, "")

    from src.knowledge import alias_index_size as _alias_index_size
    from src.retrieval import graphrag as _graphrag

    payload = {
        "ok": True,
        "llm_ready": config.is_llm_ready(),
        "graphrag_ready": config.is_graphrag_ready(),
        "graphrag": _graphrag.health(),
        # Zero here means match_topics is blind, which makes GraphRAG's
        # coverage gate refuse everything while looking perfectly healthy.
        "alias_index_notes": _alias_index_size(),
        "provider": provider,
        "model": model,
        # How many configured models are not currently cooling down. A drop
        # here is the earliest visible sign of quota trouble.
        "models_available": len(chain),
    }
    balance = _openrouter_balance()
    if balance is not None:
        payload["ai_credit_usd"] = balance
        payload["ai_credit_low"] = balance < 1.0
    return payload


@app.get("/whoami")
def whoami(authorization: str = Header(default="")):
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    sub = verify_token(token)
    if not sub:
        raise HTTPException(status_code=401, detail="invalid token")
    return {"verified": True, "sub": sub}


@app.post("/extract")
async def extract(request: Request, x_service_key: str = Header(default="")):
    _check_service_key(x_service_key)
    body = await request.json()
    filename = body.get("filename", "upload.bin")
    b64 = body.get("base64", "")
    if not b64:
        return {"text": ""}
    raw = base64.b64decode(b64)
    suffix = Path(filename).suffix or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name
    text = extract_text(tmp_path)
    Path(tmp_path).unlink(missing_ok=True)
    return {"text": text}


@app.post("/jobs/run")
async def jobs_run(request: Request, x_service_key: str = Header(default="")):
    """Convex hands us a consultation job; we answer and webhook the result back."""
    _check_service_key(x_service_key)
    body = await request.json()
    job_id = body.get("jobId")
    data = body.get("input", {}) or {}
    problem = data.get("problem", "")
    profile = data.get("profile", "")
    document_text = data.get("document_text", "")
    if document_text:
        profile = f"{profile}\n\nInfo from uploaded documents:\n{document_text}"

    try:
        result = await run_consult_turn(
            problem=problem,
            raw_context=None,
            answers=None,
            free_text=None,
            profile=profile,
        )
    except Exception as e:
        await _post_webhook({"type": "job.result", "jobId": job_id, "result": None, "error": str(e)})
        return {"accepted": True, "jobId": job_id}

    # Built FIELD BY FIELD, never `result.model_dump()`. The Convex `jobs`
    # table accepts `v.any()` for this payload, so a dump would silently
    # write the entire ConsultContext — including chat_history — into a
    # table nobody expects to hold conversation text.
    await _post_webhook({
        "type": "job.result",
        "jobId": job_id,
        "result": {
            "kind": result.kind,
            "answer": result.answer,
            "knowledge_used": "",
        },
    })
    return {"accepted": True, "jobId": job_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host=config.HOST, port=config.PORT, reload=config.RELOAD)
