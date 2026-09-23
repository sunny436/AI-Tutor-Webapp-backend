# Architecture

## Components

```
Browser ──► Web app (Next.js, separate repository)
               │  server-side proxy; holds the session token in an httpOnly cookie
               │  Authorization: Bearer <token>, X-Request-ID, X-Forwarded-For
               ▼
            Chat API (FastAPI, 127.0.0.1:4000)
               ├─ auth            users, sessions, email codes, throttling
               ├─ conversations   list/create/rename/delete, message history
               ├─ chat            ChatService + SSE + stop + regenerate + feedback + quotas
               ├─ context         ContextProvider pipeline (empty in the generic chatbot)
               └─ llm             LLMProvider protocol → OpenAI-compatible providers
               ▼
            PostgreSQL 16 + pgvector (127.0.0.1:5432) — the single source of truth
            SMTP (verification and reset codes)      LLM APIs: Ollima (primary), OpenRouter (fallback)
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
   build the prompt from PostgreSQL (system prompt, optional context, history window), stream from
   the LLM, push `token` events, stop on cancel.
3. **Finalize**: write content, status and metadata; update the usage event; emit `done` or `error`.

The browser sends only `{conversationId, message}`; it never writes messages or sends history.

## Extension points (for the AI tutor phase)

| Need | Seam | Change required |
|---|---|---|
| Different instructions/model per feature | `app/chat/assistant.py::resolve_assistant_config` | return a different `AssistantConfig` |
| Retrieval (curriculum knowledge graph, document search) | `app/context/base.py::ContextProvider` | implement `provide()`, return it from the config |
| Citations in the UI | `ContextBlock.source` + `messages.metadata` + a new SSE event | additive; existing clients ignore unknown events |
| More LLM providers / routing | `app/llm/base.py::LLMProvider`, `FallbackProvider` | new provider class; compose |
| Learner profile, subjects, progress | new tables in a new Alembic migration, keyed by `users.id` | additive |
| Embeddings | pgvector (enabled by migration 0001) | see below |

### Vector data (pgvector)

The `vector` extension is enabled and verified (HNSW index + cosine search in `tests/test_foundation.py`).
No vector tables exist yet because the embedding model and dimension are not chosen. The intended shape:

```sql
knowledge_sources (id, name, kind, metadata jsonb, created_at)
documents         (id, source_id → knowledge_sources, title, uri, metadata jsonb, created_at)
document_chunks   (id, document_id → documents, ordinal, content text, metadata jsonb,
                   embedding vector(<dim>), created_at)
CREATE INDEX ON document_chunks USING hnsw (embedding vector_cosine_ops);
```

A retrieval provider embeds the query (an `EmbeddingProvider` alongside `LLMProvider`), queries
`document_chunks` with `ORDER BY embedding <=> :q LIMIT k` (plus metadata filters), and returns
`ContextBlock`s. No other database or vector store is introduced.
