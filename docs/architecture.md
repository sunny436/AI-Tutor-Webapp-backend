# Architecture

## One repository, one release

The whole application is one repository, and every commit is one complete, consistent version of it:

| Folder | What | Tooling |
|---|---|---|
| `frontend/` | Next.js 15 web app + its server-side proxy (BFF), a Bun + Turborepo workspace (`apps/app`, `packages/ui`) | Bun 1.3.14, Biome, bun test, Playwright |
| `backend/` | FastAPI chat API, SQLAlchemy async + Alembic, LangGraph/LangChain RAG | Python 3.12 venv, ruff, pytest |
| `docs/openapi.json` | The API contract: generated from the backend, tested by the frontend (`routes.test.ts`) | `bun run contract` |
| `deploy/` | One deploy for both: Git push to production, only the changed part rebuilt ([deployment.md](deployment.md), [rollback.md](rollback.md)) | bash, systemd |

They stay two processes (a Node server and a Python server) because they are different runtimes with
a narrow, tested HTTP contract between them, but they are **tested together and deployed from the
same commit**: production runs both from one checkout, `/opt/aichat/app`, and a deploy restarts only
the one a commit changes.

## Components

```
Browser ──► Web app (Next.js, frontend/; 127.0.0.1:3000)
               │  server-side proxy; holds the session token in an httpOnly cookie
               │  Authorization: Bearer <token>, X-Request-ID, X-Forwarded-For
               ▼
            Chat API (FastAPI, backend/; 127.0.0.1:4000 dev · 4100 prod)
               ├─ auth            users, sessions, email codes, throttling, profile photo, devices
               ├─ learning        academic catalog, learner profile, subjects, learning preferences,
               │                  and what they add to the tutor's instructions (app/learning/tutor.py)
               ├─ progress        active time in PadhAI (deduplicated minutes), questions, streaks, goals, and
               │                  the practice record read from the question bank's ledger (app/progress/practice.py)
               ├─ notifications   preferences, the email outbox, security alerts, reminders, unsubscribe
               ├─ support         support requests (forwarded through the outbox)
               ├─ conversations   list/create/rename/delete, message history
               ├─ chat            ChatService + SSE + stop + regenerate + feedback + quotas
               ├─ intents         what a message asks for: Ollalink's classifier, 46 intents (INTENT_ROUTER)
               ├─ rag             LangGraph turn graph + LangChain retriever over pgvector (docs/rag.md)
               └─ llm             LLMProvider protocol → OpenAI-compatible providers
               ▼
            PostgreSQL 16 + pgvector (127.0.0.1:5432) — the single source of truth
            SMTP or Ollastack mail (codes)           LLM APIs: Ollima (primary), OpenRouter (fallback)
                                                     Embeddings API: OpenAI-compatible (text-embedding-3-small)
```

The API is never published to the internet; only the web app is, through a Cloudflare Tunnel. The browser
only talks to the web app's own origin (`/api/v1/*`); the proxy (`frontend/apps/app/src/lib/server/proxy-core.ts`)
forwards an allowlist of routes with the session attached, checks Origin on mutations, streams SSE
unbuffered and aborts upstream when the browser leaves ([frontend-integration.md](frontend-integration.md)). Nothing is stored
outside PostgreSQL: no local files, no vector store on disk, no authoritative in-memory
state (the in-process generation registry only speeds up stopping a reply; the database
flag is authoritative). Students' uploaded files are PostgreSQL rows too (`user_file_blobs`,
1 MiB each): deleted with the file or the account by foreign keys, backed up with everything else.

**Files** (`app/files`): an upload is stored and then read by one background worker in the API
process (a PostgreSQL lease per file, so a restart or deploy loses nothing). Untrusted bytes are
parsed only by a separate process, `python -m app.files.extract`, which in production is a
sandboxed systemd transient unit (`aichat-extract-*`: a throwaway user, no network, no secrets,
read-only files, 512 MB and 300 s); the API process never loads a parser. Its text goes through
LangChain (`Document` → `RecursiveCharacterTextSplitter.split_documents` → `Embeddings`) into
`file_chunks` (pgvector, 1536). A chat turn reads only the files attached to its conversation
(owned, ready), exactly and per file, with the attached passages inside the student's message
([rag.md](rag.md), "Files the student attached").

