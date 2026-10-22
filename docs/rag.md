# Retrieval-augmented generation (RAG)

Native, domain-neutral RAG: **LangGraph** orchestrates each chat turn, **LangChain** provides the
document / embeddings / retriever / text-splitter abstractions, and **PostgreSQL + pgvector** is the
only store. No other vector database is used. The NCERT textbooks are the one external source: a separate
service, the NCERT Knowledge Service, called through its API only ("NCERT textbooks", below).

## Dependency direction

```
FastAPI route ─► ChatService ─► LangGraph graph ─► LangChain retriever ─► KnowledgeStore ─► PostgreSQL/pgvector
 (app/chat/router)  (app/chat/service)  (app/rag/graph)    (app/rag/retriever)   (app/rag/store)
                                          │
                                          └─► LLMProvider protocol (app/llm/base) ─► configured provider
```

- Routes never import retrieval code; ChatService imports only `app.rag.graph`; the graph imports no
  provider, store or embeddings module; the store knows nothing about LangChain/LangGraph.
- `app/main.py` is the composition root that wires concrete implementations.
- Enforced by `tests/test_architecture_guards.py` (AST import rules).

## The graph (`app/rag/graph.py`)

```
START → receive_query → retrieve_context → assemble_context → generate_answer → END
```

| Node | Does |
|---|---|
| `receive_query` | Takes the latest user message; decides whether retrieval is skipped (`disabled`, `not_requested`, `empty_query`, `embeddings_unconfigured`). `not_requested`: the turn's `AssistantConfig.retrieval` is None, for small talk that opens a chat ("hi", "thanks": `is_meaningful`; "why?" after a question is still searched) or an intent answered from the app's own records (`performance_analysis`, `study_schedule`; `app/intents`). |
| `retrieve_context` | If the caller can see no chunks for the configured embedding model → skip (`empty_knowledge_base`, no embedding call). Otherwise builds the retriever for this turn and calls it, bounded by `RAG_RETRIEVAL_TIMEOUT_S`. Any failure → status `failed` + reason; the turn continues without context. |
| `assemble_context` | Builds the LLM input under one character budget (below) and emits the retrieval summary. |
| `generate_answer` | Streams from the `LLMProvider`; emits `token` events; closes the provider stream on success, error or cancellation. |

Streaming: ChatService consumes `graph.astream(state, stream_mode="custom")` events
`retrieval` → `llm_started` → `token`… → `llm_finished`. Cancelling the consumer (stop button, client
disconnect) cancels the running node; nothing is generated afterwards. No retry policy: exactly one
LLM generation per turn (the provider fallback only switches before the first token).

Extension points (not implemented): query rewriting before `retrieve_context`, reranking after it,
answer validation after `generate_answer` — each is a new node on an existing edge.

## Schema (migration `0002_knowledge_base`)

| Table | Key columns |
|---|---|
| `knowledge_sources` | `name` (unique), `owner_user_id` (NULL = **global**, else **private** to that user) |
| `documents` | `source_id`, `uri` (unique per source), `title`, `content_hash`, `ingest_signature`, `metadata` |
| `document_chunks` | `document_id`, `source_id` (denormalised), `ordinal`, `content`, `metadata`, `embedding vector(1536)`, `embedding_model` |

Indexes on `document_chunks`: HNSW `embedding vector_cosine_ops`, btree `(source_id, embedding_model)`,
GIN `metadata jsonb_path_ops`, unique `(document_id, ordinal)`.

## Access model

- Every search takes an `AccessScope(user_id)` built from the **verified session**. Allowed sources =
  global sources + the caller's own private sources. `source_names` and `metadata_filter` can only
  narrow that set.
- Retrieval options come only from `resolve_assistant_config` (server side); chat requests cannot carry
  filters (unknown fields are rejected).
- **Global sources are visible to every signed-in user** — ingest only content suitable for all users.
  The ingestion CLI makes visibility an explicit choice (`--global` or `--owner-email`).
- Future project/workspace scoping: add a `project_id` (new migration) and extend `AccessScope`; the
  retriever and graph do not change.

## Ingestion (`app/rag/ingestion.py`, `scripts/ingest_documents.py`)

