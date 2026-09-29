# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

The whole ChatGPT-style chat application, which will grow into an AI tutor. There is **one
repository, and each commit is one release** of both halves:

- `backend/`: FastAPI API on PostgreSQL 16 + pgvector (the only datastore). It has its own Python 3.12 venv, ruff and pytest.
- `frontend/`: Next.js 14 web app with its server-side proxy (BFF). It's a Bun + Turborepo workspace:
  `apps/app`, `packages/ui`, `tooling/typescript`. `frontend/CLAUDE.md` has the frontend detail;
  Claude Code loads it when you work there.

They are two processes, tested together and deployed from the same commit of `main`: production
runs both from one checkout, and a deploy rebuilds and restarts only the half a commit changes
(`docs/deployment.md`). There is one deploy command for both; don't add per-half deploy commands.

History:
- The frontend was a separate repository (`sunny436/AI-Tutor-Webapp-frontend`). It was imported with
  its history into `frontend/`, and that repository is no longer used.
- The backend formerly held an Ayurveda chatbot; that code is only at the tag `ayurveda-baseline`.
- Remotes: `origin` is `sunny436/AI-Tutor-Webapp` (push `main` there; no PRs); `ayurveda` is the old Ayurveda repo.

## Architecture guardrail: web-first, not web-only

PadhAI is built for the web today; the platform under it must serve future iOS, Android, tablet
and desktop clients without a rewrite. The web app (with its BFF) is the API's first client, not
the architecture. Priorities: correctness, security, reliability, maintainability, scalability,
performance, simplicity.

- **Durable data and rules live in the API** (routers → services/repositories → PostgreSQL). Browser
  storage is for UI state only; user preferences belong in `/v1/me/settings`. A client may mirror a
  rule for UX; the API enforces it.
- **APIs model resources, not screens.** `/v1` changes are additive; anything breaking gets a new
  endpoint or version while old clients still need the old one (`docs/api-contract.md`, "Compatibility").
- **Authorization is per user, in the API.** Never rely on a client, or on the BFF allowlist.
- **Web-only mechanisms stay at the client layer:** the BFF, cookies, CSP, layout, `PREVIEW_FEATURES`.
- **Don't** build other clients, add cross-platform abstractions, or refactor working code for
  scalability alone; make the smallest safe change. The web-derived assumptions a native client would
  need resolved first are listed in `docs/architecture.md`, "Clients".
- **Enforced by tests:** contract sync (`export_openapi.py --check`, `routes.test.ts`), dependency
  direction (`test_architecture_guards.py`), per-user isolation (`test_authorization.py`). The rest
  is review.

## Commands

