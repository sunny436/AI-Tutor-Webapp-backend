# Local development

Requirements: Python 3.12, Docker (Docker Desktop on Windows). Commands use Windows paths;
on Linux/macOS replace `.venv\Scripts\python` with `.venv/bin/python`.

## 1. Start PostgreSQL + pgvector and Mailpit

```sh
docker compose -f docker-compose.dev.yml up -d
```

- PostgreSQL 16 with pgvector on `127.0.0.1:5432` (user/password/db `aichat`, development only).
- Mailpit (catches sign-up and reset emails): SMTP `127.0.0.1:1025`, inbox at http://127.0.0.1:8025.

## 2. Install and configure

```sh
cd backend-python
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
copy .env.example .env
```

Fill in `SECRET_KEY` and the LLM keys (`LLM_PRIMARY_API_KEY`, optionally the fallback). To work
without any LLM account set `LLM_PROVIDER=fake` (replies echo the message).

## 3. Migrate and run

```sh
.venv\Scripts\python -m alembic upgrade head
run_backend.bat          # or: .venv\Scripts\python -m uvicorn app.main:create_app --factory --port 4000 --reload
```

API docs: http://127.0.0.1:4000/docs (development only).

## 4. Tests

```sh
.venv\Scripts\python -m pytest                 # everything, including tests/e2e (real HTTP server)
.venv\Scripts\python -m pytest tests\e2e       # only the end-to-end flow
```

The suite creates and migrates its own database `aichat_test` (override with `TEST_DATABASE_URL`;
the name must end in `_test`), truncates tables before each test, uses a fake LLM and an in-memory
mailbox, and never touches the development database or any remote service.

Lint and contract:

```sh
.venv\Scripts\python -m ruff check . && .venv\Scripts\python -m ruff format --check .
.venv\Scripts\python scripts\export_openapi.py            # regenerate docs/openapi.json after API changes
```

## 5. Verify the whole flow with a real model

With the server running (real `LLM_PRIMARY_API_KEY`) and Mailpit up:

```sh
.venv\Scripts\python scripts\smoke_chat.py
```

It signs up a throwaway account (code from Mailpit), streams a reply, stops a reply mid-stream,
regenerates, leaves feedback, renames, checks persisted history, and deletes the conversation and
the account. Never point it at production.

## Adding a migration

Change `app/db/models.py`, then `.venv\Scripts\python -m alembic revision -m "describe it"` and write
the upgrade by hand (or `--autogenerate` and review it). `tests/test_foundation.py` fails if the
models and the migrated schema differ.
