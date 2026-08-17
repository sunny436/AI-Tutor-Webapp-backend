"""
server.py
---------
The Python AI backend (FastAPI). It does two jobs:

A) Answers consultations for the dashboard
   - GET  /            -> says what this host is; it used to serve a public chat
                          page, which was removed once /chat required a login
   - POST /consult     -> one turn of the card-driven consultation
   - POST /chat        -> the older single-shot flow, signed-in callers only
   - POST /upload      -> read text from an uploaded report (PDF/image)

B) Talks to the Convex template (the "bring your own backend" paths):
   - POST /jobs/run    -> Convex sends a consult job; we answer and webhook back
   - POST /extract     -> read a report (protected by the shared service key)
   - GET  /whoami      -> verify a Convex login token (JWT) via JWKS
   - GET  /health      -> simple "is it alive?" check
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
from src.bots import BOTS, BotConfig, UnknownBotError, get_bot
from src.consult import run_turn as run_consult_turn
from src.graph import run_consult
from src.documents import extract_text

# Make the logs UTF-8 before anything can write to them.
#
# This is a crash fix, not tidiness. On Windows, Python picks stdout's encoding
# from the ANSI codepage (cp1252 here) whenever stdout is NOT a console — which
# is exactly what `Start-Process -RedirectStandardOutput` gives us in production.
# Every `print()` in this codebase logs the text it is working on, so a single
# Devanagari or emoji character raises UnicodeEncodeError. Raised inside a
# request handler, that becomes an HTTP 500.
#
# Reproduced end to end: "मुझे गैस की समस्या है" then "सुबह क्या खाऊँ?" returned
# 500 on the first attempt, every time. The traceback was in `print(...)` at
# src/consult/router.py:525 — the log line, not the logic. It never showed up in
# development because a terminal on this machine reports UTF-8, so the whole
# class of failure only exists once the site is running for real.
#
# Fixed here rather than at each print site: there are dozens, they all handle
# user text, and any one added later would reintroduce it. `errors="replace"`
# guarantees logging can never again take a request down, whatever arrives.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # already wrapped, or not reconfigurable
        pass

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Ayurveda & Yoga AI Backend")

# Only the app's own origin may call this API from a browser.
#
# This was `allow_origins=["*"]` with `allow_methods`/`allow_headers` equally open.
# That is not merely untidy: the browser sends the Convex JWT on the DIRECT path
# (src/lib/backend.config.ts), so any page the user happened to be visiting could
# script authenticated calls against this backend and read the replies. Wildcard
# origins also cannot be combined with credentials, so nothing is lost by naming
# the origins explicitly.
#
# `allow_credentials` stays False on purpose: auth travels in the Authorization
# header, never in a cookie, so cookies have no reason to cross origins here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=False,
# DELETE is in the list because the browser really does use it —
# `DELETE /documents/{filename}` backs the report-removal button. Omitting it
# would have broken that silently, visible only as a CORS error in the console.
# X-Service-Key is deliberately NOT allowed: those routes are called server-to-
# server by Convex, where CORS does not apply, so a browser has no business
# sending that header.
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

    Refreshed at most every five minutes. /health is polled once a minute by the
    supervisor, and a billing lookup on every poll would be both wasteful and a
    new way for the health check to hang.
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
        # Never let billing telemetry break liveness. The key is not in the
        # message — only the exception type, which is all that is diagnostic.
        print(f"[health] could not read OpenRouter balance: {type(error).__name__}")
        return None

    _balance_cache.update({"at": now, "value": value})
    return value


def require_user(authorization: str, service_key: str = "") -> str:
    """Verified user id, or 401 when `config.REQUIRE_AUTH` is on.

    Guards the endpoints that spend money or CPU. `verify_token` deliberately
    returns "" rather than raising, so that private-data lookups degrade to
    "nothing found" instead of erroring; that is right for retrieval but wrong
    for admission, hence this second, stricter gate on top of it.

    A valid service key is accepted as an alternative credential. It identifies
    no user — the return value stays "" — so it unlocks admission without
    unlocking anybody's private data. `/jobs/run` already performs the same
    consultation on that credential, so trusting it here grants nothing new, and
    it gives the test suite a way to exercise /consult without minting a login.
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
    `kid` — and publishes a JWKS whose single key has no `kid` either. PyJWT's
    `get_signing_key_from_jwt()` matches on `kid`, so it never found the key and
    raised, and `verify_token` swallowed that into "" — the value it also returns
    for genuinely anonymous callers.

    The effect was silent and long-lived: every request was treated as anonymous,
    so conversation memory and uploaded reports were never actually retrieved for
    the person who owned them. Nothing looked broken, because the consultation
    still answered — just without any of the caller's own context. Requiring auth
    on /consult is what finally turned it into a visible 401.

    So: use `kid` when a token has one (a future Convex release may add it), and
    otherwise fall back to the sole signing key in the set.

    The client is cached because `PyJWKClient` fetches the JWKS over the network;
    building a new one per request re-fetched it on every single call.
    """
    global _jwk_client
    import jwt  # PyJWT

    if _jwk_client is None:
        _jwk_client = jwt.PyJWKClient(
            f"{config.CONVEX_SITE_URL}/.well-known/jwks.json",
            cache_keys=True,
        )

    if jwt.get_unverified_header(token).get("kid"):
        return _jwk_client.get_signing_key_from_jwt(token).key

    signing_keys = [k for k in _jwk_client.get_jwk_set().keys if k.key_type == "RSA"]
    if len(signing_keys) != 1:
        # Ambiguous without a `kid`; refuse rather than guess which key to trust.
        raise ValueError(f"expected exactly one RSA signing key, found {len(signing_keys)}")
    return signing_keys[0].key


def verify_token(token: str) -> str:
    """Return the Convex user id for a login token, or "" if it is not valid.

    This is the ONLY thing allowed to establish who is asking. The browser sends
    a `principal` blob too, but that is self-asserted and must never be trusted
    for anything that selects private data - a client could simply claim to be
    somebody else and be handed their medical reports.

    Lifted out of GET /whoami, which had this logic inline and was the only route
    using it. Nothing about the verification changed; it just needed to be
    callable from /consult and /upload as well.
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
        # Deliberately not a 401. An anonymous or expired session should still be
        # able to ask about turmeric; it just does not get a private document
        # library. Failing the whole request would turn a logged-out tab into a
        # broken app.
        print(f"[auth] token rejected: {error}")
        return ""


