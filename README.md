# PadhAI: AI Tutor

**Your Questions. Your Tutor. Your Way.**

PadhAI is an AI tutor for school students in India, Classes 6–12, following CBSE and the NCERT textbooks. A student
asks a doubt in a chat, and the tutor explains it step by step: with maths, chemistry, tables and diagrams, and
with citations to the NCERT pages it used. Around the chat:
- tests come from a stored question bank, never invented by the model;
- the student's practice record turns into a daily plan;
- a streak and study time show steady work.

**Who uses it:**
- **Students:** for doubts, practice before exams, revision, and help with their own notes and worksheets.
- **The owner, Networkers Home:** runs it as one web application at one public address, built so that native apps
  can use the same API later.

**This repository is the whole application:**
- the web app, in `frontend/`;
- the API, in `backend/`;
- its deployment, in `deploy/`;
- its documentation, in `docs/`.

One commit of `main` is one release of both.

[![A tutor answer: steps, maths and NCERT sources](docs/screenshots/desktop/tutor-answer.png)](docs/screenshots/README.md)

<sub>The live site on 2026-10-26, signed in as a test account. Its name and email are replaced, and other chats
are blurred: [how the screenshots were made](docs/screenshots/README.md).</sub>

## Contents

1. [What PadhAI can do](#what-padhai-can-do)
2. [Screenshots](#screenshots)
3. [Architecture at a glance](#architecture-at-a-glance)
4. [Technology](#technology)
5. [Quick start](#quick-start)
6. [How a question is answered](#how-a-question-is-answered)
7. [Repository structure](#repository-structure)
8. [Configuration and secrets](#configuration-and-secrets)
9. [Testing and quality](#testing-and-quality)
10. [Deployment](#deployment)
11. [Documentation](#documentation)
12. [Contributing and project status](#contributing-and-project-status)
13. [Licence and acknowledgements](#licence-and-acknowledgements)

## What PadhAI can do

**Status key:**
- **On:** works by default.
- **Flag:** behind a setting; production's state, as reported on the date given.
- **Preview:** sample-data pages, never in production.

The full catalogue is [docs/features.md](docs/features.md).

| Area | What a student gets | Status |
|---|---|---|
| Chat | Answers streamed word by word, with Stop, Regenerate, Copy and feedback | On |
| Rich answers | Maths and chemistry (KaTeX), tables, study cards, diagrams, charts and flashcards | On |
| Textbook grounding | Answers from the NCERT books for Classes 6–12, the student's own class and subjects first, with page citations | On when configured (configured in production) |
| A tutor that fits the student | Class, board, goals, subjects and preferences shape every answer; Settings previews what the tutor is told | On |
| Tests in the chat | "Test me on…" gives stored questions that adapt to each answer, marked by the database | On |
| My Learning | Today's plan, revisions due, mastery, mistakes and recent tests | On |
| Streak and study time | Learning days in India time, celebrations, and estimated active study time | On |
| Own files | PDF, Office files, CSV, text and images (OCR in English and Hindi) that the tutor reads and cites | On |
| Voice mode | Talk with the tutor and hear the answer (English) | Flag `VOICE_MODE` (on, 2026-10-26) |
| Study scope | Keeps the tutor to learning, and redirects unrelated requests | Flag `STUDY_SCOPE` (on, 2026-10-26) |
| Intent router | Tailors each answer to the kind of help asked for | Flag `INTENT_ROUTER` (on, 2026-10-26) |
| Sign-in | Email code or password, Google, two-step sign-in, a breached-password check | On (the adaptive CAPTCHA isn't configured in production) |
| Homework Helper, Summarizer | Sample-data pages | Preview |

Verified gaps are listed in [docs/known-limitations.md](docs/known-limitations.md).

## Screenshots

| Desktop | Phone |
|---|---|
| [![New chat](docs/screenshots/desktop/new-chat.png)](docs/screenshots/desktop/new-chat.png)<br/>A new chat with the week's greeting | [![New chat on iPhone](docs/screenshots/mobile/new-chat.png)](docs/screenshots/mobile/new-chat.png)<br/>The same on an iPhone |
| [![My Learning](docs/screenshots/desktop/my-learning.png)](docs/screenshots/desktop/my-learning.png)<br/>My Learning: today's plan and revisions | [![Answer on iPhone](docs/screenshots/mobile/tutor-answer.png)](docs/screenshots/mobile/tutor-answer.png)<br/>An answer with a table and sources |
| [![Voice mode](docs/screenshots/workflows/voice-mode.png)](docs/screenshots/workflows/voice-mode.png)<br/>Voice mode | [![Navigation drawer](docs/screenshots/mobile/drawer.png)](docs/screenshots/mobile/drawer.png)<br/>The navigation drawer |

All 20 screenshots, with how each was masked, are in [the gallery](docs/screenshots/README.md).

## Architecture at a glance

```mermaid
flowchart LR
  S[Student's browser] -->|"same origin only: pages, /api/v1/*, /api/auth/*"| W
  subgraph W["Web app: frontend/ (Next.js on Node, port 3000)"]
    P[Pages]
    B["Proxy (BFF)<br/>allowlist, Origin check,<br/>adds the session token"]
    BA["Sign-in<br/>(Better Auth)"]
  end
  B -->|"Bearer token, loopback only"| A["API: backend/<br/>(FastAPI, port 4100 in production)"]
  BA -->|identity tables| DB
  A --> DB[("PostgreSQL 16 + pgvector<br/>the only datastore")]
  A --> LLM["Model providers<br/>(OpenAI-compatible: Ollima, OpenRouter fallback)"]
  A --> NC["NCERT Knowledge Service<br/>(separate; through its API)"]
  A --> OL["OllaLink<br/>(classifiers and speech)"]
  A --> EM["Email<br/>(SMTP or Ollastack)"]
```

- **The browser never calls the API.** The web app's server checks each request against an allowlist, adds the
  session token from an httpOnly cookie, and forwards it. The token never reaches page code.
- **The API enforces every rule.** It checks the session and that the data belongs to the student, and keeps all
  data in PostgreSQL. That includes the vectors for search and students' files.
- **One server runs both** under systemd, behind a Cloudflare Tunnel. A deploy rebuilds and restarts only the part a
  commit changed.

The reference is [docs/architecture.md](docs/architecture.md), and the trust boundaries are in
[docs/security.md](docs/security.md).

## Technology

These are the exact versions from the lockfiles and pin files at this commit.

| Part | Technology | Why it is here |
|---|---|---|
| Web app | **Next.js 15.5.27**, **React 19.3.0**, TypeScript 5.7.3 | Pages, plus the server routes that form the proxy and sign-in |
| UI | Tailwind CSS 3.4.17, Radix UI (`packages/ui`), Noto Sans | Accessible components, light and dark themes |
| Answers | react-markdown, KaTeX 0.18.7 (with mhchem), Mermaid 12.0.0 | Maths, chemistry, tables and diagrams, sanitised first |
| Sign-in | **Better Auth 1.7.7**, node-postgres | Email codes, passwords, Google, two-step sign-in |
| Runtimes | **Bun 1.3.14** (`.bun-version`), **Node.js 24.19.0** (`.node-version`) | Bun installs and runs tasks; the web server runs on Node, as Bun doesn't signal a client disconnect |
| Workspace | Turborepo 2.1.1, Biome 1.8.3, Playwright 1.63.0 | Builds, lint and format, browser tests |
| API | **Python 3.12**, **FastAPI 0.141.1**, uvicorn 0.53.0, Pydantic 2.13.5 | The HTTP API, typed settings and schemas |
| Database access | SQLAlchemy 2.0.54 (async), asyncpg 0.31.0, Alembic 1.20.0 | Async queries, hand-written migrations |
| AI | LangGraph 1.2.12, langchain-core 1.6.4, the OpenAI SDK 2.54.0 (for OpenAI-compatible providers), httpx 0.28.1 | The chat turn graph, retrieval, model and embedding calls |
| Data | **PostgreSQL 16 + pgvector** (`pgvector/pgvector:pg16`) | Everything: accounts, chats, progress, files, vectors |
| Production | Ubuntu 24.04, systemd, Cloudflare Tunnel | One host, no other infrastructure |

The backend's dependencies are pinned with hashes in `backend/requirements.lock`, and the web app's in
`frontend/bun.lock`.

## Quick start

**You need:**
- Git;
- Python 3.12;
- Bun 1.3.14;
- Node.js 24;
- Docker, for the local PostgreSQL and Mailpit.

```sh
git clone <the repository URL> && cd <the folder>
bun run setup     # backend/.venv and its packages, backend/.env from the example, frontend packages
```

Then set the local settings (the full steps, and why each is needed, are in the
[beginner guide](docs/beginner-guide.md)):

- `backend/.env`: `LLM_PROVIDER=fake`, `EMBEDDING_PROVIDER=fake`, and `AUTH_INTERNAL_TOKEN=<32+ random characters>`;
- `frontend/apps/app/.env.local`:
  - `AUTH_DATABASE_URL=postgresql://aichat:aichat@127.0.0.1:5432/aichat`;
  - `BETTER_AUTH_SECRET=<32+ random characters>`;
  - the same `AUTH_INTERNAL_TOKEN`.

```sh
bun run dev       # PostgreSQL + Mailpit (Docker), migrations, then the API on :4000 and the web app on :3000
```

| Open | You should see |
|---|---|
| http://localhost:3000 | The sign-in page. Create an account; the code arrives in Mailpit |
| http://127.0.0.1:8025 | Mailpit, the local inbox |
| http://127.0.0.1:4000/health | `{"status": "ok", "release": "development", "files": "available"}` |
| http://127.0.0.1:4000/docs | The API's interactive docs (development only) |

With the fake model, every answer is `You said: …`, streamed word by word. That is success. For real answers, set
`LLM_PROVIDER=openai_compatible` and `LLM_PRIMARY_API_KEY`. When something fails, see
[docs/troubleshooting.md](docs/troubleshooting.md).

## How a question is answered

1. **The browser** sends the question to the web app's own `/api/v1/chat/stream`.
2. **The proxy** checks it:
   - the route is allowlisted;
   - the `Origin` is the site's own;
   - the body is JSON, at most 64 KB;
   - the session cookie's signature is valid.

   Then it forwards the question to the API with the token.
3. **The API** checks the session and the quotas. It saves the question and an empty reply, and reads the
   student's learning settings and progress.
4. **JEV** (optional):
   - the study scope filter asks whether this is something PadhAI helps with;
   - the intent router asks what kind of help is wanted.

   These are short classification calls, capped in time, and they never fail a turn.
5. **Retrieval** searches the NCERT textbooks (or the knowledge base) and the student's attached files. It starts
   while JEV is still reading the message, and it never fails a turn.
6. **The model** writes the answer from the instructions, the passages and the chat so far: one call, streamed
   back word by word as Server-Sent Events.
7. **The API** saves the finished reply with its sources. If the student asked for a test, it swaps in stored
   questions first. Then it updates the learning day and the streak.

Step by step, with diagrams: [docs/request-lifecycle.md](docs/request-lifecycle.md). The AI pipeline:
[docs/ai-architecture.md](docs/ai-architecture.md).

## Repository structure

```text
.
├── backend/                 the API: FastAPI app (app/), migrations (alembic/), tests (tests/), scripts (scripts/)
├── frontend/                the web app: a Bun + Turborepo workspace
│   ├── apps/app/            Next.js: pages (src/app), features (src/features), API client and proxy (src/lib), e2e tests
│   ├── packages/ui/         shared UI components
│   └── tooling/typescript/  shared TypeScript settings
├── deploy/                  production: deploy, status and rollback scripts, systemd units, env templates
├── docs/                    documentation, screenshots and the API contract (openapi.json)
├── qbank/                   the question bank's source content
├── scripts/run.mjs          the task runner behind `bun run …`
├── self-hosted/             an optional error collector (described, not deployed)
├── docker-compose.dev.yml   local PostgreSQL + pgvector and Mailpit
└── package.json             the repository's commands (no dependencies; the workspace is frontend/)
```

Every module, with what it does: [docs/codebase-map.md](docs/codebase-map.md).

## Configuration and secrets

**Where settings live:**
- **The API** reads `backend/.env`. In production it reads `/etc/aichat/api.env`.
- **The web app** reads `frontend/apps/app/.env.local`. In production it reads `/etc/aichat/web.env`.
- **Every setting**, with its default and who reads it: [docs/environment-variables.md](docs/environment-variables.md).

**Rules for secrets:**
- **Never commit or print a secret.** `.env` files and the local key files are git-ignored.
- **Production's secrets exist only on the server**, in files readable by root alone. A deploy never touches them.
- **Production refuses to start with unsafe values**, such as a development secret or a missing internal token
  (`Settings.validate_for_env`).
- How secrets, sessions, uploads and AI risks are handled: [docs/security.md](docs/security.md). To report a
  vulnerability, see [SECURITY.md](SECURITY.md).

## Testing and quality

```sh
bun run lint       # ruff (check + format) for the API, Biome for the web app
bun run test       # API tests (PostgreSQL + Mailpit needed), web typecheck and unit tests, deploy script tests
bun run build      # is docs/openapi.json current? then the web app's production build
bun run contract   # regenerate the API contract, then the web app's contract tests
bun run test:e2e   # Playwright + axe, against a local API with the fake model
```

**CI** runs three jobs on every push to `main`:
- Backend (lint, contract, tests);
- Frontend (typecheck, lint, tests, build);
- Integration (end-to-end).

CI is advisory: a deploy never waits for it. At `0e33ec0` (2026-10-26), `bun run status` reported the Integration
job as failing. That was observed but not investigated ([docs/testing.md](docs/testing.md#known-baseline)). Test layers, and what
each needs: [docs/testing.md](docs/testing.md).

## Deployment

Production is one Ubuntu server. It runs the web app and the API under systemd from one checkout of `main`, behind
a Cloudflare Tunnel. Releases are made by the owner, or with the owner's approval:

```sh
git push origin main && bun run deploy   # GitHub main -> production; rebuilds and restarts only what changed; ends "Status: MATCH"
bun run status                           # GitHub main against production, each part's commit, health: MATCH or MISMATCH
bun run smoke                            # after every deploy: the live site, signed in as the QA account (desktop and phones)
bun run rollback                         # the previous commit, the same way
```

How it works and what it checks: [docs/deployment.md](docs/deployment.md) and [docs/rollback.md](docs/rollback.md).
Health, logs and runbooks: [docs/operations.md](docs/operations.md). The host's layout:
[INFRASTRUCTURE.md](INFRASTRUCTURE.md).

## Documentation

| If you are | Start with |
|---|---|
| New to PadhAI | [Start here](docs/start-here.md), [beginner guide](docs/beginner-guide.md), [glossary](docs/glossary.md), [troubleshooting](docs/troubleshooting.md) |
| A developer | [Architecture](docs/architecture.md), [codebase map](docs/codebase-map.md), [web app](docs/frontend-architecture.md), [API](docs/backend-architecture.md), [request lifecycle](docs/request-lifecycle.md), [API reference](docs/api-reference.md), [data model](docs/data-model.md), [adding a feature](docs/adding-a-feature.md) |
| An AI engineer | [AI architecture](docs/ai-architecture.md), [retrieval](docs/rag.md), [question bank](docs/question_bank.md) |
| An operator | [Deployment](docs/deployment.md), [operations](docs/operations.md), [rollback](docs/rollback.md), [environment variables](docs/environment-variables.md) |
| Reviewing security | [Security](docs/security.md), [SECURITY.md](SECURITY.md) |
| Contributing | [CONTRIBUTING.md](CONTRIBUTING.md), [CLAUDE.md](CLAUDE.md), [decisions](docs/decisions.md), [known limitations](docs/known-limitations.md) |

Everything, by audience: [the docs hub](docs/README.md).

## Contributing and project status

- **Status:** live in production and developed actively. Milestones are in [CHANGELOG.md](CHANGELOG.md), plans in
  [ROADMAP.md](ROADMAP.md), and verified gaps in [docs/known-limitations.md](docs/known-limitations.md).
- **How to contribute:** [CONTRIBUTING.md](CONTRIBUTING.md). The working rules, including the owner's rules for
  production and testing, are in [CLAUDE.md](CLAUDE.md).
- **History:**
  - this repository began as the backend of an Ayurveda chatbot, which is kept only at the tag
    `ayurveda-baseline`;
  - the web app was a separate repository until it was imported, with its history, into `frontend/`;
  - [docs/production-migration.md](docs/production-migration.md) records how production moved off the old stack.

## Licence and acknowledgements

**Copyright © 2026 Networkers Home. All rights reserved.** This is proprietary software, and it is not open
source: see [LICENSE.md](LICENSE.md).

Third-party components keep their own licences. Two are bundled in this repository:
- the starter template the web app began from (MIT);
- the Noto Sans font (SIL Open Font License).

Their notices are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Every dependency is listed with its version
in `frontend/bun.lock` and `backend/requirements.lock`.