```
file ─► parse (.md/.markdown/.txt, UTF-8, ≤ RAG_MAX_DOCUMENT_BYTES, no NUL bytes, non-empty)
     ─► chunk (RecursiveCharacterTextSplitter: RAG_CHUNK_SIZE / RAG_CHUNK_OVERLAP)
     ─► embed ALL chunks (before any write)
     ─► one transaction: upsert document (row lock) → delete its chunks → insert new chunks
```

- **Versioning:** `ingest_signature` = sha256(content, title, metadata, embedding model, dimension,
  chunking). Unchanged signature → skipped, no embedding call. Any change → re-embedded and replaced.
- **Atomicity:** an embedding or database failure rolls back; the previous version stays intact.
- **Concurrency:** concurrent ingestion of the same `(source, uri)` serialises on the document row
  lock; the last commit wins and chunks of two versions never mix.
- Deleting: `--delete URI`. Files removed from a directory are not pruned automatically.
- The knowledge base takes `.md`/`.txt` only. Students' own PDF, Word, PowerPoint, Excel, CSV,
  text and image files go through the File Library instead (below).

```sh
python scripts/ingest_documents.py --source handbook --global docs/handbook/
python scripts/ingest_documents.py --source my-notes --owner-email me@example.com notes.md
python scripts/ingest_documents.py --source handbook --global --metadata lang=en docs/handbook/
python scripts/ingest_documents.py --source handbook --delete intro.md
```

## Embeddings (`app/rag/embeddings.py`)

- Behind LangChain's `Embeddings` interface; nothing else knows the provider.
- `openai_compatible`: `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` (default OpenAI
  `text-embedding-3-small`, requested at `dimensions=1536`), batched, timed, redacted typed errors.
- Every vector is checked for length 1536 and finite values. The app refuses to start if
  `EMBEDDING_DIMENSIONS` ≠ the column dimension.
- Chunks record `embedding_model`; retrieval searches only chunks of the configured model, so vector
  spaces never mix. Changing the model makes old chunks invisible (a startup warning counts them) until
  they are re-ingested — **nothing is re-embedded automatically**.
- Changing the dimension requires a new migration and a full re-ingest.
- `fake`: deterministic keyword hashing for tests/offline work. It measures shared vocabulary, **not
  meaning**; refused in production.

## Retrieval (`app/rag/retriever.py`, `app/rag/store.py`)

`PgVectorRetriever` (a LangChain `BaseRetriever`, async only): blank query → `[]`; embed the query;
resolve allowed source ids; then

```sql
WITH hits AS (
  SELECT id, document_id, source_id, ordinal, content, metadata, embedding <=> :q AS distance
  FROM document_chunks
  WHERE embedding_model = :model AND source_id IN (:allowed) [AND metadata @> :filter]
  ORDER BY embedding <=> :q LIMIT :k)
SELECT hits.*, documents.title, documents.uri, knowledge_sources.name ... ORDER BY distance
```

run with `SET LOCAL hnsw.iterative_scan = strict_order` and `hnsw.ef_search = RAG_HNSW_EF_SEARCH`
(pgvector ≥ 0.8) so filtered searches can stay on the HNSW index. Results below `RAG_MIN_SCORE`
(cosine similarity) are dropped. The embedding column is never selected.

Planner note: for small or highly selective sources PostgreSQL may prefer the `(source_id,
embedding_model)` btree plus an exact sort — exact results, cheaper at that size. The query shape is
proven HNSW-compatible by `test_search_query_can_use_the_hnsw_index`.

Each `Document` carries `chunk_id, document_id, source_id, source, title, uri, ordinal, score,
embedding_model, attributes` — everything a citation needs.

## NCERT textbooks (`app/rag/ncert.py`)

With `NCERT_KB_BASE_URL` and `NCERT_KB_API_KEY` set, the knowledge source is the NCERT Knowledge Service
(a separate service and repository, `sunny436/graphrag`; production `ncert-kb-api` on 127.0.0.1:4200) instead
of pgvector; attached files stay in pgvector.