async def _post_webhook(body: dict) -> None:
    url = f"{config.CONVEX_SITE_URL}/backend/webhook"
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(url, headers={"x-webhook-secret": config.WEBHOOK_SECRET}, json=body)


# ======================================================================
#  A) THE WEB APP (for using the product directly in your browser)
# ======================================================================
@app.get("/", response_class=HTMLResponse)
def home():
    """Say what this host is. Deliberately NOT the legacy chat page any more.

    This used to serve `frontend/index.html`, a complete working chat UI. That
    was fine while the backend was a localhost development server; it stopped
    being fine when the same process was published at ayur-api.namahos.com,
    because the page and its `POST /chat` endpoint were then a fully functional
    anonymous chatbot on the public internet, spending our AI balance.

    `/chat` now requires a signed-in caller (see below), so this page could no
    longer work regardless. Serving it anyway would put a product-branded chat
    box on a public URL that errors on every message — worse than not serving it.

    The file is left in the repo: it is still the quickest way to exercise the
    legacy flow locally, and `python -m http.server` in that folder will open it.
    """
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<title>Ayurveda API</title>"
        "<h1>Ayurveda &amp; Yoga API</h1>"
        "<p>This host serves the API only. The app is at "
        "<a href='https://ayur.namahos.com'>ayur.namahos.com</a>.</p>"
    )


