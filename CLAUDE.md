# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

The whole ChatGPT-style chat application, which will grow into an AI tutor. There is **one
repository, and each commit is one release** of both halves:

- `backend/`: FastAPI API on PostgreSQL 16 + pgvector (the only datastore). It has its own Python 3.12 venv, ruff and pytest.
- `frontend/`: Next.js 15 (React 19) web app with its server-side proxy (BFF). It's a Bun + Turborepo workspace:
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
  - `eval_tutor_record.py`: does the model USE the practice-test and exercise record the app gives it (synthetic
    records, real model, pass-rate gate)? Run it on the host (`systemd-run ... -p EnvironmentFile=/etc/aichat/api.env`)
    after any change to what the tutor is told. A fact in the prompt is not a fact the model uses: on 2026-10-01 a
    finished test was in the prompt and 26 of 30 replies were still wrong ("you haven't finished", "I can't see"
    your results").
  - `migration_status.py`: schema vs code, as JSON.
  - `eval_intents.py`: the intent router on synthetic cases (`tests/fixtures/intent_cases.jsonl`), with the
    release gates and the latency of each request and of both together; `--sweep` on the dev split chooses
    `INTENT_MIN_CONFIDENCE` and `INTENT_MIN_GROUP_CONFIDENCE`, the test split runs once with both frozen;
    `--probe` (dev split) compares the compact option texts with the owner's long criteria, `--replay` on the
    host (the real tutor). It prints ids and numbers only.
  - `eval_scope.py`: the study scope filter on synthetic cases (`tests/fixtures/scope_cases.jsonl`): false
    rejections and false acceptances apart; `--sweep` on the dev split, the test split once; ids and numbers only.
  - `import_questions.py ../qbank`: the question bank (`docs/question_bank.md`); dry run by default, `--apply`
    writes (one transaction; production only with the owner's approval). `qbank_coverage.py`: real counts per topic.

## How the halves connect

**Browser → BFF → API.**
- The browser only ever calls its own origin, `/api/v1/*`.
- `frontend/apps/app/src/lib/server/proxy-core.ts` forwards the allowlist in `lib/api/routes.ts` to
  `API_BASE_URL`, which is server-only. It adds `Authorization: Bearer <token>`; the token comes from
  Better Auth's httpOnly cookie `__Host-padhai_session`, whose HMAC signature it verifies first.
- **Sign-in is Better Auth** (`frontend/apps/app/src/lib/auth`, `/api/auth/*`, an exact allowlist of
  routes; docs/architecture.md "Identity" in "Clients", docs/deployment.md "Sign-in"): email-first
  sign-up (a code, then a password), password and email-code sign-in, Google, reset and change,
  two-step sign-in (TOTP + recovery codes, asked for at every way in), an adaptive CAPTCHA
  (Turnstile) and a breached-password check (HIBP, k-anonymity). It
  writes `users`/`auth_sessions`/`auth_accounts`/`auth_verifications` as role `aichat_auth`, never
  returns a token to page code, and asks the API's loopback `/internal/auth/*` (shared
  `AUTH_INTERNAL_TOKEN`) to email codes and security notices. The API finds each session by its
  token's SHA-256, requires a verified address, and owns devices, email change and deletion.
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
- **Composition root:** `backend/app/main.py` `create_app(settings, *, llm, email_sender, embeddings, intents)`
  wires everything; tests inject fakes through it. `Settings.validate_for_env()` refuses unsafe
  production values.
- **A chat turn** (`app/chat/service.py`): *prepare* runs in the request transaction (conversation,
  409 if a reply is already streaming, quotas, user message + assistant placeholder, and the student's
  learning context, which `app/learning/tutor.py` turns into instructions after the frozen system
  prompt: every learning setting, including academic year and study time, plus a "Learning so far"
  line (streak, today's activity, and the header's countdown: whether today counts yet and the time
  left in the India learning day; `app.progress.learning.tutor_progress`) once they have learnt;
  it is read before the question is counted, so the Settings preview shows exactly this; a
  regenerated answer leaves its own question out of today's count. Nothing set and nothing learnt
  means no instructions. Notification settings (daily reminder, streak warning, weekly summary,
  sign-in alerts, in-app reminders) decide delivery only and never reach the tutor). *Generate* runs
  as an independent asyncio task registered in `app/chat/streams.py`. It runs the LangGraph graph
  `receive_query → retrieve_context → assemble_context → generate_answer` (`app/rag/graph.py`), emits
  SSE `meta`/`token`/`done`/`error`, and persists the result. Stop and disconnect cancel the task.
- **Tests in the chat come from the question bank** (`app/qbank/chat_tests.py`, `QUESTION_BANK_TESTS`): the
  tutor names a chapter (or up to three, a mock test) in a ```question-bank block, the server swaps in stored
  questions (SQL) before the reply is saved, and `app/assessments` grades them; no model writes, picks or
  checks a question. A test is a practice set in the ledger (`qb_sets` mode `chat`) and is adaptive
  (`ADAPTIVE_CHAT_TESTS`, a kill switch: off = fixed tests): each answer (`app/chat/router.py`, one
  transaction under the reply's row lock) is recorded in the ledger, brings the next question chosen from
  it (`selection.pick_next`), and counts toward the learning day (5 answers make one). The practice record
  (`app/progress/practice.py`, `GET /v1/progress/plan|mastery|revisions|mistakes|practice-tests|practice-topics`)
  is read from the ledger, survives deleting the chat, and reaches the tutor as one "Practice record" line.
  The tutor's own fill-in-the-blanks exercises are graded but never evidence. The model never sees an exercise's
  answer key in the chat history (`assessments.for_model`), and an unanswered one is told to it as having no score.
  One it writes without its fence (a `:::fill-blank` card, bare JSON, a json block, or a card's plain text
  with `[[blanks]]`) is put in a ```fill-blank fence before the reply is saved (`chat_tests.fill`), or the
  student would read the answer key.
- **One model call per turn:** there are no graph retries, and `FallbackProvider` switches providers
  only before the first token. `INTENT_ROUTER` (off by default) adds up to two short classification requests
  before it (Ollalink, `app/intents`): they write no text, are capped together by `INTENT_ROUTER_TIMEOUT_S`,
  are never retried and never fail a turn. While they run (about 1.1 s from the server: 141 ms of network
  each, Ollalink serves one request at a time), the graph's own search already runs (`graph.prefetch`, the
  same search: an intent can only turn it off), so the router adds only its time beyond the search.
  `STUDY_SCOPE` (off by default) adds one more request of its own, the same way, before both.