## Data model

```
users ─┬─ user_settings        preferences (JSONB, ≤ 4 KB)
       ├─ user_avatars         the profile photo: a re-encoded 256 px WebP, ≤ 64 KB
       ├─ learner_profiles     class, board, medium, goals, weak topics (catalog codes + short text), versioned
       ├─ learner_subjects     ordered subject list with priority / needs-improvement flags
       ├─ learning_preferences how the student wants to be taught; typed columns, each `auto` by default
       ├─ activity_days        per local day: active seconds, questions, the last credited UTC minute
       ├─ notification_preferences   reminders (off by default) and sign-in alerts (on)
       ├─ email_outbox         emails for the worker to send, at most once; redacted after 7 days
       ├─ support_requests     plain-text questions and reports, kept until the account is deleted
       ├─ auth_sessions        SHA-256 of a random 256-bit token; 30-day sliding expiry
       ├─ conversations ── messages ── message_feedback
       └─ usage_events         one per generation: provider, model, tokens, latency, outcome
email_codes                    HMAC of 6-digit codes, 15-minute expiry, 5 attempts
auth_attempts                  throttling counters (hashed email/IP)
knowledge_sources ── documents ── document_chunks   RAG knowledge base; embedding vector(1536); sources are
                                                    global (owner NULL) or private to one user
```

`messages.status`: `complete` · `streaming` (being generated) · `cancelled` (stopped; partial text kept) ·
`error` (failed; partial text kept) · `superseded` (replaced by a regeneration; hidden, kept for feedback analysis).

`conversations.metadata` and `messages.metadata` (JSONB) carry per-feature data (future: mode,
citations) without schema changes.

## A chat turn

1. **Prepare** (request transaction): verify the session; load or create the conversation (owned by
   the user, row-locked); mark dead `streaming` rows as interrupted; refuse with 409 if a reply is
   still generating; enforce the per-user quota (from `usage_events`); insert the user message, an
   assistant placeholder (`streaming`) and a usage event; commit.
2. **Generate** (independent asyncio task, so the result is persisted even if the client leaves):
   load the conversation from PostgreSQL; with `INTENT_ROUTER` on, read what the new message asks for
   (`app/intents`: up to two short classification requests to Ollalink, the group and then the intent
   within it, capped together by `INTENT_ROUTER_TIMEOUT_S`, never retried, never failing the turn) and
   rebuild the prompt with it, while the graph's first two steps (the knowledge search) already run
   (`graph.prefetch`; used only when the intent kept the search on); run the LangGraph graph
   (`receive_query → retrieve_context → assemble_context → generate_answer`, see [rag.md](rag.md));
   push `token` events; stop on cancel (cancelling the graph step cancels the LLM stream).
