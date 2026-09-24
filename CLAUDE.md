# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

The backend of a generic ChatGPT-style chatbot that will grow into an AI tutor: a FastAPI service in
`backend/` on PostgreSQL 16 + pgvector (the only datastore). The Next.js web app lives in a
**separate repository** (`AI Tutor- Frontend`) and is the API's only client, through its server-side proxy.
The repo formerly held an Ayurveda chatbot; that code is only reachable at the git tag `ayurveda-baseline`.

Remotes: `tutor` = `sunny436/AI-Tutor-Webapp-backend` (PRs go to its `main`); `origin` = the old Ayurveda repo.

## Commands

Run from `backend/`. Windows paths shown; on Linux use `.venv/bin/python`.

```sh
docker compose -f ../docker-compose.dev.yml up -d        # PostgreSQL+pgvector :5432, Mailpit :1025 / UI :8025
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m alembic upgrade head
.venv\Scripts\python -m uvicorn app.main:create_app --factory --port 4000   # or run_backend.bat

.venv\Scripts\python -m pytest -o addopts="" -ra                  # full suite, as CI runs it (a few minutes)
.venv\Scripts\python -m pytest tests/test_chat.py                  # one file
.venv\Scripts\python -m pytest "tests/test_email.py::test_backend_selection"   # one test (or -k pattern)
.venv\Scripts\python -m ruff check . && .venv\Scripts\python -m ruff format --check .
.venv\Scripts\python scripts\export_openapi.py            # regenerate docs/openapi.json; CI runs it with --check
```

- Tests need the dev compose stack. They drop, recreate and migrate their own database (`aichat_test`, override
  with `TEST_DATABASE_URL`; the name **must** end in `_test`), and truncate all tables before each test. They use
  a fake LLM, fake keyword-hash embeddings and an in-memory mailbox, so no network is needed.
- When piping pytest/ruff output (e.g. `| tail`), check the exit code separately: a pipe hides failures.
- Offline dev without API keys: `LLM_PROVIDER=fake`, `EMBEDDING_PROVIDER=fake`. Fake embeddings only measure
  shared vocabulary; they prove plumbing, never retrieval quality.
- Other scripts: `smoke_chat.py` (live end-to-end check against a running server + Mailpit; never point it at
  production), `ingest_documents.py` (knowledge base; `--global` or `--owner-email` is mandatory),
  `eval_retrieval.py` (calibrate `RAG_MIN_SCORE` with real embeddings).

## Architecture

`app/main.py` `create_app(settings, *, llm, email_sender, embeddings)` is the **composition root**: the only place
that wires the concrete LLM provider, embeddings, knowledge store, retriever and LangGraph graph. Tests inject fakes
through it. Settings come from env (`backend/.env.example` lists all); `Settings.validate_for_env()` refuses
unsafe production values (dev secrets, fake LLM/embeddings, memory email).

