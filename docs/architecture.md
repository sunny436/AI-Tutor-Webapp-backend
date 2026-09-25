# Architecture

## One repository, one release

The whole application is one repository, and every commit is one complete, consistent version of it:

| Folder | What | Tooling |
|---|---|---|
| `frontend/` | Next.js 14 web app + its server-side proxy (BFF), a Bun + Turborepo workspace (`apps/app`, `packages/ui`) | Bun 1.3.14, Biome, bun test, Playwright |
| `backend/` | FastAPI chat API, SQLAlchemy async + Alembic, LangGraph/LangChain RAG | Python 3.12 venv, ruff, pytest |
| `docs/openapi.json` | The API contract: generated from the backend, tested by the frontend (`routes.test.ts`) | `bun run contract` |
| `deploy/` | One release-based deployment for both ([deployment.md](deployment.md), [rollback.md](rollback.md)) | bash, systemd |

They stay two processes (a Node server and a Python server) because they are different runtimes with
a narrow, tested HTTP contract between them, but they are **built, tested, deployed and rolled back
together**: production runs both from one release directory, `/opt/aichat/current -> releases/<commit>`.

## Components

```
Browser ──► Web app (Next.js, frontend/; 127.0.0.1:3000)
               │  server-side proxy; holds the session token in an httpOnly cookie
               │  Authorization: Bearer <token>, X-Request-ID, X-Forwarded-For
               ▼
            Chat API (FastAPI, backend/; 127.0.0.1:4000 dev · 4100 prod)
               ├─ auth            users, sessions, email codes, throttling
               ├─ conversations   list/create/rename/delete, message history
               ├─ chat            ChatService + SSE + stop + regenerate + feedback + quotas
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
flag is authoritative).

## Data model

```
users ─┬─ user_settings        preferences (JSONB, ≤ 4 KB)
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
   load the conversation from PostgreSQL and run the LangGraph graph
   (`receive_query → retrieve_context → assemble_context → generate_answer`, see [rag.md](rag.md));
   push `token` events; stop on cancel (cancelling the graph step cancels the LLM stream).
3. **Finalize**: write content, status and metadata (including the internal retrieval summary);
   update the usage event; emit `done` or `error`.

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
| Sessions can be revoked only all at once (`revoke-others`) | people manage devices one by one | list and revoke single sessions (rows already keep user agent, IP and last use) |
| The theme is stored in the browser (next-themes) | a preference that does not follow the user | move it to `/v1/me/settings` the next time preferences are worked on |
| Sign-in throttling counts per IP | carrier NAT puts many phones behind one address | review the limits against real mobile traffic |
| Logs carry request and user ids, but not the client; no metrics or tracing | web and app failures cannot be told apart | log a client identifier; add metrics once there is more than one client |
| Nothing is stored outside PostgreSQL; there are no uploads | homework photos and PDFs | server-side storage behind the API, never on one device |

Already client-neutral: bearer tokens returned in the response body; 30-day sliding sessions, one
per device; email flows by 6-digit code, with no web links; a non-streaming `POST /v1/chat`
alongside SSE; opaque pagination cursors; ISO-8601 timestamps; errors identified by `code`; another
user's resources indistinguishable from missing ones.

## Extension points (for the AI tutor phase)

| Need | Seam | Change required |
|---|---|---|
| Different instructions/model per feature | `app/chat/assistant.py::resolve_assistant_config` | return a different `AssistantConfig` |
| Retrieval filters (source, subject, project, any metadata) | `AssistantConfig.retrieval` (`RetrievalOptions`) | set options in `resolve_assistant_config`; no RAG change |
| A different retriever | `retriever_factory` in `app/main.py` (any LangChain `BaseRetriever`) | swap the factory |
| Query rewriting / reranking / answer checks | new nodes in `app/rag/graph.py` | insert on an existing edge |
| Citations in the UI | sources already stored in order in `messages.metadata.retrieval.sources` | add to the public metadata allowlist + an SSE event; existing clients ignore unknown events |
| More LLM providers / routing | `app/llm/base.py::LLMProvider`, `FallbackProvider` | new provider class; compose |
| Learner profile, subjects, progress | new tables in a new Alembic migration, keyed by `users.id` | additive |
| Project/workspace-scoped knowledge | `AccessScope` + a `project_id` column | new migration; retriever and graph unchanged |

### Knowledge base and vectors

Implemented: PostgreSQL + pgvector hold sources, documents and chunks with `vector(1536)` embeddings
(HNSW index), ingested by `scripts/ingest_documents.py` and searched by a LangChain retriever inside
the LangGraph turn graph. Details, access model, failure behaviour and verification status:
[rag.md](rag.md). No other database or vector store is used.