@app.post("/chat")
async def chat(
    request: Request,
    authorization: str = Header(default=""),
    x_service_key: str = Header(default=""),
):
    """
    Run ONE turn of the LEGACY Ayurveda/Yoga flow and return the result directly.
    Kept for `frontend/index.html`; the dashboard now uses POST /consult.

    SIGNED-IN CALLERS ONLY — and that was missing, which made this the one hole
    in an otherwise closed backend.

    Every other AI route already called `require_user`. This one did not, and
    the backend is published at ayur-api.namahos.com, so it was an open,
    anonymous, internet-reachable endpoint onto the model chain. Verified from
    the public hostname with no credentials at all:

        POST https://ayur-api.namahos.com/chat {"problem":"...","followups":99}
        -> 200, a full generated plan, billed to our OpenRouter balance

    Anyone who found the URL could spend the AI budget, which is precisely the
    "credit khatam" failure this project has been working to make impossible —
    and no chain ordering or fallback can defend against it, because the
    requests are legitimate as far as the model is concerned.

    Nothing in the product calls this route (the dashboard uses /consult), so
    requiring a caller to be signed in costs no working functionality.

    `run_consult` is fully synchronous (LangGraph -> LangChain -> blocking HTTP to
    Groq, plus blocking Chroma/sentence-transformers), so it must be pushed to a
    worker thread. Calling it inline froze the whole event loop for the duration
    of every consult, stalling all other requests.
    """
    require_user(authorization, x_service_key)

    data = await request.json()
    problem = data.get("problem", "")
    profile = data.get("profile", "")
    history = data.get("history", "")
    followups = int(data.get("followups", 0))
    document_text = data.get("document_text", "")

    if document_text:
        profile = f"{profile}\n\nInfo from uploaded documents:\n{document_text}"

    result = await asyncio.to_thread(run_consult, problem, profile, history, followups)
    return result  # {kind, answer, knowledge_used}


def _resolve_bot(data: dict) -> BotConfig:
    """Which bot is this request for? Unknown ids are a 400, never a fallback.

    Called BEFORE the turn starts, so an unregistered bot_id never reaches a
    retriever, an LLM or the vector store. Falling back to the default bot here
    would silently answer out of Ayurveda's corpus for a caller that explicitly
    asked for something else — the exact cross-bot leak the Bot Manager exists to
    prevent, and one that no happy-path test would ever catch.

    An ABSENT bot_id is still accepted and means the default bot. The frontend
    now sends one, so this remains only for clients still running an older
    bundle — a browser tab open across the deploy, or a cached script. Rejecting
    absence immediately would 400 those users mid-conversation for no fault of
    their own, and this site is expected to stay up.

    It is logged rather than silent, so the transition is observable: once this
    warning stops appearing in production, absence can safely become a 400 too.
    A default is a silent fallback wearing a different hat, and it is only
    tolerable while it is temporary and visible.
    """
    if not data.get("bot_id"):
        print("[consult] request without bot_id; defaulting to the ayurveda bot")
    try:
        return get_bot(data.get("bot_id"))
    except UnknownBotError:
        # Naming the known ids keeps the error actionable. They are not secret —
        # the frontend sends them in plain request bodies.
        raise HTTPException(
            status_code=400,
            detail=f"unknown bot_id: {data.get('bot_id')!r}; known: {sorted(BOTS)}",
        )