**A chat turn** (`app/chat/service.py`) is split in two:
1. *prepare* (inside the HTTP request's transaction): load or create the user's conversation, 409 if a reply is
   already streaming, check quotas, insert the user message and an assistant placeholder, commit.
2. *generate* (an independent asyncio task, registered in `app/chat/streams.py`): runs the LangGraph turn graph and
   pushes SSE events (`meta` / `token` / `done` / `error`), then persists content, status and a retrieval summary.
   Stop and client disconnect cancel the task (event or DB flag). PostgreSQL stays the source of truth for status.

**The graph** (`app/rag/graph.py`): `receive_query → retrieve_context → assemble_context → generate_answer`.
- Retrieval never fails a turn: it is skipped (disabled, no embedding key, empty knowledge base) or fails with a
  reason code, and the reply proceeds without context.
- Exactly one LLM generation per turn, with no graph retries. `FallbackProvider` (`app/llm/fallback.py`) switches
  providers only **before the first token**.
- `app/rag/context.py` builds the prompt under one deterministic character budget, in this order: system prompt →
  latest message → whole chunks up to `RAG_MAX_CONTEXT_CHARS` → history, newest first, up to `LLM_MAX_INPUT_CHARS`.
  Context blocks are numbered `[n]` in the same order as `messages.metadata.retrieval.sources`.

**Retrieval / RAG** (`docs/rag.md` is the reference):
- `PgVectorRetriever` (LangChain `BaseRetriever`, async only) → `KnowledgeStore` (SQLAlchemy) → pgvector HNSW.
- Every search takes `AccessScope(user_id)`. Allowed sources = global (`owner_user_id` NULL) plus the user's own.
  `source_names` and `metadata_filter` can only narrow that set.
- Retrieval options come only from `resolve_assistant_config` (`app/chat/assistant.py`), the extension seam for
  tutor-specific prompts and filters. Chat requests reject unknown fields, so clients can never pass filters.
- The embedding dimension is fixed at **1536** in three places kept in sync by a test: `EMBEDDING_DIMENSIONS` in
  `app/db/models.py`, the `vector(1536)` column (migration `0002`), and the `EMBEDDING_DIMENSIONS` setting.
  Chunks record `embedding_model`, and search only sees the configured model. Changing the model or dimension needs
  a new migration plus an explicit re-ingest. Nothing is ever re-embedded automatically.

**Enforced by `tests/test_architecture_guards.py`** (AST import rules; keep them passing):
- `*/router.py` never imports `app.rag` or `pgvector`.
- `app/chat/*` imports only `app.rag.graph` from `app.rag`, and never `langchain`, `langgraph` or `pgvector`.
- `app/rag/graph.py` depends on abstractions only: no concrete LLM providers, no store, embeddings or retriever,
  no SQLAlchemy.
- `app/db/*` and `app/rag/store.py` never import LangChain or LangGraph.
- No GraphRAG, Chroma, Pinecone, Weaviate or Qdrant anywhere. This is an owner decision: pgvector is the only
  vector store.

**Cross-cutting:**
- Errors always use the envelope `{"error": {code, message, requestId}}` (`app/errors.py`).
- Logs are JSON and must never contain message content, questions, document text or keys. A test checks this.
- Auth (`app/auth/`) is email-code verification with server-side sessions and anti-enumeration: sign-up, resend and
  forgot-password always return 202, and an unknown email costs the same argon2 time as a wrong password.
- Email is pluggable through `EMAIL_BACKEND=smtp|ollastack|memory`. Ollastack is an HTTP API, not SMTP.
- The DB driver is asyncpg on purpose: psycopg's async mode doesn't work on Windows' Proactor loop.

**Schema changes:** edit `app/db/models.py`, then add a hand-written Alembic revision.
`tests/test_foundation.py` fails if the models and the migrated schema differ. After any API change, regenerate
`docs/openapi.json`; the internal `messages.metadata.retrieval` is intentionally not exposed publicly.

## Production (single VM; changes need the owner's explicit approval)

- Ubuntu 24.04 VM at `10.1.30.37`, reached with `ssh root@10.1.30.37`. Public site: `ayur.namahos.com`, via a
  Cloudflare Tunnel to the web app on `127.0.0.1:3000`.
- Units: `aichat-postgres`, `aichat-api` (**`127.0.0.1:4100`** in prod; dev uses 4000), `aichat-web`,
  `aichat-pg-backup.timer`. The legacy Ayurveda units (`ayurveda-backend`, `convex`) may still be running for
  rollback.
- Secrets live only in `/etc/aichat/*.env` (mode 600). The host has **no GitHub credentials**: code arrives as git
  bundles in `/root/aichat-bundles/` (`docs/production-migration.md` has the exact update commands).
- `deploy/install.sh` caveats:
  - It rebuilds the frontend in place (`.next`), which breaks a live `aichat-web` mid-build.
  - After it `git pull`s itself, the rest of that run still executes the old script.

  Once the web app is live, prefer targeted steps (e.g. `systemctl restart aichat-api` after updating
  `/opt/aichat/backend`).
- Load env for one-off commands exactly as the service does:
  `systemd-run --pipe --wait --collect -p EnvironmentFile=/etc/aichat/api.env ...`. Don't `source` the file in bash:
  values such as `EMAIL_FROM` contain `<`.
- Runbook and rollback: `docs/production-migration.md`. Layout: `INFRASTRUCTURE.md`, `deploy/README.md`.

## Repo hygiene

- `ollima.txt` and `ollastack.txt` in the repo root hold live provider keys. They are git-ignored; never print or
  commit their contents.
- `.claude/settings.local.json` is tracked but holds per-user permission rules. Don't commit local changes to it.
- `.gitattributes` forces LF (`* text=auto eol=lf`), so shell scripts run on Linux.
- On this Windows machine, Python's default encoding is cp1252. Pass `encoding="utf-8"` when reading or writing
  files from scripts, and set `PYTHONIOENCODING=utf-8` when printing non-ASCII.
