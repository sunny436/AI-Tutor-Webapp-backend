# backend — the chat API

FastAPI service. PostgreSQL + pgvector is the only datastore.

```
app/
  main.py            application factory (create_app), lifespan, routers
  settings.py        environment configuration (refuses unsafe production values)
  logging.py         JSON logs with request/user ids — never message content
  errors.py          typed errors → {"error": {code, message, requestId}}
  middleware.py      request id, access log, 64 KB body limit (pure ASGI)
  health.py          /health (liveness), /ready (database)
  db/                SQLAlchemy models + async engine (asyncpg)
  auth/              sign-up/verify/login/reset, sessions, profile, settings
  conversations/     conversation + message history (always scoped to the user)
  chat/              ChatService: prepare → generate (task) → persist; SSE; stop; regenerate; feedback
  llm/               LLMProvider protocol, OpenAI-compatible provider, fallback, fake, typed errors
  rag/               LangGraph turn graph, LangChain retriever, knowledge store, ingestion, embeddings
alembic/             migrations (0001: schema + extensions; 0002: knowledge base with vector(1536))
scripts/             export_openapi.py (contract), smoke_chat.py (live check),
                     ingest_documents.py (knowledge base), eval_retrieval.py (retrieval quality)
tests/               pytest against a real PostgreSQL test database; tests/e2e drives a real server
```

Commands (from this directory; on Linux use `.venv/bin/python`):

| Task | Command |
|---|---|
| Install | `python -m venv .venv` then `.venv\Scripts\python -m pip install -r requirements-dev.txt` |
| Migrate | `.venv\Scripts\python -m alembic upgrade head` |
| Run | `run_backend.bat` or `.venv\Scripts\python -m uvicorn app.main:create_app --factory --port 4000` |
| Test | `.venv\Scripts\python -m pytest` |
| Lint | `.venv\Scripts\python -m ruff check . && .venv\Scripts\python -m ruff format --check .` |
| Contract | `.venv\Scripts\python scripts\export_openapi.py` (`--check` in CI) |
| Live smoke | `.venv\Scripts\python scripts\smoke_chat.py` (server running, real LLM key, Mailpit) |
| Ingest documents | `.venv\Scripts\python scripts\ingest_documents.py --source NAME --global PATH` (see docs/rag.md) |

Configuration: every variable is listed in [.env.example](.env.example).