- **Intent router** (`app/intents`, `INTENT_ROUTER=off|shadow|on`): Ollalink's classification model reads
  which of the owner's 46 intents (`taxonomy.py`, `TAXONOMY_VERSION`) a new message asks for, one question per
  request: the group, then only that group's intents (fixed option texts of at most 80 characters; no second
  request for `other` or a group below `INTENT_MIN_GROUP_CONFIDENCE`). Applied only when P(group) is at least
  `INTENT_MIN_GROUP_CONFIDENCE` and P(group) x P(intent | group) at least `INTENT_MIN_CONFIDENCE`. An applied intent
  adds a "What the latest message asks for" line after the student's settings (`resolve_assistant_config(intent=)`);
  test intents get the bank's chapters (`chat_tests.menu(asked=True)`); `performance_analysis` and
  `study_schedule` search nothing. An explicit "hint only" (English, Hindi, Hinglish) is always `hint_only`,
  with or without the classifier and in every mode, `off` included (a fixed rule, never a reading: a hint asked for by name,
  only the next step, or wanting to solve it themselves with asking how to begin). A regenerated reply reuses its intent;
  shadow records without applying. While students use the app, signed-in requests nudge the classifier
  (`OLLALINK_WARM_AFTER_S`, `ClassifierWarmMiddleware`): one small warm-up after a quiet spell, so the next message is not slow.
  Stored in `messages.metadata.intent` (internal), logged as metadata only.
