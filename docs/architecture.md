# Architecture

## Components

```
Browser ──► Web app (Next.js, separate repository)
               │  server-side proxy; holds the session token in an httpOnly cookie
               │  Authorization: Bearer <token>, X-Request-ID, X-Forwarded-For
               ▼
            Chat API (FastAPI, 127.0.0.1:4000 dev · 4100 prod)
               ├─ auth            users, sessions, email codes, throttling
               ├─ conversations   list/create/rename/delete, message history
               ├─ chat            ChatService + SSE + stop + regenerate + feedback + quotas
               ├─ rag             LangGraph turn graph + LangChain retriever over pgvector (docs/rag.md)
               └─ llm             LLMProvider protocol → OpenAI-compatible providers
               ▼
            PostgreSQL 16 + pgvector (127.0.0.1:5432) — the single source of truth
            SMTP (verification and reset codes)      LLM APIs: Ollima (primary), OpenRouter (fallback)
                                                     Embeddings API: OpenAI-compatible (text-embedding-3-small)
```

The API is never published to the internet; only the web app is. Nothing is stored
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