@app.post("/consult")
async def consult(
    request: Request,
    authorization: str = Header(default=""),
    x_service_key: str = Header(default=""),
):
    """
    Card-driven consultation — one turn.

    Request : {problem, context, answers, freeText, profile, principal?}
    Response: {kind: "intake"|"answer"|"escalation", condition, message,
               intake?, answer?, context, sources}

    STATELESS by design: the client echoes back the `context` it was given, and
    that context carries INTAKE state only. Conversation history, medical profile
    and uploaded reports are server-owned and will be fetched by the retrieval
    layer using the caller's identity — never accepted from the browser, which
    would let a client assert its own medical history to the model.

    `principal` is threaded through now (unused) so switching those retrievers on
    later needs no client change.
    """
    try:
        data = await request.json()
    except (UnicodeDecodeError, ValueError) as error:
        # A body that isn't valid UTF-8 JSON is the caller's mistake, not ours —
        # report it as such instead of surfacing a 500 with a stack trace.
        raise HTTPException(status_code=400, detail=f"invalid JSON body: {error}")

    # Identity comes from the verified token and nowhere else. Whatever the client
    # put in `principal` is passed along for logging, but `user_id` - the field
    # the retrievers filter private data on - is overwritten from the JWT, so a
    # forged principal buys nothing.
    token = _bearer(authorization)
    principal = {**(data.get("principal") or {}), "token": token}
    principal["user_id"] = require_user(authorization, x_service_key)

    # After auth, before any work: an unauthenticated caller learns nothing about
    # which bots exist, and an unknown bot_id costs one dict lookup rather than a
    # retrieval pass.
    bot = _resolve_bot(data)

    result = await run_consult_turn(
        problem=data.get("problem", ""),
        raw_context=data.get("context"),
        answers=data.get("answers"),
        free_text=data.get("freeText"),
        profile=data.get("profile", ""),
        principal=principal,
        bot=bot,
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

    A sibling of `/consult`, not a replacement. `/consult` is untouched, so every
    existing caller keeps working and this can be turned off by simply not
    calling it.

    Two event types:
      token: {"text": "..."}   a piece of a prose answer, as the model writes it
      done:  <ConsultResult>   the identical JSON /consult would have returned

    `done` always arrives, and it is what the client stores. The tokens are a
    preview: a client that ignored them entirely would still end up with exactly
    the right transcript. That is deliberate — the authoritative answer must not
    depend on the reader having received every chunk.

    Intake turns emit no tokens at all. They are question cards, and half a form
    is not a form.
    """
    try:
        data = await request.json()
    except (UnicodeDecodeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=f"invalid JSON body: {error}")

    token = _bearer(authorization)
    principal = {**(data.get("principal") or {}), "token": token}
    principal["user_id"] = require_user(authorization, x_service_key)

    # Resolved here rather than inside `run()` so an unknown bot_id is a real
    # HTTP 400 the client can act on, not an `error` frame arriving mid-stream
    # after the connection has already been accepted.
    bot = _resolve_bot(data)

    # The turn runs in a worker thread and pushes pieces onto this queue; the
    # response generator drains it. A queue rather than a direct yield because
    # `run_turn` calls the writer several frames deep and cannot itself be a
    # generator without changing its contract for every other caller.
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
                profile=data.get("profile", ""),
                principal=principal,
                on_token=on_token,
                bot=bot,
                conversation_id=data.get("conversationId"),
            )
            await queue.put(("done", result.model_dump()))
        except Exception as error:  # noqa: BLE001
            print(f"[consult] stream turn failed: {error}")
            await queue.put(("error", str(error)))
        finally:
            await queue.put(None)

    async def events():
        task = asyncio.create_task(run())
        try:
            while True:
                item = await queue.get()
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
        headers={
            "Cache-Control": "no-cache",
            # Cloudflare and any intermediate proxy will happily buffer a
            # response and deliver it in one piece, which would defeat the whole
            # point. This is the header they honour.
            "X-Accel-Buffering": "no",
        },
    )


MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@app.post("/upload")
async def upload(
    file: UploadFile = File(...),
    authorization: str = Header(default=""),
):
    """Read a report and add it to the caller's private document library.

    Extraction and indexing in one request, on purpose: two round trips would
    mean the browser holds extracted medical text in memory between them for no
    benefit.

    Requires a signed-in caller (see `config.REQUIRE_AUTH`). It previously
    accepted anonymous uploads and simply indexed nothing, which was reasonable
    on localhost; published to the internet it is an open door to 20 MB of OCR
    per request. The check runs BEFORE the body is read so a rejected caller
    never gets to spend that.
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
        # extract_text is blocking (pypdf, and Tesseract shelling out for OCR),
        # so it must not run on the event loop.
        text = await asyncio.to_thread(extract_text, tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    indexed = 0
    if user_id and text:
        from src import user_documents

        indexed = await asyncio.to_thread(
            user_documents.index_document, user_id, filename, text
        )

    # The extracted text is NOT returned any more. The browser has no use for it
    # - the retriever reads it server-side - and sending medical text back over
    # the wire only widens where it can end up.
    return {"filename": filename, "chars": len(text or ""), "indexed": indexed}


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

    Deleting the file without deleting its chunks would leave the report quietly
    answering questions after the user believed it was gone - which is worse than
    never having offered deletion.
    """
    user_id = verify_token(_bearer(authorization))
    if not user_id:
        raise HTTPException(status_code=401, detail="login required")

    from src import user_documents

    await asyncio.to_thread(user_documents.remove_document, user_id, filename)
    return {"ok": True, "filename": filename}


@app.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    authorization: str = Header(default=""),
):
    """Turn a recorded clip into text, in whatever language was actually spoken.

    Returns the detected language alongside the transcript so the caller can set
    the conversation language from it - somebody who speaks Hindi should not have
    to also ask for a Hindi reply.

    Signed-in callers only: speech-to-text runs against the model chain, so an
    open endpoint here spends the same free-tier quota the consultations need.
    """
    require_user(authorization)
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="clip too large")
    if not raw:
        return {"text": "", "language": ""}

    from src.llm import transcribe

    mime = file.content_type or "audio/webm"
    try:
        return await asyncio.to_thread(transcribe, raw, mime)
    except Exception as error:  # noqa: BLE001
        print(f"[transcribe] failed: {error}")
        raise HTTPException(status_code=502, detail="transcription failed")


@app.post("/speak")
async def speak_text(request: Request, authorization: str = Header(default="")):
    """Read an answer aloud. Called only when the user presses the speaker icon."""
    require_user(authorization)
    if not config.TTS_ENABLED:
        # No free model on OpenRouter emits speech, so this is off by default
        # rather than quietly billing a key that is meant to cost nothing.
        raise HTTPException(
            status_code=503,
            detail="Reading aloud needs a paid voice model. Set TTS_MODEL in .env.",
        )

    data = await request.json()
    text = (data.get("text") or "").strip()
    if not text:
        return {"audio": "", "format": "wav"}

    from src.llm import speak

    try:
        return await asyncio.to_thread(speak, text, data.get("voice", ""))
    except Exception as error:  # noqa: BLE001
        print(f"[speak] failed: {error}")
        raise HTTPException(status_code=502, detail="speech generation failed")


# ======================================================================
#  B) CONVEX INTEGRATION (for the dashboard / template)
# ======================================================================
@app.get("/health")
def health():
    """Liveness, plus how much AI credit is left.

    The balance is here because "the AI stopped working" was, every time, a
    budget that had quietly run out — and the first warning was always a user
    seeing an error. A number on the health check turns that into something
    anyone can watch days ahead.

    Cached and best-effort: this endpoint is hit every minute by the supervisor
    and must never be slower or less reliable than the thing it reports on, so a
    failed balance lookup is simply omitted rather than allowed to fail /health.
    """
    # `provider` reported config.LLM_PROVIDER, which is only the DEFAULT for
    # chain entries that carry no "provider:" prefix of their own. Every entry in
    # the live chain names its provider, so the field said "groq" while every
    # request in fact went to OpenRouter. Harmless until the one moment it
    # matters -- reading /health during an outage and chasing the wrong provider.
    #
    # Report what the next request will actually use: the head of the healthy
    # chain, which is also the thing that changes when a model falls into
    # cooldown, so this doubles as a view of the fallback state.
    from src.llm import _available_models, split_provider

    chain = _available_models("")
    head = chain[0] if chain else ""
    provider, model = split_provider(head) if head else (config.LLM_PROVIDER, "")

    payload = {
        "ok": True,
        "llm_ready": config.is_llm_ready(),
        "provider": provider,
        "model": model,
        # How many of the configured models are not currently cooling down. A
        # drop here is the earliest visible sign of quota trouble.
        "models_available": len(chain),
    }
    balance = _openrouter_balance()
    if balance is not None:
        payload["ai_credit_usd"] = balance
        # A threshold rather than a raw number alone, so it is actionable at a
        # glance instead of needing arithmetic.
        payload["ai_credit_low"] = balance < 1.0
    return payload


@app.get("/whoami")
def whoami(authorization: str = Header(default="")):
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    sub = verify_token(token)
    if not sub:
        # This route is a diagnostic - "is my login working?" - so unlike
        # /consult it should say no rather than degrade quietly.
        raise HTTPException(status_code=401, detail="invalid token")
    return {"verified": True, "sub": sub}


@app.get("/debug/retrieve")
async def debug_retrieve(
    q: str = "",
    user_id: str = "",
    x_service_key: str = Header(default=""),
):
    """Why did THIS query retrieve THAT note? Developers and admins only.

    Two gates, because the blast radius of getting this wrong is the corpus and
    another person's report text:

      1. the service key — the same guard as /extract, so no browser can reach it
      2. config.DEBUG_RAG — off unless a deployment deliberately turns it on

    Returns 404 rather than 403 when disabled: a disabled debug route should not
    advertise that it exists.

    The DEBUG_RAG gate is checked FIRST, deliberately. With the key check first,
    an anonymous request got 401 while a nonexistent path got 404 — so anyone
    could tell the route was there, on a public hostname, just by the status
    code. Checking the flag first makes a disabled route indistinguishable from
    one that was never built.
    """
    if not config.DEBUG_RAG:
        raise HTTPException(status_code=404, detail="not found")
    _check_service_key(x_service_key)
    if not q.strip():
        raise HTTPException(status_code=400, detail="q is required")

    from src.debug import pipeline_trace

    # user_id is honoured only because the caller already proved it holds the
    # service key; it is never taken from an end user.
    return await pipeline_trace(q, user_id or None)


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
    _check_service_key(x_service_key)
    body = await request.json()
    job_id = body.get("jobId")
    data = body.get("input", {}) or {}
    problem = data.get("problem", "")
    profile = data.get("profile", "")
    history = data.get("history", "")
    followups = int(data.get("followups", 0))
    document_text = data.get("document_text", "")
    if document_text:
        profile = f"{profile}\n\nInfo from uploaded documents:\n{document_text}"

    try:
        # Same blocking-call reasoning as /chat above.
        result = await asyncio.to_thread(run_consult, problem, profile, history, followups)
    except Exception as e:
        await _post_webhook({"type": "job.result", "jobId": job_id, "result": None, "error": str(e)})
        return {"accepted": True, "jobId": job_id}

    await _post_webhook({
        "type": "job.result",
        "jobId": job_id,
        "result": {
            "kind": result["kind"],
            "answer": result["answer"],
            "knowledge_used": result["knowledge_used"],
        },
    })
    return {"accepted": True, "jobId": job_id}


if __name__ == "__main__":
    import uvicorn
    # host comes from config (default 127.0.0.1). It used to be a hard-coded
    # "0.0.0.0", which published this API to the whole LAN.
    #
    # reload is off unless RELOAD=1. It was hard-coded on, so production paid for
    # a file watcher over `.venv` and a second process it never needed. Set
    # RELOAD=1 in backend-python/.env while developing.
    uvicorn.run("server:app", host=config.HOST, port=config.PORT, reload=config.RELOAD)