From the repository root (the implementation is `scripts/run.mjs`, a thin runner over each half's own tools):

```sh
bun run setup | dev | dev:backend | dev:frontend       # dev: Docker db + migrations, API :4000 + web :3000
bun run test          # backend pytest + frontend typecheck + unit tests (incl. the API contract test)
bun run test:e2e      # Playwright + axe against an API on :4100 with the fake LLM (starts it from backend/)
bun run lint | build | contract                        # contract: regenerate docs/openapi.json + frontend check
git push origin main && bun run deploy   # production: GitHub main -> production, only what changed
bun run smoke         # after every deploy: the live site as the owner (headed Chrome + emulated phones)
bun run rollback | status                 # previous commit the same way | GitHub main vs production (MATCH)
bun run verify        # the three CI jobs in a Linux container: needs Docker, so not on this PC (owner's rule)
bun run lock:backend  # after editing backend/requirements.txt: regenerate the hashed requirements.lock
bun run rehearse      # optional: the deploy scripts on a throwaway systemd container (Docker, ~30 min)
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
- **Backend tests:** they need a PostgreSQL + pgvector and Mailpit, which the development PC no
  longer has (no Docker, owner's rule). Don't set them up; see "The owner's hard rules". Where
  they run, they drop, recreate and migrate their own `aichat_test` database (the name **must**
  end in `_test`), truncate tables before each test, and use a fake LLM, fake embeddings and an
  in-memory mailbox.
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

Never let the browser call the API, and never hand the token to page code. Future native clients will
call a published API directly, never the BFF (`docs/architecture.md`, "Clients").

**One contract.** `docs/openapi.json` is generated from the backend (`backend/scripts/export_openapi.py`).
The frontend's `routes.test.ts` reads that file and fails if a proxied route or request field no
longer exists. Change both halves in the same commit, then run `bun run contract`; CI checks that the
file is current. A new endpoint for the browser must also be added to `routes.ts`.

**Backend internals.**
- **Composition root:** `backend/app/main.py` `create_app(settings, *, llm, email_sender, embeddings)`
  wires everything; tests inject fakes through it. `Settings.validate_for_env()` refuses unsafe
  production values.
- **A chat turn** (`app/chat/service.py`): *prepare* runs in the request transaction (conversation,
  409 if a reply is already streaming, quotas, user message + assistant placeholder, and the student's
  learning context, which `app/learning/tutor.py` turns into instructions after the frozen system
  prompt: every learning setting, including academic year and study time, plus a "Learning so far"
  line (streak and today's activity, `app.progress.learning.tutor_progress`) once they have learnt;
  it is read before the question is counted, so the Settings preview shows exactly this. Nothing set
  and nothing learnt means no instructions). *Generate* runs
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

- **How a commit goes live:** `git push origin main`, then `bun run deploy` (`deploy/deploy.sh`):
  - it refuses unless this checkout is clean and exactly GitHub `main` (fetched now); no PRs, and
    GitHub CI is advisory (never waited for; `bun run status` shows it);
  - it pushes the commit to the production Git repository `/opt/aichat/app.git` (the host has no
    GitHub access), then runs `deploy/server/update.sh` (from this checkout's `deploy/`) on the
    host as a detached systemd unit under a lock (a second deploy stops: "another deploy is running").
- **What update.sh does:** `git reset --hard` of the production checkout `/opt/aichat/app`, then
  content keys (git objects of each part's files, tests excluded, `deploy/server/lib.sh`) decide
  what runs:
  - pip install only when `requirements.lock` changed; bun install only when a `package.json` or
    `bun.lock` changed (the venv and `node_modules` are reused);
  - the frontend is built **beside** the served build (`NEXT_DIST_DIR=.next-build`, Next's cache in
    `.next-cache`) and swapped in; the build it replaced stays as `.next-prev`, so going back is a
    swap without a build; a failed build never reaches users;
  - backup + `alembic upgrade head` only when migrations are pending; restart only the API (backend
    changed) and/or only the web app (frontend changed); docs/tests-only commits restart nothing;
  - local smoke: both units active, API `/health` + `/ready`, web `/login`, web -> API -> database.
  - It prints GitHub main, the production checkout, the backend and frontend running SHAs, and
    `MATCH` or `MISMATCH`; any failure is `STOP:` and a non-zero exit, never reported as success.
- **Release identity:** the checkout's `RELEASE` file; the API's `/health` and the web app's
  `/api/health` (loopback only) report the commit each process started from. A part that did not
  change keeps running an older commit with identical code (still MATCH).
- **Pinned runtimes:** `.node-version` (the web app runs on Node, not Bun's runtime: Bun does not
  signal a client disconnect, which breaks stop-on-leave), `.bun-version`, `backend/requirements.lock`.
- **Jobs worker:** `aichat-jobs.timer` runs `python -m app.jobs` once a minute from the checkout: the
  email outbox (at most once), reminders, retention. It ships installed but NOT enabled, and student
  email follows `NOTIFICATIONS_MODE` (default `off`); enabling either is an owner decision
  (`docs/deployment.md`, "Jobs worker").
- **Rollback:** `bun run rollback [-- <commit>]` deploys the previous (or a named) commit the same way;
  status says MISMATCH until main is deployed again. Details in `docs/deployment.md` and `docs/rollback.md`.
- **Host:** Ubuntu 24.04 VM `10.1.30.37` (`ssh root@10.1.30.37`). The public site `ayur.namahos.com`
  goes through a Cloudflare Tunnel to web `127.0.0.1:3000`. The API is on `127.0.0.1:4100` (4000 is
  dev), and PostgreSQL is Docker on `127.0.0.1:5432`.
- **Secrets:** only in `/etc/aichat/{api,web,postgres}.env` (mode 600), never touched by a deploy.
  Load them for one-off commands with `systemd-run --pipe --wait --collect -p EnvironmentFile=/etc/aichat/api.env ...`;
  don't `source` them.
- **The database is outside the checkout:** `/opt/aichat/shared/postgres`. Its Compose project and
  volume names are pinned (`compose` / `compose_pgdata`); moving or renaming them would start an
  empty database. Migrations must be backward compatible (a rollback runs older code on the newer schema).
- **Status:** the first deploy of this model moves production from the release layout
  (`/opt/aichat/current` -> `releases/<commit>`, since 2026-09-25) to `/opt/aichat/app`, and leaves
  `releases/` in place. Leftovers kept until the owner approves their removal: `releases/`, the old
  checkouts `/opt/aichat/{backend,frontend}`, `/root/aichat-bundles`, saved units `aichat-*.before-*`,
  the legacy Ayurveda services; don't touch them. Production changes need the owner's explicit approval.
- **Known hazard until the legacy Ayurveda stack is removed:** its `convex.service` (enabled) runs
  `docker compose up -d --remove-orphans` in a Compose project that is also named `compose`, the
  project of the live Postgres. Any start of it (a reboot, `systemctl restart convex`, or starting
  `convex-backup.service`, which `Requires=` it) removes `compose-postgres-1` as an "orphan"
  (the data volume survives; recover with `systemctl restart aichat-postgres`). Don't reboot the host
  or start either unit; after any reboot, check `docker ps` for `compose-postgres-1` first.
  Removing the legacy stack (archive first) awaits the owner's go-ahead.
- **Never, by hand:** edit files in `/opt/aichat/app`, run migrations outside a deploy, `git clean`
  there, `docker compose down -v`, or change `API_BASE_URL` in `web.env` (the frontend's default
  `:4000` is the old API on that host).
- **Changing the deploy scripts:** try it with `bun run rehearse` (optional, local); the host runs
  the deploying checkout's `deploy/` scripts, so a fix takes effect with the next deploy.

## The owner's hard rules (2026-09-29): production, testing and release

These override anything else in this file. They are quoted exactly.

> **PRODUCTION RULE:** Keep production simple and deterministic — Git main is the source of truth; deploy the exact verified commit to the server, build/run directly on the production VM, and keep frontend/backend versions strictly matched. No unnecessary containers, infrastructure layers, or deployment complexity; use system services/process supervision, health checks, backups, and rollback capability. After every release: verify the exact commit is live, services are healthy, and no stale/old release is serving traffic.

> **TESTING / WORK RULE:** Minimum safe code, maximum output — no Docker, no local setup, no unnecessary refactor, no test-suite expansion, no time/token waste; only check obvious build/runtime breakage. Commit/push to Git main and deploy directly to production, ensuring production runs the exact final main commit. Finish in one pass; report only what is actually live.

What they mean here:
- **Strictly matched** = `Status: MATCH`: the backend and the frontend both run the production
  checkout's code. A part whose code did not change keeps running (content keys, owner's choice);
  that is still MATCH.
- **No containers beyond the one that exists.** PostgreSQL's pinned Compose project is the only
  container in production. Nothing new runs in Docker, and there is no Docker on the development PC
  (removed 2026-09-29; never reinstall or ask). So there is no local Postgres or Mailpit, and the
  backend pytest suite, Playwright and `bun run verify` do not run here.
- **Checks are only for obvious build/runtime breakage.** Before committing:
  - backend: `ruff check` and `ruff format --check`, plus a Python import/compile check (and a
    pure-function script when logic changed);
  - frontend: `bun run typecheck`, `bun run lint`, `bun run test` and `bun run build`;
  - `bun test deploy/tests` when deploy scripts changed.
  - Don't add tests or refactor.

Every task, in one pass:
1. **Implement:** minimum safe code; reuse what exists; no new dependencies, services or
   abstractions; no scope creep; no subagents unless the owner asks.
2. **Check** as above. A failure is fixed, never shipped.
3. **Push:** commit on `main`, then `git push origin main` (`origin` is the owner's GitHub repo). No
   pull requests, no branches. GitHub CI is advisory and never waited for.
4. **Release:** `bun run deploy` (it deploys exactly GitHub `main`). It must end with
   `Status: MATCH`.
5. **Verify live:**
   - `bun run status`: MATCH, services healthy, and no stale release serving traffic (it fails if
     the legacy ports 4000/3210/3211/6791 listen);
   - `bun run smoke`: every check PASS;
   - a live check of what changed.
   - If anything fails: stop, fix, or `bun run rollback`. Never declare success.
6. **Report only what is actually live:** the final deployed SHA, MATCH, the smoke result, what was
   proven live, and what was not.

## Repo hygiene

- `ollima.txt` and `ollastack.txt` in the repository root hold live provider keys. They are
  git-ignored; never print or commit their contents.
- `.claude/settings.local.json` holds per-user permission rules. It is untracked and ignored.
- `.gitattributes` forces LF (`* text=auto eol=lf`), for the shell scripts and for Biome.
- On this Windows machine, Python's default encoding is cp1252. Pass `encoding="utf-8"` when
  reading or writing files from scripts, and set `PYTHONIOENCODING=utf-8` when printing non-ASCII.