3. **Finalize**: write content, status and metadata (including the internal retrieval summary and the
   intent router's reading, `metadata.intent`); update the usage event; emit `done` or `error`.

The browser sends only `{conversationId, message}`; it never writes messages or sends history.

## Clients: web-first, not web-only

The web app is the first client of the API, not the platform. Everything a second client (iOS,
Android, tablet, desktop) would need already lives behind `/v1`: accounts and sessions, data,
validation, quotas, tutor configuration (`resolve_assistant_config`) and user preferences
(`/v1/me/settings`, `user_settings.preferences`). Rules live in the API's services and repositories
(`app/*/service.py`, `app/conversations/repository.py`); routers only translate HTTP. One exception is
left as it is, since it works and moving it gains nothing today: feedback is written directly in
`app/chat/router.py`. Clients follow the "Client obligations" in [api-contract.md](api-contract.md).

These assumptions come from having only a web client. None needs changing now; each must be
resolved before, and only when, a native client is started:

| Today | Why it matters for a native client | Needed first |
|---|---|---|
| The API listens on loopback and is reached only through the web app's BFF | a native app cannot use the BFF (its session is a cookie and it checks `Origin` on mutations) | publish the API itself (e.g. its own hostname through the tunnel), still `/v1` with bearer tokens |
| `TRUST_FORWARDED_FOR` takes the first `X-Forwarded-For` entry | safe only while the BFF is the sole caller; on a public API a client could set it and dodge per-IP throttling | take the client IP from `CF-Connecting-IP` (or the proxy's own entry) before publishing |
| Closing the stream stops the reply (`app/chat/streams.py`) | phones drop connections when backgrounded or switching networks | let a client opt out per request, or stop only on `POST …/cancel` |
| No idempotency key on `POST /v1/chat` and `/v1/chat/stream` | a send retried on a flaky network can create the message twice | accept an `Idempotency-Key` |
| The theme is stored in the browser (next-themes) | a preference that does not follow the user | move it to `/v1/me/settings` the next time preferences are worked on |
| Sign-in throttling counts per IP | carrier NAT puts many phones behind one address | review the limits against real mobile traffic |
| Logs carry request and user ids, but not the client; no metrics or tracing | web and app failures cannot be told apart | log a client identifier; add metrics once there is more than one client |
| Uploads are the profile photo (≤ 64 KB, `user_avatars`) and File Library files (≤ 100 MB per student, PostgreSQL `user_file_blobs`, under a 3 GB database ceiling) | many students' files outgrow one database's disk | object storage behind the same `/v1/files` API when the ceiling is reached; clients never see where bytes live |

Identity (2026-10-01): Better Auth runs inside the web app's server (`/api/auth/*`, no extra
service) on the same PostgreSQL: it signs people up (email first: a code proves the address, then a
password), in (password, email code, Google) and resets passwords, and owns the session's expiry
and cookie, plus two-step sign-in (an authenticator app and recovery codes, asked for at every way
in), the adaptive CAPTCHA (Cloudflare Turnstile) and the breached-password check. The API stays
the authority on every request: it finds the session by the SHA-256 of
its token (`auth_sessions.token_hash`, kept by a trigger), requires a verified address and
authorizes per user; sessions, devices, the email change and account deletion are still `/v1`.
Better Auth reaches the database as `aichat_auth`, a role limited to the identity tables, and calls
the API's loopback-only `/internal/auth/*` (shared token) to send codes and security notices. A
native client would sign in at `/api/auth` (with Better Auth's bearer plugin, not enabled today)
and call `/v1` with `Authorization: Bearer` exactly as now.

Already client-neutral: bearer tokens on `/v1`; 30-day sliding sessions, one per device; email
flows by 6-digit code, with no web links; a non-streaming `POST /v1/chat`
alongside SSE; opaque pagination cursors; ISO-8601 timestamps; errors identified by `code`; another
user's resources indistinguishable from missing ones.

## Extension points (for the AI tutor phase)

| Need | Seam | Change required |
|---|---|---|
| Different instructions/model per feature | `app/chat/assistant.py::resolve_assistant_config` | return a different `AssistantConfig` |
| Retrieval filters (source, subject, project, any metadata) | `AssistantConfig.retrieval` (`RetrievalOptions`) | set options in `resolve_assistant_config`; no RAG change |
| A different retriever | `retriever_factory` in `app/main.py` (any LangChain `BaseRetriever`) | swap the factory |
| Query rewriting / reranking / answer checks | new nodes in `app/rag/graph.py` | insert on an existing edge |
| Citations in the UI | done (2026-09-30): `metadata.citations` (public) from the numbered sources and files; the web app shows chips and a Sources list | a `citations` SSE event before the first token, if chips are wanted while streaming |
| More LLM providers / routing | `app/llm/base.py::LLMProvider`, `FallbackProvider` | new provider class; compose |
| Learner profile, subjects, progress | new tables in a new Alembic migration, keyed by `users.id` | additive |
| Project/workspace-scoped knowledge | `AccessScope` + a `project_id` column | new migration; retriever and graph unchanged |

### Knowledge base and vectors

Implemented: PostgreSQL + pgvector hold sources, documents and chunks with `vector(1536)` embeddings
(HNSW index), ingested by `scripts/ingest_documents.py` and searched by a LangChain retriever inside
the LangGraph turn graph. Details, access model, failure behaviour and verification status:
[rag.md](rag.md). No other database or vector store is used.