- **Study scope filter** (`app/intents/scope.py`, `STUDY_SCOPE=off|shadow|on`): is a new message something
  PadhAI helps with? Its own Ollalink request through the router's client (one choice question: study,
  support, unclear, mixed, unrelated), never an intent. Fixed rules first (small talk, "hint only", bare
  files). `on`: a policy paragraph after the frozen prompt on every turn; `REDIRECT` (P(unrelated) ≥
  `SCOPE_MIN_REDIRECT`, never in a chat with a test or an exercise: reason `practice`) is the app's own
  reply with no model, search, learning day or title; other decisions
  add one conditional line; a failure is the tutor with the policy. Stored in `messages.metadata.scope`.
- **Voice mode** (`app/voice`, `VOICE_MODE=off|qa|on`, `VOICE_QA_EMAILS`; `features/voice` in the web app): the
  browser records each utterance (its own VAD), the API transcribes it with OllaLink (`gpu-transcribe`, batch:
  realtime is a WebSocket the BFF cannot carry), the words go to the chat as `mode: "voice"` (one prompt line,
  an `expression` SSE event from scope + Jev), and the reply is read aloud sentence by sentence (OllaLink TTS,
  `hadley`; no TTS streaming), its first chunk ending at its first pause, in the smallest audio the browser
  decodes (Ogg Opus, AAC, MP3: found by decoding a clip). `VOICE_ACK` (off|qa|on) says a pre-recorded word
  (`public/voice/ack-*`) when the student stops. `VOICE_PARALLEL_ROUTING` starts scope, JEV and search together
  on voice turns (the same decisions); `VOICE_SERVER_SPEECH` has the server speak a reply's first words
  (`app/voice/first_speech.py`, the stream's `speech` event). English only: OllaLink speaks no Hindi, so it is for
  English/unset tutor languages. Every voice route checks the rollout and the language itself; nothing is stored.
  The BFF gives voice routes their own bounded class (`voice: true`, 24 at once), never behind the 2-slot file queue.
  Latency measured 2026-10-26 (the end of speech to the answer's first word, P50 7.0 s, n=20): the tutor's first
  token (scope + JEV + search ~1.9 s, the LLM ~1.3 s) and the first sentence's TTS dominate.
- **Retrieval never fails a turn:** it is skipped or fails with a reason code. Small talk that opens a chat
  ("hi": `is_meaningful`) searches nothing; a short follow-up ("why?") is searched with the question before it.
- **Context budget** (`app/rag/context.py`): system prompt → latest message → whole chunks up to
  `RAG_MAX_CONTEXT_CHARS` → history up to `LLM_MAX_INPUT_CHARS`.
- **RAG** (`docs/rag.md`): `PgVectorRetriever` → `KnowledgeStore` → pgvector HNSW; or, when
  `NCERT_KB_BASE_URL` + `NCERT_KB_API_KEY` are set, `NcertRetriever` (`app/rag/ncert.py`): the separate
  NCERT Knowledge Service (`ncert-kb-api` :4200, repository `sunny436/graphrag`) through its API only,
  vector mode, Classes 6-12 only (`SERVED_CLASSES`), the student's class and subjects ranked first here, follow-ups searched with the
  question before them (`search_query_for`). Its own data and releases; never read its tables.
  - Every search is scoped by `AccessScope(user_id)`: global sources plus the user's own.
  - Retrieval options come only from `resolve_assistant_config` (`app/chat/assistant.py`), which is
    the seam for tutor features.
  - The embedding dimension is fixed at **1536** in three places, kept in sync by a test.
  - Changing the model or dimension needs a migration plus a re-ingest.
- **Files** (`app/files`, `docs/rag.md` "Files the student attached"): the File Library, 100 MB per
  student, bytes in PostgreSQL (`user_file_blobs`). One worker in the API process reads uploads
  (PostgreSQL leases; it recovers and self-tests after start, in the background); untrusted bytes are
  parsed only by `python -m app.files.extract` in a sandboxed systemd transient unit (production) and
  the API process never imports a parser. A turn reads only its conversation's attached, owned, ready
  files, inside the latest user message. No files setting may stop the API: `/health` says `"files"`.
  Host check: `backend/scripts/sandbox_probe.py`.
- **Enforced by `tests/test_architecture_guards.py`:**
  - routers never import `app.rag` or pgvector;
  - `app/chat/*` imports only `app.rag.graph`;
  - `graph.py` depends on abstractions only;
  - `app/db/*` and `store.py` never import LangChain or LangGraph;
  - no GraphRAG, Chroma, Pinecone, Weaviate or Qdrant.
- **Cross-cutting:**
  - one error envelope `{"error": {code, message, requestId}}`;
  - JSON logs that never contain message or document text, or keys;
  - identity on Better Auth (web) + per-request checks here; per-account limits in `auth_attempts`
    under an advisory lock (`app/auth/service.py` `_throttle`, `frontend/.../lib/auth/guard.ts`);
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
- **Host:** Ubuntu 24.04 VM `10.1.50.94` (`ssh root@10.1.50.94`). The public site `ayur.namahos.com`
  goes through a Cloudflare Tunnel to web `127.0.0.1:3000`. The API is on `127.0.0.1:4100` (4000 is
  dev), and PostgreSQL is Docker on `127.0.0.1:5432`.
- **Secrets:** only in `/etc/aichat/{api,web,postgres}.env` (mode 600), never touched by a deploy.
  Load them for one-off commands with `systemd-run --pipe --wait --collect -p EnvironmentFile=/etc/aichat/api.env ...`;
  don't `source` them.
- **The database is outside the checkout:** `/opt/aichat/shared/postgres`. Its Compose project and
  volume names are pinned (`compose` / `compose_pgdata`); moving or renaming them would start an
  empty database. Migrations must be backward compatible (a rollback runs older code on the newer schema).
- **Status:** production runs only the checkout model (`/opt/aichat/app`). The owner removed
  every leftover on 2026-09-29 (11:46-12:05 UTC, by hand): the legacy Ayurveda services and Convex
  (units, containers, the `compose_data` volume, images), `/opt/ayurveda`, `/etc/ayurveda`,
  `/opt/aichat/{releases,current,backend,frontend}`, `/root/aichat-bundles` and the `aichat-*.before-*`
  units. Before it: a `pg_dump` (`/var/backups/aichat/aichat-2026-09-29-114626.dump`). The Ayurveda
  archive (32 Convex exports, `/etc/ayurveda` with its secrets, the vector-store backups, the unit
  files) is kept OFF the host, on the owner's PC: `Desktop\ayurveda-archive-2026-09-29.tgz`; the
  Ayurveda code is the `ayurveda` remote and the tag `ayurveda-baseline`. Docker now runs only
  `compose-postgres-1` (volume `compose_pgdata`). Production changes need the owner's explicit approval.
- **Never, by hand:** edit files in `/opt/aichat/app`, run migrations outside a deploy, `git clean`
  there, `docker compose down -v`, or change `API_BASE_URL` in `web.env` (production's API is
  `:4100`; the frontend's built-in default `:4000` is the development port).
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

- `ollima.txt`, `ollastack.txt` and `openrouter.txt` in the repository root hold live provider keys.
  They are git-ignored; never print or commit their contents.
- `.claude/settings.local.json` holds per-user permission rules. It is untracked and ignored.
- `.gitattributes` forces LF (`* text=auto eol=lf`), for the shell scripts and for Biome.
- On this Windows machine, Python's default encoding is cp1252. Pass `encoding="utf-8"` when
  reading or writing files from scripts, and set `PYTHONIOENCODING=utf-8` when printing non-ASCII.