- **Request:** `POST /api/v1/retrieval/search` with `Authorization: Bearer <key>`, `mode: vector`, `top_k`
  (`RAG_TOP_K`, three times that for a student with a curriculum) and
  `filters: {enforcement: strict, any_of: [{classes: [6..12]}]}`: the tutor serves Classes 6-12 only
  (`SERVED_CLASSES`, owner decision 2026-10-14); Classes 1-5 are never searched, and a result outside 6-12
  is dropped here as well. The student's class and subjects (`retrieval_for` in `app/chat/assistant.py`)
  are never sent: they rank the results here, their own books first, then the top `RAG_TOP_K` are kept.
  Subject ids are the names in slug form.
- **Query:** the latest question; a short follow-up (six words or fewer) is searched together with the question
  before it (`search_query_for` in `app/rag/graph.py`). A rule, not a model call. At most 32 words are sent
  (`search_text`: the first and last 16 of a longer query), because the service's encoder time grows with
  every word (4 words 0.55 s, 30 words 1.8 s, 70 words 3.3 s on the VM); the tutor still gets the whole question.
- **Response:** results are validated field by field and malformed ones dropped; each passage is capped at
  4,000 characters, and the context budget below still decides what fits. `[n]` is titled
  "NCERT <book> (Class n), Ch k: <chapter>, p. <printed page>".
- **Failure:** `ncert_timeout` (`NCERT_KB_TIMEOUT_S`, 6 s: live searches took ~1.7 s, p95 2.8 s and at most 3.9 s
  from 2026-10-15 to 10-19, too close to the earlier 4 s),
  `ncert_unauthorized`, `ncert_unavailable`, `ncert_bad_response`; after 3 in a row, `ncert_paused` for 30 s
  (no call). Each is a retrieval failure with that reason: the reply goes on without textbook context.
- **Privacy:** only the search query (at most 32 words of the question, with the question before it for a
  short follow-up) and the fixed Classes 6-12 scope are sent. The student's class and subjects never leave
  this app (they only rank the results here), and nothing that identifies them: no user id, name or email.

## Context budget (`app/rag/context.py`)

All sizes in characters (≈ 4 chars/token for English; Devanagari costs ~2.6× more tokens per char):

1. system prompt — always
2. latest user message — always
3. retrieved chunks, whole, in rank order, until `RAG_MAX_CONTEXT_CHARS` (default 8,000); a chunk that
   does not fit ends the context (never cut mid-chunk)
4. earlier conversation, newest first, whole messages, until `LLM_MAX_INPUT_CHARS` (default 48,000)

The context message tells the model the material may be incomplete or unrelated, to use it only when
it directly answers, and never to invent sources. Blocks are numbered `[1]..[n]` in the same order as
`messages.metadata.retrieval.sources`, so citations can be exposed later without changing RAG.

## Failure behaviour

| Situation | Result |
|---|---|
| `RAG_ENABLED=false`, no embedding key, empty knowledge base | retrieval skipped, no embedding call; normal reply |
| embedding error / timeout, database unavailable, retrieval timeout | `failed` + reason; reply without context; persistence unaffected |
| no chunk above `RAG_MIN_SCORE` | `empty`; reply without context |
| LLM failure | existing typed error handling (`error` SSE event, partial text kept) |

## Observability

- Log `rag.retrieval`: status, reason, chunk count, top score, `embedding_ms`, `search_ms`, `total_ms`.
- Log `rag.graph`: retrieval status, context sources/chars, prompt chars, history kept/dropped.
- Log `ingest document`: status, chunks, duration.
- The same summary is stored per reply in `messages.metadata.retrieval` (internal; not part of the
  public API response).
- Never logged: question text, document or chunk text, keys. (Tested.)
- **Do not enable LangSmith tracing** (`LANGSMITH_*` / `LANGCHAIN_TRACING*`): it would send prompts and
  documents to an external service.

## Configuration

