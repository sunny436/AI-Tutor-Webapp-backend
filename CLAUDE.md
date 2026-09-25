# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

The whole ChatGPT-style chat application, which will grow into an AI tutor. There is **one
repository, and each commit is one release** of both halves:

- `backend/`: FastAPI API on PostgreSQL 16 + pgvector (the only datastore). It has its own Python 3.12 venv, ruff and pytest.
- `frontend/`: Next.js 14 web app with its server-side proxy (BFF). It's a Bun + Turborepo workspace:
  `apps/app`, `packages/ui`, `tooling/typescript`. `frontend/CLAUDE.md` has the frontend detail;
  Claude Code loads it when you work there.

They are two processes, but they are tested, deployed and rolled back together. **AI Tutor is
released as one application. Frontend and backend are never independently deployed to production.**
Never add a command, script or unit that deploys only one half.

History:
- The frontend was a separate repository (`sunny436/AI-Tutor-Webapp-frontend`). It was imported with
  its history into `frontend/`, and that repository is no longer used.
- The backend formerly held an Ayurveda chatbot; that code is only at the tag `ayurveda-baseline`.
- Remotes: `tutor` is `sunny436/AI-Tutor-Webapp-backend` (PRs go to its `main`); `origin` is the old Ayurveda repo.

## Commands

