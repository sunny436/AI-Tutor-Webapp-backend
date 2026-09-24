# Chat API

Backend for a generic, ChatGPT-style AI chatbot: accounts, conversations, streamed
replies, and a PostgreSQL + pgvector data layer designed to grow into an AI tutor.

```
web app (separate repository) ──► FastAPI chat API ──► PostgreSQL 16 + pgvector
      server-side proxy               (this repo)         (single source of truth, incl. RAG vectors)
                                            │
                                            ├──► LangGraph turn graph + LangChain retriever
                                            └──► LLM providers (Ollima → OpenRouter fallback), embeddings API
```

| What | Where |
|---|---|
| API service (FastAPI, SQLAlchemy async, Alembic) | [backend-python/](backend-python/) |
| API contract (endpoints, SSE events, errors) | [docs/api-contract.md](docs/api-contract.md), [docs/openapi.json](docs/openapi.json) |
| Architecture and extension points | [docs/architecture.md](docs/architecture.md) |
| RAG: LangGraph + LangChain + pgvector | [docs/rag.md](docs/rag.md) |
| How a web app integrates | [docs/frontend-integration.md](docs/frontend-integration.md) |
| Local development and tests | [docs/development.md](docs/development.md) |
| Target deployment | [deploy/](deploy/), [INFRASTRUCTURE.md](INFRASTRUCTURE.md) |
| Production migration (not yet executed) | [docs/production-migration.md](docs/production-migration.md) |

## Quick start (Windows or Linux)

```sh
docker compose -f docker-compose.dev.yml up -d          # PostgreSQL + pgvector, Mailpit
cd backend-python
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt   # Linux: .venv/bin/python
cp .env.example .env                                    # add LLM keys
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m uvicorn app.main:create_app --factory --port 4000
```

Tests: `cd backend-python && .venv/Scripts/python -m pytest` (needs the dev compose stack).

## History

The previous product that lived in this repository, and how it is retired, is described in
[docs/production-migration.md](docs/production-migration.md). Nothing from it is used here.