`RAG_ENABLED, RAG_TOP_K, RAG_MIN_SCORE, RAG_MAX_CONTEXT_CHARS, RAG_RETRIEVAL_TIMEOUT_S,
RAG_HNSW_EF_SEARCH, RAG_CHUNK_SIZE, RAG_CHUNK_OVERLAP, RAG_MAX_DOCUMENT_BYTES, LLM_MAX_INPUT_CHARS,
EMBEDDING_PROVIDER, EMBEDDING_BASE_URL, EMBEDDING_API_KEY, EMBEDDING_MODEL, EMBEDDING_DIMENSIONS,
EMBEDDING_BATCH_SIZE, EMBEDDING_TIMEOUT_S` — see `backend/.env.example`.

## Local development and tests

```sh
docker compose -f docker-compose.dev.yml up -d
cd backend && .venv\Scripts\python -m alembic upgrade head
set EMBEDDING_PROVIDER=fake            # offline; or set EMBEDDING_API_KEY for real embeddings
.venv\Scripts\python scripts\ingest_documents.py --source demo --global path\to\docs
run_backend.bat                        # chat; replies store retrieval status/sources in metadata
.venv\Scripts\python -m pytest tests\test_rag_*.py tests\test_architecture_guards.py
```

Calibrate `RAG_MIN_SCORE` with real embeddings: `python scripts/eval_retrieval.py --cases cases.jsonl`
(`{"query": ..., "expected_uri": ...}` per line).

## Verification status

| Verified (tests / local runs) | NOT VERIFIED |
|---|---|
| schema, migrations, HNSW-compatible query, filters, access boundary, versioning, atomicity, concurrency, graph wiring, skip/failure paths, cancellation, logging hygiene — with a fake embedder | real OpenAI embeddings (no key configured); real retrieval relevance; `RAG_MIN_SCORE` calibration; performance at scale (≥ 100k chunks); production (untouched) |

## Citations

The prompt numbers knowledge chunks `[1]..[n]` and attached files `[F1]..`, and the turn keeps
both lists (`retrieval.sources`, `retrieval.fileSources`, internal). `app/chat/service.py`
`public_citations` turns them into the public `metadata.citations` (`ref`, `kind`, `title`, and
`fileId` for files; never URIs or scores), omitted when nothing was numbered. The web app shows
the markers as chips with a Sources list, and `::file{ref=F1}` / `::pdf{ref=F1}` previews resolve
through it (`GET /v1/files/{id}/content`, the owner's own files only).

## Files the student attached (app/files)

Separate from the knowledge base, and never searched globally: a student's files are only ever
read in that student's own chats, and only once attached to a message in the conversation.

- **Processing** (`app/files/processing.py`): the sandboxed extractor (`app/files/extract.py`:
  pypdfium2, python-docx, python-pptx, openpyxl, Tesseract `eng+hin` for scanned pages and photos)
  returns page, slide or sheet texts; LangChain `Document`s → `RecursiveCharacterTextSplitter`
  (`RAG_CHUNK_SIZE`/`RAG_CHUNK_OVERLAP`) → the same `Embeddings` → `file_chunks` (vector(1536), no
  vector index). A file is `ready` only when its text is usable (OCR confidence ≥ 60) and every
  chunk is stored; otherwise `failed` with a reason.
- **Scope of a turn** (`conversation_files`): the 5 most recently attached ready files of the
  conversation (≤ 4,000 chunks), so follow-up questions and regenerations keep using them; a
  deleted file drops out (its attachment keeps only the name).
- **Retrieval** (`AttachedFiles` in `app/rag/retriever.py`, `KnowledgeStore.search_files`): files
  of ≤ 12,000 characters are given whole, in reading order; larger ones are searched exactly, the
  closest chunks of each file (8 spread over the files, at least 2 each). The question is embedded
  once; if that fails, reading order is used, so an attached file is never silently ignored.
  `RAG_ENABLED` and the knowledge base's own skip reasons concern the knowledge base only.
- **Prompt** (`app/rag/context.py`): the passages go inside the latest user message, in an
  `<attached_files>` block marked as reference material, not instructions (never a system message;
  anything in a file that could close the block is neutralised), up to 16,000 characters, labelled
  `[F1] name (whole file)` or `(excerpts: k of N sections, not the full file)`.
- **Changing the embedding model**: at startup, ready files embedded with another model become
  `failed(model_changed)` and are read again on Retry.

