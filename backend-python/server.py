"""
server.py
---------
The Python AI backend (FastAPI). It does two jobs:

A) Serves a friendly WEB APP (the chat UI) at http://localhost:4000
   - GET  /            -> the chat page (frontend/index.html)
   - POST /chat        -> run one turn of the Ayurveda/Yoga flow, return the answer
   - POST /upload      -> read text from an uploaded report (PDF/image)

B) Talks to the Convex template (the "bring your own backend" paths):
   - POST /jobs/run    -> Convex sends a consult job; we answer and webhook back
   - POST /extract     -> read a report (protected by the shared service key)
   - GET  /whoami      -> verify a Convex login token (JWT) via JWKS
   - GET  /health      -> simple "is it alive?" check
"""

import asyncio
import base64
import tempfile
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Header, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

import config
from src.consult import run_turn as run_consult_turn
from src.graph import run_consult
from src.documents import extract_text

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_FILE = BASE_DIR / "frontend" / "index.html"

app = FastAPI(title="Ayurveda & Yoga AI Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
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

        jwks_url = f"{config.CONVEX_SITE_URL}/.well-known/jwks.json"
        signing_key = jwt.PyJWKClient(jwks_url).get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
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
    """Serve the chat web page."""
    if FRONTEND_FILE.exists():
        return HTMLResponse(FRONTEND_FILE.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Frontend not found.</h1>")


@app.post("/chat")
async def chat(request: Request):
    """
    Run ONE turn of the LEGACY Ayurveda/Yoga flow and return the result directly.
    Kept for `frontend/index.html`; the dashboard now uses POST /consult.

    `run_consult` is fully synchronous (LangGraph -> LangChain -> blocking HTTP to
    Groq, plus blocking Chroma/sentence-transformers), so it must be pushed to a
    worker thread. Calling it inline froze the whole event loop for the duration
    of every consult, stalling all other requests.
    """
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


@app.post("/consult")
async def consult(request: Request, authorization: str = Header(default="")):
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
    principal["user_id"] = verify_token(token)

    result = await run_consult_turn(
        problem=data.get("problem", ""),
        raw_context=data.get("context"),
        answers=data.get("answers"),
        free_text=data.get("freeText"),
        profile=data.get("profile", ""),
        principal=principal,
    )
    return result.model_dump()


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

    Logged out, this still extracts and returns the text but indexes nothing -
    there is no verified user to store it against. `indexed: 0` in the response
    is how the UI knows to say so rather than claiming success.
    """
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

    user_id = verify_token(_bearer(authorization))
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
    """
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
async def speak_text(request: Request):
    """Read an answer aloud. Called only when the user presses the speaker icon."""
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
    return {"ok": True, "llm_ready": config.is_llm_ready(), "provider": config.LLM_PROVIDER}


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
    """
    _check_service_key(x_service_key)
    if not config.DEBUG_RAG:
        raise HTTPException(status_code=404, detail="not found")
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
    uvicorn.run("server:app", host="0.0.0.0", port=config.PORT, reload=True)
