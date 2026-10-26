# Testing

> Verified at commit `0e33ec0` (2026-10-26) against `scripts/run.mjs`, `.github/workflows/ci.yml`,
> `frontend/apps/app/playwright.config.ts`, `playwright.smoke.config.ts`, `backend/tests/` and `deploy/tests/`.

## Contents

- [The layers](#the-layers)
- [What each layer needs](#what-each-layer-needs)
- [Commands](#commands)
- [End-to-end tests](#end-to-end-tests)
- [The production smoke](#the-production-smoke)
- [CI](#ci)
- [Writing a test](#writing-a-test)
- [Known baseline](#known-baseline)

## The layers

| Layer | What it proves | Where |
|---|---|---|
| Backend tests (pytest) | API behaviour against a real PostgreSQL + pgvector: auth, isolation, chat, RAG, files, voice, the question bank, migrations, architecture rules | `backend/tests/` (40 files) |
| Web app unit tests (`bun test`) | Pure logic: the proxy, cookies, the SSE parser, the chat store, renderers, settings models, the voice scheduler | `frontend/apps/app/src/**/*.test.ts(x)` |
| Contract tests | The API contract is current, and every route and request field the web app proxies exists in it | `backend/scripts/export_openapi.py --check`; `src/lib/api/routes.test.ts`, `contract.gen.test.ts` |
| Deploy gate tests | The deploy scripts' pure parts: content keys, the CI gate, CI parity | `deploy/tests/*.test.mjs` |
| End to end (Playwright + axe) | The real built web app, proxy, API and database together, in browsers, with accessibility checks | `frontend/apps/app/e2e/` (25 specs) |
| Visual regression | Screenshots compared with stored baselines (recorded on Windows, so they run there) | `e2e/visual-regression.e2e.ts` and its `-snapshots/` folder |
| Production smoke | The live site, after each deploy, as the QA account | `frontend/apps/app/smoke/` |

## What each layer needs

| Layer | Needs |
|---|---|
| Unit, contract (frontend), typecheck, lint, build | Bun 1.3.14 and the workspace installed (`bun install --frozen-lockfile` in `frontend/`). The build runs on Node 24 |
| Backend tests | `backend/.venv` (`bun run setup`), plus **PostgreSQL 16 with pgvector and Mailpit**. Locally that's `docker compose -f docker-compose.dev.yml up -d`; CI has them as services |
| End to end | All of the above, plus a Playwright browser (`bunx playwright install chromium`, and `webkit` for the Safari projects) |
| Production smoke | The QA account's credentials (`SMOKE_EMAIL`/`SMOKE_PASSWORD`, or `dummy_account.txt`) and the live site |

> **On the owner's development PC** there is no Docker (the owner's rule), so the backend tests and the e2e suite
> don't run there; CI runs them. Checks on that PC are: `ruff check`, `ruff format --check` and an import check
> for the backend; `bun run typecheck`, `lint`, `test` and `build` for the frontend; and `bun test deploy/tests`
> when the deploy scripts change.

## Commands

From the repository root:

| Command | Runs |
|---|---|
| `bun run test` | Backend pytest, then the frontend typecheck and unit tests, then the deploy gate tests. All steps run, and it fails at the end if any failed |
| `bun run lint` | `ruff check`, `ruff format --check`, then Biome |
| `bun run build` | The contract check, then the frontend production build |
| `bun run contract` | Regenerate `docs/openapi.json` and `contract.gen.ts`, then run the contract tests |
| `bun run test:e2e` | The Playwright suite (below) |
| `bun run verify` | The three CI jobs, locally, in a Linux container (needs Docker) |

Directly:

| Where | Command |
|---|---|
| `backend/` (Windows) | `.venv\Scripts\python -m pytest -o addopts="" -ra` (all), `… -k streak` (by name), `… "tests/test_chat.py::test_logs_never_contain_the_question_or_document_text"` (one) |
| `backend/` (Linux, macOS) | `.venv/bin/python -m pytest -o addopts="" -ra` |
| `frontend/` | `bun run typecheck`, `bun run lint`, `bun run test` |
| `frontend/apps/app/` | `bun test src/lib/api/sse.test.ts` (one file), `bun test ./src -t "stop"` (by name) |

When piping test output (`| tail`), check the exit code separately: pipes hide failures.

## End-to-end tests

`bun run test:e2e` (or `bun run test:e2e` in `frontend/apps/app`):

- **The web app:**
  - a production build in `.next-e2e`, served on `:3100` by `e2e/serve.mjs` on Node (production's runtime);
  - a second build with preview features on `:3101`;
  - a throwaway Better Auth secret, and Better Auth's per-IP limit off (every test comes from one address; the
    per-account limits stay on).
- **The API** on `:4100`: an API already running there is reused, otherwise it is started from `backend/`. Its
  settings are:
  - `LLM_PROVIDER=fake` (replies `You said: …`, with a small delay so Stop can be tested);
  - test-sized limits;
  - `VOICE_MODE=on` with `VOICE_PROVIDER=fake`;
  - a throwaway internal token.
- **Codes** are read from Mailpit (`:8025`). Test addresses use `@example.com`.
- **Safety:** `global-setup.ts` refuses any non-loopback API or Mailpit URL, so the suite can never touch
  production.
- **Browser projects:**

| Project | Device | Specs |
|---|---|---|
| `desktop` | Desktop Chrome | every spec except the mobile and preview ones |
| `mobile` | Pixel 7 | `*mobile.e2e.ts` |
| `preview` | Desktop Chrome on the preview build | `preview.e2e.ts` |
| `webkit` | Desktop Safari | `settings-workspace.e2e.ts` |
| `webkit-mobile` | iPhone 14 | `settings-mobile.e2e.ts` |

**The specs:**
- sign-in and accounts (`auth`);
- the chat (`chat-home`, `chat-polish`, `chat-polish-mobile`, `streaming`, `failures`, `journey`);
- Settings (`settings`, `settings-layout`, `settings-workspace`, `settings-mobile`);
- the streak (`streak`) and voice (`voice`, `voice-barge-in`);
- layout and look (`responsive`, `mobile`, `motion`, `design-system`, `visual`, `visual-regression`);
- accessibility (`accessibility`) and security (`security`);
- regressions (`regression`) and preview gating (`gated`, `preview`).

**Useful options:**
- `E2E_BACKEND_DIR=none` never starts the API (one must already be running);
- `E2E_SKIP_BUILD=1` reuses the last build;
- `bun run test:e2e e2e/journey.e2e.ts -g "journey"` runs one test.

All the variables are in [environment-variables.md, "Tests"](environment-variables.md#tests).

## The production smoke

`bun run smoke`, after every deploy. It signs in once as the QA account in a visible browser, then checks the
live site:
- the new chat and its greeting's contrast;
- the sidebar, composer, menus, the bell and the streak;
- Settings;
- a 320 px window, and motion;
- one real question, whose chat it then deletes;
- the same layout checks on an emulated iPhone (WebKit) and Android phone;
- dark mode on each page.

It ends by signing out.

It writes as little as it can:
- the question counts toward today's learning day;
- marking notifications read is intercepted;
- nothing in Settings is saved.

Every check prints PASS or FAIL, and any FAIL means the release isn't done ([deployment.md, "After every deploy"](deployment.md#after-every-deploy-bun-run-smoke)).

## CI

`.github/workflows/ci.yml` runs on every push. **It is advisory:** a deploy never waits for it, and `bun run
status` shows its verdict.

| Job | Steps |
|---|---|
| **Backend (lint, contract, tests)** | Install the locked dependencies (hashes verified) and the dev tools; ruff; `export_openapi.py --check`; pytest against the PostgreSQL + pgvector service |
| **Frontend (typecheck, lint, tests incl. contract, build)** | `bun install --frozen-lockfile`; typecheck; lint; unit tests; deploy gate tests; the production build on the pinned Node |
| **Integration (end-to-end)** | PostgreSQL and Mailpit services; the backend from the lock, migrated; Playwright with Chromium and WebKit; `bun run test:e2e` |

## Writing a test

- **Prefer the layer closest to the rule:**
  - a pure function gets a unit test;
  - an API rule gets a pytest against the real database;
  - a user flow gets an e2e spec.
- **Use the fakes:**
  - the fake LLM echoes `You said: <message>`;
  - the fake embeddings measure shared vocabulary only, so they prove plumbing, not relevance;
  - the in-memory mailbox holds codes in backend tests, and Mailpit holds them in e2e.
- **A new endpoint for the browser** needs its `routes.ts` entry and a regenerated contract (`bun run contract`).
  `routes.test.ts` fails otherwise.
- **Test databases' names must end in `_test`**; the backend fixtures drop and recreate them.
- **Owner's rule for changes:** run the checks for obvious build and runtime breakage, and don't expand the test
  suite without the owner's say ([CLAUDE.md](../CLAUDE.md), "The owner's hard rules").

## Known baseline

What `bun run status` reported for CI on `main`:

| Date | Commit | Verdict |
|---|---|---|
| 2026-10-22, 2026-10-23 | the releases of those days | **Backend (lint, contract, tests): failure** |
| 2026-10-26 | `0e33ec0` | **Integration (end-to-end): failure**: 190 passed and 1 failed, WebKit `settings-workspace.e2e.ts` "resizing across 768px keeps you where you are" (a navigation interrupted another). At `eedcb67`, a different test in the same spec failed (axe at 767px), so it looks like a flaky Settings spec. The Backend and Frontend jobs didn't fail |

The 2026-10-22/23 failures were observed, not investigated; the 2026-10-26 one was read from the CI log, not fixed. They didn't block releases, because CI is advisory. Check the current
verdict with `bun run status` before assuming a red job is yours.