From the repository root (the implementation is `scripts/run.mjs`, a thin runner over each half's own tools):

```sh
bun run setup | dev | dev:backend | dev:frontend       # dev: Docker db + migrations, API :4000 + web :3000
bun run test          # backend pytest + frontend typecheck + unit tests (incl. the API contract test)
bun run test:e2e      # Playwright + axe against an API on :4100 with the fake LLM (starts it from backend/)
bun run lint | build | contract                        # contract: regenerate docs/openapi.json + frontend check
bun run deploy | rollback | status                     # production (docs/deployment.md, docs/rollback.md)
bun run lock:backend  # after editing backend/requirements.txt: regenerate the hashed requirements.lock
bun run rehearse      # the release model on a throwaway systemd container (Docker, ~45 min)
```

Directly, in `backend/` (Windows paths; Linux `.venv/bin/python`):

```sh
.venv\Scripts\python -m pytest -o addopts="" -ra                              # as CI runs it
.venv\Scripts\python -m pytest "tests/test_email.py::test_backend_selection"   # one test (or -k)
```

Directly, in `frontend/`: `bun run test`, `bun run typecheck`, `bun run lint`. Or, in
`frontend/apps/app`, `bun test src/lib/api/routes.test.ts`.

- **Where to install:** never run `bun install` at the repository root. The Bun workspace root is
  `frontend/`, and the root `package.json` has no workspaces and no dependencies.
- **Backend tests:** they need the dev compose stack. They drop, recreate and migrate their own
  `aichat_test` database (the name **must** end in `_test`), truncate tables before each test, and
  use a fake LLM, fake embeddings and an in-memory mailbox.
- **Pipes hide failures:** when piping pytest/ruff/bun output (e.g. `| tail`), check the exit code separately.
- **Offline dev:** `LLM_PROVIDER=fake` and `EMBEDDING_PROVIDER=fake`. Fake embeddings only measure
  shared vocabulary, so they prove plumbing, not retrieval quality.
- **Other backend scripts:**
  - `smoke_chat.py`: live check against a running server; never point it at production.
  - `ingest_documents.py`: knowledge base; `--global` or `--owner-email` is mandatory.
  - `eval_retrieval.py`: retrieval quality.
  - `migration_status.py`: schema vs code, as JSON.

## How the halves connect

**Browser → BFF → API.**
- The browser only ever calls its own origin, `/api/v1/*`.
- `frontend/apps/app/src/lib/server/proxy-core.ts` forwards the allowlist in `lib/api/routes.ts` to
  `API_BASE_URL`, which is server-only. It adds `Authorization: Bearer <token>`; the token comes from the
  httpOnly cookie `__Host-aichat_session`.
- It enforces Origin on mutations, a 64 KB body limit and JSON bodies. It passes SSE through
  unbuffered, and aborts upstream when the browser leaves, which the API treats as stop.
- Server components call the API directly with `lib/server/backend.ts`. If the API is unreachable,
  users see an outage screen, not a sign-out.

Never let the browser call the API, and never hand the token to page code.

**One contract.** `docs/openapi.json` is generated from the backend (`backend/scripts/export_openapi.py`).
The frontend's `routes.test.ts` reads that file and fails if a proxied route or request field no
longer exists. Change both halves in the same commit, then run `bun run contract`; CI checks that the
file is current. A new endpoint for the browser must also be added to `routes.ts`.

**Backend internals.**
- **Composition root:** `backend/app/main.py` `create_app(settings, *, llm, email_sender, embeddings)`
  wires everything; tests inject fakes through it. `Settings.validate_for_env()` refuses unsafe
  production values.
- **A chat turn** (`app/chat/service.py`): *prepare* runs in the request transaction (conversation,
  409 if a reply is already streaming, quotas, user message + assistant placeholder). *Generate* runs
  as an independent asyncio task registered in `app/chat/streams.py`. It runs the LangGraph graph
  `receive_query → retrieve_context → assemble_context → generate_answer` (`app/rag/graph.py`), emits
  SSE `meta`/`token`/`done`/`error`, and persists the result. Stop and disconnect cancel the task.
- **One model call per turn:** there are no graph retries, and `FallbackProvider` switches providers
  only before the first token.
- **Retrieval never fails a turn:** it is skipped or fails with a reason code.
- **Context budget** (`app/rag/context.py`): system prompt → latest message → whole chunks up to
  `RAG_MAX_CONTEXT_CHARS` → history up to `LLM_MAX_INPUT_CHARS`.
- **RAG** (`docs/rag.md`): `PgVectorRetriever` → `KnowledgeStore` → pgvector HNSW.
  - Every search is scoped by `AccessScope(user_id)`: global sources plus the user's own.
  - Retrieval options come only from `resolve_assistant_config` (`app/chat/assistant.py`), which is
    the seam for tutor features.
  - The embedding dimension is fixed at **1536** in three places, kept in sync by a test.
  - Changing the model or dimension needs a migration plus a re-ingest.
- **Enforced by `tests/test_architecture_guards.py`:**
  - routers never import `app.rag` or pgvector;
  - `app/chat/*` imports only `app.rag.graph`;
  - `graph.py` depends on abstractions only;
  - `app/db/*` and `store.py` never import LangChain or LangGraph;
  - no GraphRAG, Chroma, Pinecone, Weaviate or Qdrant.
- **Cross-cutting:**
  - one error envelope `{"error": {code, message, requestId}}`;
  - JSON logs that never contain message or document text, or keys;
  - email-code auth with anti-enumeration;
  - `EMAIL_BACKEND=smtp|ollastack|memory`;
  - asyncpg on purpose (psycopg async fails on Windows' Proactor loop).
- **Schema changes:** edit `app/db/models.py` and add a hand-written Alembic revision.
  `tests/test_foundation.py` checks parity. Migrations must be backward compatible, because
  production runs them before switching releases.

## Deployment and production

- **What gets deployed:** `bun run deploy` (`deploy/deploy.sh`) takes a commit of GitHub's `main`
  (the tip by default) whose three CI jobs passed on that exact commit (`deploy/ci-gate.mjs`, fail
  closed), sends `git archive` of it plus a file manifest to the host, and runs it there as a
  detached systemd unit (`deploy/server/bootstrap.sh` → that release's `deploy/server/release.sh`).
- **The release steps:** verify every file against the commit → build into
  `/opt/aichat/releases/<commit>/` (backend from the hashed `requirements.lock`, frontend on the
  pinned Node) → migrations (only with `--with-migrations`, after a backup) → trial API :4101 and
  web :3001 on the real database, proving web → API → database by request id → switch: stop web,
  flip `/opt/aichat/current`, restart API, start web (≈7–8 s outage, never mixed) → prove the
  invariant → automatic rollback on failure.
- **Release identity:** each release has a `RELEASE` file; the API's `/health` and the web app's
  `/api/health` (loopback only) report it. `bun run status` checks pointer = both reported
  releases = every process's release = files match the commit, and prints `INVARIANT OK`/`FAIL`.
- **Pinned runtimes:** `.node-version` (the web app runs on Node, not Bun's runtime: Bun does not
  signal a client disconnect, which breaks stop-on-leave), `.bun-version`, `backend/requirements.lock`.
- **Rollback:** `bun run rollback` switches both back together, to the previously live release
  (`LIVE-STACK`). Details in `docs/deployment.md`, `docs/rollback.md` and `deploy/README.md`.
- **Host:** Ubuntu 24.04 VM `10.1.30.37` (`ssh root@10.1.30.37`). It has no GitHub access. The public
  site `ayur.namahos.com` goes through a Cloudflare Tunnel to web `127.0.0.1:3000`. The API is on
  `127.0.0.1:4100` (4000 is dev), and PostgreSQL is Docker on `127.0.0.1:5432`.
- **Secrets:** only in `/etc/aichat/{api,web,postgres}.env` (mode 600). Load them for one-off
  commands with `systemd-run --pipe --wait --collect -p EnvironmentFile=/etc/aichat/api.env ...`;
  don't `source` them.
- **The database is outside releases:** `/opt/aichat/shared/postgres`. Its Compose project and volume
  names are pinned (`compose` / `compose_pgdata`); moving or renaming them would start an empty
  database.
- **Status:** production runs the release layout since 2026-09-25 (first release `a353815`,
  `INFRASTRUCTURE.md`). The pre-release leftovers (old checkouts `/opt/aichat/{backend,frontend}`,
  `/root/aichat-bundles`, units saved as `aichat-*.before-20260925052156`, the legacy Ayurveda
  services) are kept for rollback until the owner approves their removal; don't touch them.
  Production changes need the owner's explicit approval.
- **Never, by hand:** edit a release, repoint `current` (except the emergency steps in
  `docs/rollback.md`), run migrations outside `release.sh`, `docker compose down -v`, or change
  `API_BASE_URL` in `web.env` (the frontend's default `:4000` is the old API on that host).
- **Changing the deploy scripts:** prove it with `bun run rehearse`; the host scripts run from the
  release being deployed, so a fix only takes effect with the release that contains it.

## Repo hygiene

- `ollima.txt` and `ollastack.txt` in the repository root hold live provider keys. They are
  git-ignored; never print or commit their contents.
- `.claude/settings.local.json` holds per-user permission rules. It is untracked and ignored.
- `.gitattributes` forces LF (`* text=auto eol=lf`), for the shell scripts and for Biome.
- On this Windows machine, Python's default encoding is cp1252. Pass `encoding="utf-8"` when
  reading or writing files from scripts, and set `PYTHONIOENCODING=utf-8` when printing non-ASCII.
