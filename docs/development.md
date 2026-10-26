# Local development

> **New to the project?** [beginner-guide.md](beginner-guide.md) walks through the same setup one step at a time,
> with what you should see and what to do when a step fails.

One clone has everything: `backend/` (FastAPI) and `frontend/` (Next.js). Requirements: Python 3.12,
[Bun](https://bun.sh) 1.3.14 (`.bun-version`), Node 24 (`.node-version`; the end-to-end tests run the
web app on Node, as production does), Docker (Docker Desktop on Windows). Run the commands from the repository
root; on Windows use Git Bash or PowerShell.

## Set up and run

```sh
git clone <repository> && cd <repository>
bun run setup      # backend/.venv + requirements, backend/.env from the example, frontend bun install
bun run dev        # dev database (Docker) + migrations, then API :4000 and web :3000 together
```

- Open **http://localhost:3000**, not `127.0.0.1:3000`. Next.js rewrites 127.0.0.1 to `localhost` in
  redirects, and the session cookie is per host name.
- `docker-compose.dev.yml` runs PostgreSQL 16 + pgvector on `127.0.0.1:5432` (user, password and db
  all `aichat`, development only) and Mailpit, which catches sign-up and reset emails. Its SMTP is
  on `127.0.0.1:1025` and its inbox at http://127.0.0.1:8025.
- `backend/.env` needs an LLM key (`LLM_PRIMARY_API_KEY`). Without one, set `LLM_PROVIDER=fake`
  (replies echo your message word by word).
- API docs: http://127.0.0.1:4000/docs (development only).

Separately: `bun run dev:backend` (API with reload) and `bun run dev:frontend` (web; expects the API on
:4000). The frontend's settings are in `frontend/apps/app/.env.local` (from `.env.example`); by
default it calls the API at `http://127.0.0.1:4000`.

## Commands

| Command (repository root) | What it runs |
|---|---|
| `bun run test` | backend pytest (own `aichat_test` database) + frontend typecheck and unit tests + the deploy gate's tests |
| `bun run test:e2e` | Playwright + axe end-to-end: a production build on :3100 against an API on :4100 with the fake LLM, codes read from Mailpit. Starts the API from `backend/` unless one is already running. |
| `bun run lint` | ruff check + format check, Biome |
| `bun run build` | frontend production build + "is `docs/openapi.json` current?" |
| `bun run contract` | regenerate `docs/openapi.json` from the backend, then the frontend contract test |
| `bun run lock:backend` | regenerate `backend/requirements.lock` (hashed pins, Linux + Python 3.12, in Docker) after changing `backend/requirements.txt` |
| `bun run deploy` / `bun run rollback` / `bun run status` | production, always both halves together ([deployment.md](deployment.md), [rollback.md](rollback.md)) |
| `bun run rehearse` | the release model end to end on a throwaway systemd container (Docker, ~45 min) |

`scripts/run.mjs` implements them over the existing tools, so the underlying commands still work:
in `backend/`, `.venv\Scripts\python -m pytest tests/test_chat.py` (Linux: `.venv/bin/python`); in
`frontend/`, `bun run test`, `bun run typecheck`; in `frontend/apps/app`, `bun test src/lib/api/routes.test.ts`.
Don't run `bun install` at the repository root: the Bun workspace root is `frontend/`.

The backend suite creates and migrates its own database `aichat_test` (override with
`TEST_DATABASE_URL`; the name must end in `_test`), truncates tables before each test, uses a fake
LLM and an in-memory mailbox, and never touches the development database. CI (GitHub Actions) runs
three jobs on every push and pull request: Backend (lint, contract, tests), Frontend (typecheck, lint,
tests incl. contract, build) and Integration (end-to-end). CI is advisory: `bun run deploy` never waits
for it, and `bun run status` shows its verdict ([deployment.md](deployment.md)).

## Dependencies

Production and CI install the backend from `backend/requirements.lock`: every package at one exact
version with its hashes (`pip install --require-hashes`). `requirements.txt` holds the allowed
ranges; after changing it, run `bun run lock:backend` and commit both (a test fails if they
disagree). The frontend is locked by `frontend/bun.lock`. The runtimes are pinned by `.node-version`
and `.bun-version`, which CI and every release use.

## Changing the API

The contract is `docs/openapi.json`, generated from the backend. After changing a route or a
request/response model:

```sh
bun run contract
```

This regenerates the file and runs the frontend's `routes.test.ts`, which fails if a route the
frontend proxy allows, or a request field it sends, no longer exists. Frontend and backend changes
go in the same commit, and CI checks the file is current. A new endpoint the browser needs also has
to be added to the proxy's allowlist, `frontend/apps/app/src/lib/api/routes.ts`.

## Adding a migration

Change `backend/app/db/models.py`, then in `backend/`: `.venv\Scripts\python -m alembic revision -m "describe it"`,
and write the upgrade by hand (or `--autogenerate` and review it). `tests/test_foundation.py` fails
if the models and the migrated schema differ. Production runs migrations before switching to a new
release, while the old one still serves, so they must be backward compatible
([deployment.md](deployment.md#migrations)).

## Verify the whole flow with a real model

With the API running (a real `LLM_PRIMARY_API_KEY`) and Mailpit up, in `backend/`:

```sh
.venv\Scripts\python scripts\smoke_chat.py
```

It signs up a throwaway account (code from Mailpit), streams a reply, stops one mid-stream,
regenerates, leaves feedback, renames, checks persisted history, and deletes the conversation and
the account. Never point it at production.

## Knowledge base (RAG)

```sh
set EMBEDDING_PROVIDER=fake     # offline keyword-hash embedder; or set EMBEDDING_API_KEY for real embeddings
.venv\Scripts\python scripts\ingest_documents.py --source demo --global docs\my-notes
```

Without an embedding key (and not `fake`) retrieval is skipped and chat works normally. See
[rag.md](rag.md), including what the fake embedder does not verify.
