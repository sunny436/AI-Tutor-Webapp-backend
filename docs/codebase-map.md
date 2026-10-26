# Codebase map

> Verified at commit `0e33ec0` (2026-10-26). The module tables below are generated from each file's own leading
> docstring or comment, so they say what the code says about itself. Regenerate them, rather than hand-editing,
> when files move.

## The repository at a glance

```text
.
├── backend/                  FastAPI chat API (Python 3.12)
│   ├── app/                  the application: one package per domain (tables below)
│   ├── alembic/versions/     hand-written migrations 0001–0017
│   ├── scripts/              command-line tools: contract export, ingestion, evaluations, question import, probes
│   ├── tests/                the pytest suite (40 test files) and fixtures
│   ├── requirements.txt      dependency ranges; requirements.lock (hashed, Linux and Python 3.12) is what production installs
│   └── run_backend.bat       start the API on Windows (the database must already be up)
├── frontend/                 Bun + Turborepo workspace (install here, never at the root)
│   ├── apps/app/             the Next.js web app: src/, e2e/ (Playwright), smoke/ (production smoke), scripts/
│   ├── packages/ui/          design system: tokens (globals.css), Tailwind config, Radix-based components
│   └── tooling/typescript/   shared TypeScript configs
├── deploy/                   the one deploy: deploy.sh, rollback.sh, status.sh, server/ (runs on the host),
│                             systemd/ (units), env/*.example, compose/ (the PostgreSQL container),
│                             cloudflared/ (tunnel template), rehearsal/, verify/ (CI in Docker), tests/
├── docs/                     this documentation; openapi.json (generated API contract)
├── qbank/                    the question bank's source files (manifest/, content/), imported by
│                             backend/scripts/import_questions.py
├── scripts/run.mjs           the task runner behind `bun run <task>`
├── self-hosted/glitchtip/    optional self-hosted error tracker (Sentry protocol). Not deployed
├── docker-compose.dev.yml    local PostgreSQL 16 + pgvector and Mailpit
├── package.json              root scripts only (no dependencies, no workspaces)
├── .node-version, .bun-version   pinned runtimes (Node 24.19.0, Bun 1.3.14)
└── CLAUDE.md                 project rules, commands and production notes (for Claude Code and people)
```

## Entry points

| What | Entry point |
|---|---|
| The API | `backend/app/main.py`, `create_app` (run by uvicorn with `--factory`) |
| The jobs worker | `backend/app/jobs/__main__.py` (`python -m app.jobs`) |
| The file extractor | `backend/app/files/extract.py` (`python -m app.files.extract`, sandboxed) |
| The web app | `frontend/apps/app/src/app/layout.tsx` and the route folders under `src/app/` |
| The browser-to-API proxy | `frontend/apps/app/src/app/api/v1/[...path]/route.ts`, then `src/lib/server/proxy-core.ts` |
| Sign-in | `frontend/apps/app/src/app/api/auth/[...all]/route.ts`, then `src/lib/auth/` |
| Every repository command | `scripts/run.mjs` (`bun run setup`, `dev`, `test`, …) and `deploy/*.sh` |

## Where the tests are

| Tests | Location |
|---|---|
| Backend unit and integration | `backend/tests/test_*.py` (PostgreSQL required) |
| Backend architecture rules | `backend/tests/test_architecture_guards.py` |
| Web app unit | `frontend/apps/app/src/**/*.test.ts(x)` |
| End to end (browser) | `frontend/apps/app/e2e/*.e2e.ts` |
| Production smoke | `frontend/apps/app/smoke/` |
| Deploy scripts | `deploy/tests/*.test.mjs` |

## Backend modules (`backend/`)


### `app/appearance/`

| File | What it is |
|---|---|
| `app/appearance/router.py` | GET/PATCH /v1/me/appearance: how the app looks for this user, on every device. |

### `app/assessments/`

| File | What it is |
|---|---|
| `app/assessments/__init__.py` | Practice tests in a tutor's reply, recorded by the server (app/assessments/state.py). |
| `app/assessments/state.py` | Practice tests and exercises: what the tutor writes into a reply for the student to answer, graded and recorded by the server (docs/api-contract.md, "Practice … |

### `app/auth/`

| File | What it is |
|---|---|
| `app/auth/avatar.py` | Profile photos: validated, resized and re-encoded on the server. |
| `app/auth/dependencies.py` | Who is calling. Identity comes ONLY from a server-verified session token. |
| `app/auth/devices.py` | What a signed-in device may show about itself: a coarse label and a masked address. |
| `app/auth/emails.py` | Outgoing email: SMTP (Mailpit locally) or the Ollastack Agent Mail API; memory in tests. |
| `app/auth/internal.py` | What the web app's Better Auth (frontend/apps/app/src/lib/auth) asks the API to do after it acts: send a sign-in or reset code, and raise the security notices. … |
| `app/auth/retention.py` | What auth keeps, and for how long. Run every hour by the API itself (app/main.py), so it never depends on the jobs worker; the worker (python -m app.jobs) runs … |
| `app/auth/router.py` | – |
| `app/auth/schemas.py` | – |
| `app/auth/security.py` | Password hashing (argon2id), session tokens and one-time email codes. |
| `app/auth/service.py` | Account and session logic. All state lives in PostgreSQL. |

### `app/chat/`

| File | What it is |
|---|---|
| `app/chat/assistant.py` | What the assistant is for a given turn: prompt, retrieval options and model. |
| `app/chat/router.py` | – |
| `app/chat/schemas.py` | – |
| `app/chat/service.py` | The chat core. |
| `app/chat/streams.py` | Server-Sent Events encoding and the registry of in-flight generations. |
| `app/chat/teaching.py` | The tutor's teaching defaults: how it answers, explains, corrects mistakes and gives hints. |
| `app/chat/titles.py` | Chat titles, ChatGPT-style: a few words naming the topic, set once from the first answered question. |

### `app/conversations/`

| File | What it is |
|---|---|
| `app/conversations/repository.py` | Conversation and message queries. EVERY query is scoped by the owning user id. |
| `app/conversations/router.py` | – |
| `app/conversations/schemas.py` | – |

### `app/db/`

| File | What it is |
|---|---|
| `app/db/base.py` | – |
| `app/db/models.py` | PostgreSQL schema: the single source of truth for all application data. |
| `app/db/session.py` | Async engine and session factory (SQLAlchemy 2 + asyncpg). |

### `app/`

| File | What it is |
|---|---|
| `app/email_html.py` | The HTML part of PadhAI's emails: one branded layout and a few blocks, everything escaped. |
| `app/errors.py` | Typed application errors and the single JSON error envelope. |
| `app/health.py` | – |
| `app/logging.py` | Structured JSON logging with a per-request id. |
| `app/main.py` | Application factory. |
| `app/middleware.py` | Pure ASGI middleware: request id, access log and request body size limit. |
| `app/ratelimit.py` | A per-key sliding-window limit, kept in this process's memory. |
| `app/schemas.py` | Shared API schema base: JSON is camelCase on the wire, snake_case in Python. |
| `app/settings.py` | Configuration, read from the environment (and `.env` in development). |

### `app/files/`

| File | What it is |
|---|---|
| `app/files/__init__.py` | The File Library: user files, their processing, and what chat may attach (docs/rag.md). |
| `app/files/extract.py` | Text extraction for one uploaded file. Runs ONLY as a separate, sandboxed process. |
| `app/files/processing.py` | Turning uploaded files into text the tutor can use: one background worker in the API process. |
| `app/files/router.py` | /v1/files: the student's File Library (docs/api-contract.md, "Files"). |
| `app/files/schemas.py` | – |
| `app/files/service.py` | File Library rules: what may be uploaded, how much, by whom, and what chat may attach. |

### `app/greetings/`

| File | What it is |
|---|---|
| `app/greetings/refresh.py` | The weekly refresh of the study greetings by the LLM (app-level: one pool for everyone). |
| `app/greetings/router.py` | The study greetings above a new chat's composer: app-level, not per user. |

### `app/intents/`

| File | What it is |
|---|---|
| `app/intents/__init__.py` | The intent router: which of the owner's 46 intents a student's message asks for (taxonomy.py), read by Ollalink's classification model (classifier.py) and … |
| `app/intents/classifier.py` | What a student's latest message asks for, read by Ollalink's classification model. |
| `app/intents/scope.py` | Study scope: is the student's latest message something PadhAI helps with (STUDY_SCOPE)? |
| `app/intents/taxonomy.py` | The tutor's intents: the one action a student's latest message asks PadhAI to perform now. |

### `app/jobs/`

| File | What it is |
|---|---|
| `app/jobs/__main__.py` | `python -m app.jobs`: one run of the jobs worker (app/jobs/runner.py), then exit. |
| `app/jobs/runner.py` | One run of the jobs worker. `python -m app.jobs` runs it once and exits; the systemd timer aichat-jobs.timer starts it every minute … |

### `app/learning/`

| File | What it is |
|---|---|
| `app/learning/catalog.py` | The academic catalog: the values a learner profile may use (GET /v1/catalog/academic). |
| `app/learning/context.py` | The Learning domain's public reads: what the tutor may know about a student (their settings, and how they are doing: TutorProgress, read by … |
| `app/learning/router.py` | – |
| `app/learning/schemas.py` | Learning API models. JSON is camelCase; codes are checked against the catalog by the service. |
| `app/learning/service.py` | Learning: the learner profile, subjects and learning preferences. Every query is scoped by the calling user's id; nothing here can read or write another user's … |
| `app/learning/tutor.py` | What a student's settings add to the tutor's instructions: one pure, deterministic function. |

### `app/llm/`

| File | What it is |
|---|---|
| `app/llm/base.py` | The LLM abstraction: one protocol, typed errors, provider-neutral data types. |
| `app/llm/factory.py` | – |
| `app/llm/fake.py` | A deterministic provider for tests, CI and offline development. Never used in production. |
| `app/llm/fallback.py` | Try providers in order until one starts streaming. |
| `app/llm/openai_compatible.py` | Any OpenAI-compatible chat-completions API (Ollima, OpenRouter, OpenAI, vLLM, ...). |

### `app/notifications/`

| File | What it is |
|---|---|
| `app/notifications/alerts.py` | Security notices, raised by the internal auth events (app/auth/internal.py) after the web app's Better Auth signed someone in or changed how they sign in. |
| `app/notifications/emails.py` | The text of every notification email: plain text, short, and never anything the reader did not already know about their own account. No IP addresses (only a … |
| `app/notifications/inbox.py` | The in-app notifications behind the header's bell. |
| `app/notifications/outbox.py` | The email outbox: how the API asks for an email to be sent to a student or to support. |
| `app/notifications/reminders.py` | Reminder emails, planned by the worker every minute and queued at most once per period. |
| `app/notifications/router.py` | – |
| `app/notifications/schemas.py` | – |
| `app/notifications/sender.py` | Sends the email outbox: at most once, within each row's `send_before`, as the rollout allows. |
| `app/notifications/tokens.py` | Unsubscribe links that work without signing in, and cannot be forged or aimed elsewhere. |

### `app/progress/`

| File | What it is |
|---|---|
| `app/progress/activity.py` | Active time and questions per day: the Progress domain's writes, and its notion of "today". |
| `app/progress/learning.py` | The learning streak: the one place its rules live. |
| `app/progress/practice.py` | The practice record: what a student's answers to question-bank tests say about their learning (GET /v1/progress/plan, /mastery, /revisions, /mistakes, … |
| `app/progress/router.py` | – |
| `app/progress/schemas.py` | – |
| `app/progress/service.py` | Progress summaries: today, this week, the streak and the student's goals. |

### `app/qbank/`

| File | What it is |
|---|---|
| `app/qbank/__init__.py` | The question bank: stored, reviewed CBSE-pattern MCQs for Classes 6-12, and the practice sets and tests that serve them (docs/question_bank.md). Questions are … |
| `app/qbank/chat_tests.py` | Practice tests in the chat come from the question bank, never from the model. |
| `app/qbank/importer.py` | Importing the bank's text files (qbank/) into PostgreSQL: one transaction, all or nothing, safe to rerun. |
| `app/qbank/selection.py` | Serving stored questions: tests, adaptive practice sets, answers, results and coverage. |
| `app/qbank/validate.py` | Reading and checking the bank's text files (qbank/: manifests and JSONL content) before import. |

### `app/rag/`

| File | What it is |
|---|---|
| `app/rag/context.py` | Assemble the LLM input under one deterministic character budget. |
| `app/rag/embeddings.py` | Embeddings behind LangChain's `Embeddings` interface. |
| `app/rag/errors.py` | Typed RAG errors. `code` is safe to log and persist; messages never carry provider text or data. |
| `app/rag/graph.py` | The chat/RAG workflow as a LangGraph graph. |
| `app/rag/ingestion.py` | Ingestion: Document → parse → chunk → embed → PostgreSQL/pgvector. |
| `app/rag/ncert.py` | NCERT textbooks for the tutor: the NCERT Knowledge Service's search, as a LangChain retriever. |
| `app/rag/retriever.py` | LangChain retrievers over PostgreSQL/pgvector: the knowledge base, and files attached to a chat. |
| `app/rag/store.py` | Knowledge-base persistence and vector search (PostgreSQL + pgvector). |
| `app/rag/types.py` | Plain data shared across the RAG layer (no I/O, no framework imports). |

### `app/study/`

| File | What it is |
|---|---|
| `app/study/router.py` | – |
| `app/study/schemas.py` | – |
| `app/study/service.py` | Study time: sessions the student starts, pauses, resumes and ends, the active time credited inside them, and app presence. An estimate of studying, never proof … |

### `app/support/`

| File | What it is |
|---|---|
| `app/support/router.py` | POST /v1/support/requests: a signed-in student asks for help or reports a problem. |
| `app/support/schemas.py` | Support requests. What a student writes is stored and forwarded as plain text only. |

### `app/voice/`

| File | What it is |
|---|---|
| `app/voice/__init__.py` | Voice mode (VOICE_MODE): a student speaks, OllaLink's speech-to-text hears it, the tutor answers as for a typed message (app/chat), and OllaLink's … |
| `app/voice/expression.py` | The voice tutor's face on a turn, read from what the app already decided about the message: the study scope (app/intents/scope.py) and the intent router's … |
| `app/voice/policy.py` | Who voice mode is for, besides the rollout (VOICE_MODE): students whose tutor language is English or unset. OllaLink's speech output has no Hindi … |
| `app/voice/provider.py` | OllaLink speech for voice mode, English only. |
| `app/voice/router.py` | /v1/voice: voice mode's speech (docs/api-contract.md, "Voice"). |

### `scripts/`

| File | What it is |
|---|---|
| `scripts/eval_intents.py` | How well does the intent router read what students ask? Classify synthetic messages with Ollalink's model exactly as the app does (app/intents/classifier.py: … |
| `scripts/eval_retrieval.py` | Measure retrieval quality on your own labelled questions (to calibrate RAG_MIN_SCORE). |
| `scripts/eval_scope.py` | How well does the study scope filter (app/intents/scope.py) decide what PadhAI helps with? Read the labelled synthetic cases exactly as the app does (the fixed … |
| `scripts/eval_tutor_record.py` | Does the tutor use what the app records for it? Ask the configured model about practice tests and exercises, the way students ask, and score its replies. |
| `scripts/export_openapi.py` | Write (or check) the committed API contract at ../docs/openapi.json. |
| `scripts/import_questions.py` | Import the question bank's text files (qbank/) into PostgreSQL, or only check them. |
| `scripts/ingest_documents.py` | Ingest .md/.txt files into the knowledge base (PostgreSQL + pgvector), or delete one document. |
| `scripts/migration_status.py` | Where the database schema stands relative to THIS code's migrations. Prints one JSON line. |
| `scripts/qbank_coverage.py` | Coverage of the question bank, read from the database (read-only). |
| `scripts/sandbox_probe.py` | Check the file extractor sandbox on this host, with the exact properties production uses. |
| `scripts/smoke_chat.py` | Live smoke test of a RUNNING local API with the REAL LLM provider. |

## Web app modules (`frontend/apps/app/src/`)

Files with a leading description comment; components without one are named by their folder.


### `app/ (routes)`

| File | What it is |
|---|---|
| `app/(app)/(main)/(chat)/c/[conversationId]/page.tsx` | `/c/<id>` — an existing chat, rendered by the `(chat)` layout's ChatView. Conversation ids are UUIDs; anything else is a 404 before any request is mad |
| `app/(app)/(main)/(chat)/layout.tsx` | `/` and `/c/[conversationId]` share this layout, and the chat lives HERE rather than in the pages. Next.js keeps a layout mounted when navigating betw |
| `app/(app)/(main)/(chat)/page.tsx` | `/` — a new chat. Rendered by the `(chat)` layout's ChatView. |
| `app/(app)/(main)/homework/page.tsx` | Preview only: without PREVIEW_FEATURES=1 this page does not exist. |
| `app/(app)/(main)/layout.tsx` | The app: the chat, the learning tools and the help pages, inside the sidebar and header. |
| `app/(app)/(main)/summarizer/page.tsx` | Preview only: without PREVIEW_FEATURES=1 this page does not exist. |
| `app/(app)/settings/[section]/error.tsx` | A section that failed to render. Shown inside the workspace, so the other sections and Close still work; the root error page would replace everything. |
| `app/(app)/settings/[section]/layout.tsx` | An unknown section is a real 404. Checked HERE, above the section's loading boundary (loading.tsx): once that boundary streams, the response has alrea |
| `app/(app)/settings/[section]/loading.tsx` | While a section's page is on its way (a slow network), inside the workspace that stays put. |
| `app/(app)/settings/layout.tsx` | Settings is its own workspace, not a page of the app shell (that is `(main)/`). |
| `app/(app)/settings/page.tsx` | On a phone, the list of sections; wider, the first section (features/settings/settings-home.tsx). |
| `app/(auth)/layout.tsx` | Sign-in and sign-up. A visitor whose session is still valid goes straight to the app — decided here, where the session can actually be checked, rather |
| `app/api/account/password/route.ts` | `POST /api/account/password` {newPassword}: give an account its first password. The last step of signing up (the account exists once its email code is |
| `app/api/auth/[...all]/route.ts` | `/api/auth/*`: Better Auth (lib/auth). Only the routes in lib/auth/routes.ts reach it; every JSON answer leaves without its session token (page code n |
| `app/api/health/route.ts` | `/api/health`: the web server is up, and (to local callers only) the release it runs. Deploys and `bun run status` compare it with the API's `/health` |
| `app/api/v1/[...path]/route.ts` | `/api/v1/*` — the browser's only door to the chat API. All of the logic (and its tests) lives in `lib/server/proxy-core.ts`; this file only wires it t |
| `app/error.tsx` | A page failed to render; the app shell is fine. No digest, stack or status code: the reader needs a way forward, and the exception is in the console a |
| `app/global-error.tsx` | The last-resort screen: shown when the root layout itself failed to render. Two things make this file unlike every other page. 1. It REPLACES the root |
| `app/robots.ts` | A private chat app has nothing to index. Outside every route group so it is served at exactly `/robots.txt` (the middleware matcher skips it too). |
| `app/unsubscribe/page.tsx` | The link at the bottom of a reminder or alert email. Public (lib/server/gate.ts): it works signed in, signed out, or on a device that was never signed |

### `components/`

| File | What it is |
|---|---|
| `components/appearance-provider.tsx` | Null until known (the server's value, or its first load). |
| `components/auth-form.tsx` | Signing in and up, email codes and password reset, through Better Auth (lib/auth). The session cookie is set by the server; nothing here ever holds a |
| `components/brand/brand-mark.tsx` | The logo mark, from the one brand asset (see lib/brand.ts). Decorative: every place it appears names the product in text as well, so it carries no alt |
| `components/google-mark.tsx` | Google's "G", unaltered: its sign-in branding guidelines require the mark in Google's own colours (developers.google.com/identity/branding-guidelines) |
| `components/marquee-title.tsx` | Slide speed, the fade kept clear at the right edge, and the shortest cycle: slow enough to read. |
| `components/nav-items.ts` | The Learning Hub: every tool in the sidebar, in order, with the line under its name and the colours of its icon chip. The header reads the same list, |
| `components/preview-badge.tsx` | Says on screen that what sits beside it is not real yet: "Preview" on sample data, "Soon" on a control that does nothing yet. Only ever rendered with |
| `components/preview-context.tsx` | Whether preview UI may render (see lib/preview.ts). Decided on the server by the `(app)` layout and handed down, so a client component never reads the |
| `components/qr-code.tsx` | A QR code drawn as SVG paths from uqr's module matrix (no HTML string is ever injected: the encoded text, here an otpauth:// address with the student' |
| `components/service-unavailable.tsx` | The API could not be reached while loading the app. Shown instead of signing the user out: an outage is not a lost session (the old app conflated the |
| `components/theme-menu.tsx` | The app header's theme control: the current choice's icon, opening Light / Dark / System with a check on the one in use. The same choice and icons as |
| `components/theme-switcher.tsx` | The theme control. MOVED HERE from `(dashboard)/_components/`, because that is inside the authenticated route group and the component was mounted in e |
| `components/turnstile.tsx` | Cloudflare Turnstile, the CAPTCHA the sign-in form shows only after the server asked for one (CAPTCHA_REQUIRED: lib/auth/config.ts). The token goes to |
| `components/use-sign-out.ts` | Log out (the sidebar and the Settings panel). Unsaved edits are asked about FIRST: asking after signing out would leave "Stay" on a page whose session |
| `components/user-avatar.tsx` | The student's photo, or their initial: in the sidebar and in the Settings panel. Decorative. |
| `components/user-context.tsx` | The signed-in user, fetched once on the server by the app layout. Replaces the old app's five separate client queries for the same user. |

### `src/`

| File | What it is |
|---|---|
| `env.mjs` | Validated at build (next.config.mjs imports this file). The app builds with NO configuration at all: the API address defaults to the loopback address |
| `middleware.ts` | Page gating only. Real authentication happens in the API on every request; the app layout checks the session with `GET /v1/me`. See lib/server/gate.ts |

### `features/chat/`

| File | What it is |
|---|---|
| `features/chat/announcer.tsx` | What a screen reader hears about the conversation. One polite status region, announced at the moments that matter — not per token (a live region over |
| `features/chat/chat-context.tsx` | Creates the chat and conversation-list stores once per signed-in session and wires them together. Mounted by the app shell, so it survives navigation |
| `features/chat/chat-store.ts` | Client-side state for every open conversation — and nothing the server owns. The server is the source of truth for conversations and messages. This st |
| `features/chat/dictation.ts` | Dictation with the browser's own speech recognition (Web Speech API). No audio reaches AI Tutor: the browser's speech service turns speech into text, |
| `features/chat/empty-state.tsx` | What a new, empty chat shows above the composer: a small, quiet picture (study-illustration.tsx) and a study greeting picked at random from this week' |
| `features/chat/error-message.tsx` | A failure, shown as a failure — not dressed up as something the assistant said. Our own copy per error code, one recovery action, and the request id f |
| `features/chat/keyboard.ts` | Should this key press send the message? Enter sends; Shift+Enter is a newline. Enter while an input method is composing (Japanese, Chinese, Korean, Hi |
| `features/chat/plain-text.ts` | Roughly de-Markdown a reply for the screen-reader announcement. Only for `aria-live` text: the reply itself is rendered properly on screen and can be |
| `features/chat/smooth-text.ts` | A streaming reply shown at an even pace instead of in the bursts the network delivers. No invented delay: the text shown is always text that has arriv |
| `features/chat/streaming-indicator.tsx` | "The answer is on its way", before the first words arrive: three dots breathing in turn (opacity only, no bounce), and nothing else. Silent to screen |
| `features/chat/study-illustration.tsx` | The quiet picture above a new chat's greeting: an open book, a sprout of two leaves, three small sparkles. Drawn in the design tokens at low strength |
| `features/chat/use-dictation.ts` | One utterance per start (continuous off: predictable on phones too). Only the current session's events count, so a result arriving after a stop, a sen |
| `features/chat/use-stick-to-bottom.ts` | Within this many pixels of the bottom counts as "at the bottom". |

### `features/conversations/`

| File | What it is |
|---|---|
| `features/conversations/conversations-store.ts` | The sidebar's list of conversations: newest activity first, paged by cursor. The first page arrives with the page itself (fetched by the server layout |

### `features/files/`

| File | What it is |
|---|---|
| `features/files/attachment-store.ts` | Files attached to unsent messages, per chat, and their way to "ready". Lives beside the chat store (ChatProvider), not in the composer, so an upload k |
| `features/files/storage-full-dialog.tsx` | Shown when an upload is refused because the student's storage is full. Nothing is deleted for them. |

### `features/help/`

| File | What it is |
|---|---|
| `features/help/help-pages.tsx` | /help and /about. Plain server-rendered pages, written to be true of the app as it is today: when a feature changes, change its answer here in the sam |

### `features/learning-hub/`

| File | What it is |
|---|---|
| `features/learning-hub/demo-data.ts` | SAMPLE DATA for the preview UI — every placeholder in the app lives here. Nothing in this file is about the signed-in user or comes from the API. It i |
| `features/learning-hub/homework-view.tsx` | Homework Helper (preview): where a photo would go, and one worked example. |
| `features/learning-hub/summarizer-view.tsx` | Summarizer (preview): the input, and one summary of the kind it would make. |
| `features/learning-hub/tool-page.tsx` | The frame of a learning-tool page: its own scroll area (the shell does not scroll), a measure, and — first, above everything — the notice that what fo |

### `features/markdown/`

| File | What it is |
|---|---|
| `features/markdown/assessment.ts` | Practice tests on the client: which card a server record belongs to, and what a typed message means to the waiting test. Everything else (the question |
| `features/markdown/blocks.ts` | A reply's Markdown as independent blocks, and the safe-to-show part of a block still arriving. WHY BLOCKS. Parsing a reply (Markdown, maths, highlight |
| `features/markdown/citation.tsx` | The refs a reply cites in its prose (not inside code or maths), in order of first use. |
| `features/markdown/code-block.tsx` | Text types a download may be, by extension; anything else downloads as plain text. |
| `features/markdown/context.ts` | True only for the last block of a reply that is still streaming. Widgets that need their whole source (a diagram, a chart, a quiz) wait for it instead |
| `features/markdown/file-embed.tsx` | A text file's bytes as the tutor read them: a BOM means UTF-16; otherwise UTF-8, else Windows-1252. |
| `features/markdown/hast.ts` | Small helpers over the HTML syntax tree react-markdown renders from. Written out rather than pulled in: they are a few lines each. |
| `features/markdown/lazy-message-content.tsx` | The reply renderer, loaded on its own. react-markdown, the remark/rehype plugins, KaTeX and highlight.js are about 170 kB of gzipped JavaScript — abou |
| `features/markdown/message-content.tsx` | Renders a reply's Markdown — the model's raw output — safely. remark-gfm tables, strikethrough (~~double~~ only), task lists, autolinks remark-math $i |
| `features/markdown/remark-tutor.ts` | The tutor's study syntax, added to the one Markdown pipeline (message-content.tsx): :::type[Title] … ::: a study card; `::::` for an outer card around |
| `features/markdown/rich-block.tsx` | What every widget gets: its fence's source, and a way to give up (the code block shows instead, under `note` when the widget says why). |
| `features/markdown/sanitize-schema.ts` | What the Markdown renderer lets through. Starts from GitHub's sanitisation rules (`hast-util-sanitize` default schema) and narrows it: - links: `http` |
| `features/markdown/widgets/fill-blank.tsx` | ```fill-blank: an exercise the server keeps (app/assessments). The student types into the blanks and checks once; the server grades each blank (ignori |
| `features/markdown/widgets/mermaid-diagram.tsx` | mermaid's SVG with a fixed size (it says width="100%"), as an image URL. |
| `features/markdown/widgets/pdf-preview.tsx` | One page of a PDF at the width of the reply, drawn by pdf.js (the legacy build: the widest browser support). Its worker and the image decoders are pla |
| `features/markdown/widgets/tokens.ts` | Design tokens as concrete colours, for the libraries that draw themselves (Chart.js on a canvas, mermaid's theme): they cannot read `hsl(var(--x))`. R |

### `features/my-learning/`

| File | What it is |
|---|---|
| `features/my-learning/ask-in-chat.ts` | A request goes after unsent text, on its own line, never over it; the same request is not added twice (Back, then the same button again). |

### `features/navigation/`

| File | What it is |
|---|---|
| `features/navigation/app-return.ts` | Where "Close settings" goes: the last page of the main app this tab showed. Kept in sessionStorage, which is per tab (two tabs never mix; a duplicated |
| `features/navigation/leaving.ts` | Where the student is on their way to, while Next is still loading it. A signal, not routing: it never navigates, never blocks, never cancels. Its only |
| `features/navigation/navigation-guard-root.tsx` | Installs the unsaved-changes guard's listeners (navigation-guard.ts), once, in the signed-in layout, so they cover every page and outlive any one form |
| `features/navigation/navigation-guard.ts` | Unsaved edits are never lost by leaving without being asked, whichever way the student leaves. One registry of dirty forms (so one question per depart |
| `features/navigation/route-focus.ts` | Where keyboard and screen-reader focus goes when a whole view is replaced by a client-side navigation (the app and the Settings workspace swap each ot |

### `features/notifications/`

| File | What it is |
|---|---|
| `features/notifications/celebrate.ts` | "3" .. "9", then "9+": a badge that never grows wider than two characters. |

### `features/progress/`

| File | What it is |
|---|---|
| `features/progress/activity-chart.tsx` | A day's minutes; `questions` only where the chart shows them (Progress & Goals). |
| `features/progress/activity-heartbeat.tsx` | Active time in PadhAI (Settings > Progress & Goals): one heartbeat for the whole signed-in app. |
| `features/progress/session-keeper.tsx` | Keeps an active student signed in. Once per page load it asks Better Auth for the session; when the session is due (once a day) Better Auth extends it |
| `features/progress/use-activity-heartbeat.ts` | Reports active minutes while the student uses PadhAI (lib/activity.ts has the rule). Mounted once, in the signed-in app shell. A failed report is simp |

### `features/settings/`

| File | What it is |
|---|---|
| `features/settings/auto-saver.ts` | Saves toggle-style settings (appearance, notifications) as the user flips them. - **Batched:** changes made within `delay` ms go out as ONE versioned |
| `features/settings/heading-focus.ts` | A request, from the Settings workspace, to focus the next section heading that appears: the section being opened may still be loading when the request |
| `features/settings/learning-data.ts` | The academic catalog, fetched once per page load and shared by every section. |
| `features/settings/learning-labels.ts` | What each learning choice is called in the app. Every map is keyed by the contract's own enum (lib/api/contract.gen.ts), so a value the API adds is a |
| `features/settings/learning-model.ts` | Pure helpers for the learning forms: tested in learning-model.test.ts, no React. |
| `features/settings/notifications-section.tsx` | In the app (the header's bell: everything, reminders switchable) and by email (security and the reminders chosen here). Says plainly when this server |
| `features/settings/primitives.tsx` | The building blocks every Settings section uses, so they all look and behave alike: the section's own heading (`h2`, the app header owns the `h1`), ca |
| `features/settings/sections.ts` | Other words people search for (Settings > Search). Lower case. |
| `features/settings/settings-home.tsx` | Tailwind's `md`: the workspace shows the panel beside the section from here up. |
| `features/settings/study-tracking-section.tsx` | Settings > Study Tracking: what counts as study time, and the rules it follows. Nothing here is a control: the idle limits are the server's and the sa |
| `features/settings/use-auto-saver.ts` | A server resource saved as it is changed (see AutoSaver). `load` runs once on mount; while it runs, `value` is null. Failures are told with a toast in |
| `features/settings/use-unsaved-changes.ts` | While `dirty`, leaving loses the edit: the student is asked first, however they leave (a link, Close, search, log out, reload or closing the tab, the |
| `features/settings/workspace-context.tsx` | What the Settings workspace shares with its panel (settings-workspace.tsx). |

### `features/streak/`

| File | What it is |
|---|---|
| `features/streak/celebrations/goal-extended.tsx` | Animation 2, Daily Goal Completed + Streak Extended: the owner's asset (PadhAI Animation Gallery, `svgGoal`), its markup, timing and CSS unchanged; on |
| `features/streak/celebrations/palette.ts` | The owner's flame palette (PadhAI Animation Gallery) as design tokens (packages/ui/src/globals.css, where each one's colour is written down), for the |
| `features/streak/celebrations/queue.ts` | The streak celebrations' rules, kept pure so they can be tested without a page. What is celebrated comes only from the server: a finished reply's `don |
| `features/streak/celebrations/streak-lost.tsx` | Animation 4, Streak Lost: the owner's asset (PadhAI Animation Gallery, `svgLost`), its markup, timing and CSS unchanged; only the colours come from th |
| `features/streak/celebrations/streak-milestone.tsx` | Animation 3, Weekly Streak Milestone: the owner's asset (PadhAI Animation Gallery, `svgMilestone`), its markup, timing and CSS unchanged; only the col |
| `features/streak/celebrations/streak-started.tsx` | Animation 1, Streak Started: the owner's asset (PadhAI Animation Gallery, `svgStarted`), its markup, timing and CSS unchanged; only the colours come f |
| `features/streak/countdown.ts` | What is left of the learning day, for the header: "02h 14m", and in words for screen readers. |
| `features/streak/streak-store.ts` | The learning streak as the server reports it (GET /v1/progress/streak), shared by the header's badge and countdown and by Settings > Learning & Streak |

### `features/study/`

| File | What it is |
|---|---|
| `features/study/study-client.ts` | Study time, the client's part (pure, no React): what one page load observes and how it reports it. The server decides every second of credit (backend |
| `features/study/study-heartbeat.tsx` | Study time (Study Activity): this tab's observations, once for the whole signed-in app. |
| `features/study/study-store.ts` | The study session as this tab knows it: the server's state (the only source of study numbers: every second shown comes from it) plus this tab's own fa |
| `features/study/use-study-beat.ts` | Input that counts as activity: the library's defaults, but visibility is ours (hidden is not idle, it is not studying), and switching back to a tab mu |

### `features/unsubscribe/`

| File | What it is |
|---|---|
| `features/unsubscribe/token.ts` | What an unsubscribe link is for, read from its token only to word the page ("Stop daily study reminders?"). The token is `base64url("<user id>:<kind>" |
| `features/unsubscribe/unsubscribe-card.tsx` | One button, never automatic: mail scanners open links, and opening this page must not change anything. The API decides from the signed token; the kind |

### `features/voice/`

| File | What it is |
|---|---|
| `features/voice/audio-unlock.ts` | The audio voice mode plays through, made inside the student's click on the Voice button: browsers (Safari above all) only let sound start from a page |
| `features/voice/availability.ts` | Asked once per page: the API says whether voice mode is for this student (it checks every voice request too). |
| `features/voice/latex.ts` | A LaTeX formula as spoken English, the way a teacher reads school maths aloud: what voice mode says for `$…$` and `$$…$$` in a reply (speech-text.ts). |
| `features/voice/scheduler.ts` | One reply's speech, in order: its chunks (speech-text.ts) become audio one OllaLink request at a time, with the next one ready ahead, and play back to |
| `features/voice/speech-text.ts` | A reply as something to say: voice mode's spoken copy of the tutor's answer, made sentence by sentence while the answer is still being written. What t |
| `features/voice/tutor-face.tsx` | What the face is doing (listening, thinking, speaking), apart from its manner (`expression`). |
| `features/voice/use-voice-session.ts` | The voice session of the open voice view: started when it opens, ended when it closes, when the page is hidden or left (a phone locked, a tab switched |
| `features/voice/vad.ts` | When the student is speaking, from the microphone's level and how much of it is in the voice band. Every FRAME_MS: the frame's loudness (RMS of the sa |
| `features/voice/voice-session.ts` | One voice conversation in one chat. The microphone is listened to; each thing the student says is recorded, transcribed (OllaLink, through the API) an |

### `lib/`

| File | What it is |
|---|---|
| `lib/activity.ts` | When the app reports an active minute (POST /v1/progress/activity). The rule, also shown to students under Progress & Goals: PadhAI is open and visibl |
| `lib/appearance.ts` | Appearance (GET/PATCH /v1/me/appearance) as attributes on <html>, which the design tokens read (packages/ui/src/globals.css): `data-font-size`, `data- |
| `lib/brand.ts` | The product's brand, in one place. Everything that shows the brand reads it from here: the name in titles and copy, the two-tone wordmark ("Padh" + "A |
| `lib/fonts.ts` | Noto Sans, the product's one typeface (SIL Open Font License, src/fonts/noto-sans/OFL.txt), as variable fonts (every weight in one file). Served from |
| `lib/greeting.ts` | The study greeting above a new chat's composer: one of this week's pool from the API (`GET /v1/greetings`, app-level, the same pool for everyone, refr |
| `lib/legal.ts` | Terms and Privacy Policy links. Shown only once the owner publishes them and sets `NEXT_PUBLIC_TERMS_URL` / `NEXT_PUBLIC_PRIVACY_URL` in web.env (bake |
| `lib/preview.ts` | PREVIEW FEATURES: interface built ahead of its backend. The learning tools (homework, summaries), the leaderboard and the class/board line exist as UI |
| `lib/safe-redirect.ts` | Where to send someone after signing in — only ever somewhere inside this app. The previous check (`startsWith("/") && !startsWith("//")`) let `/\evil. |
| `lib/site.ts` | The public address of the app, for absolute metadata URLs. Set `NEXT_PUBLIC_SITE_URL` in production; the fallback exists for local runs. |
| `lib/time-zones.ts` | Time zones as people know them today. Browsers built on ICU (Chromium, and Node) still list and detect some zones under their old IANA names: India is |
| `lib/time.ts` | "just now", "5 minutes ago", "3 days ago": for when a device was active or a password set. |

### `lib/api/`

| File | What it is |
|---|---|
| `lib/api/auth.ts` | Session calls the API owns. Signing up and in, codes, and password reset and change are Better Auth's (lib/auth/client.ts); the BFF clears the httpOnl |
| `lib/api/chat.ts` | Sending a message and streaming the reply. Event order (backend `app/chat/streams.py`, `app/chat/service.py`): : open event: meta — the conversation ( |
| `lib/api/contract-render.ts` | Renders `contract.gen.ts` from the backend's contract, `docs/openapi.json`. The backend is the single source of truth for enums and limits: request fi |
| `lib/api/conversations.ts` | Conversation list, history and management. The server owns all of it. |
| `lib/api/errors.ts` | Every way a request can fail, turned into something a person can act on. The UI shows its OWN copy per error code. Backend messages are safe by contra |
| `lib/api/files.ts` | The File Library (docs/api-contract.md, "Files"): upload, list, retry, delete. The API decides everything (types by name and content, sizes, the 100 M |
| `lib/api/http.ts` | The one way the browser calls the API: same-origin, through the BFF. The browser never holds a token and never talks to the backend host. It calls `/a |
| `lib/api/identity.ts` | The identity side of Settings: the versioned profile, the photo, email change and devices. Everything goes through the BFF (`callRoute`), except the p |
| `lib/api/learning.ts` | The learning side of Settings: the academic catalog, the learner profile, subjects, learning and tutor preferences, and the preview of what the tutor |
| `lib/api/preferences.ts` | Appearance and notification preferences: two versioned resources (docs/api-contract.md). |
| `lib/api/progress.ts` | Progress (active time in PadhAI, questions, streaks, practice) and support requests. |
| `lib/api/routes.ts` | The backend routes this app is allowed to use — and nothing else. ONE TABLE, THREE READERS - `lib/api/*` builds every browser request from a key of th |
| `lib/api/sse.ts` | A Server-Sent Events parser for `fetch` streams. Follows the WHATWG event-stream rules rather than splitting on "\n\n": - a line ends at CRLF, LF or C |
| `lib/api/study.ts` | Study time (features/study): the server credits it; the client only reports what it observes. |
| `lib/api/types.ts` | Wire types for the chat API. Mirrors the backend contract: `docs/openapi.json` and `docs/api-contract.md` at the repository root. The backend is the s |
| `lib/api/voice.ts` | Voice mode's speech, through the web app's own proxy only: what the student said (one recorded utterance) and one sentence of their reply read aloud. |

### `lib/auth/`

| File | What it is |
|---|---|
| `lib/auth/client.ts` | The browser's Better Auth client: same-origin calls to /api/auth (only the routes in routes.ts exist there). It never sees a session token: the cookie |
| `lib/auth/config.ts` | Better Auth (1.7.7, pinned) for PadhAI: signing up and in, Google, email codes, password reset and change, two-step sign-in, and the session lifecycle |
| `lib/auth/events.ts` | What Better Auth tells the API after it acts (backend/app/auth/internal.py): email a code, or raise a security notice. The API keeps the one email sen |
| `lib/auth/guard.ts` | Per-account limits for Better Auth, in the API's own table (auth_attempts) with the API's scopes and keys (backend/app/auth/service.py `_throttle`): S |
| `lib/auth/options.ts` | What the auth pages may offer, read on the server per request. Kept apart from config.ts so a page asking "is Google on?" never loads Better Auth or t |
| `lib/auth/password.ts` | argon2id for Better Auth, in exactly the format the API writes and reads with argon2-cffi (backend/app/auth/security.py): a PHC string, `$argon2id$v=1 |
| `lib/auth/protection.ts` | Two outside checks, with timeouts and this app's failure rules (protection.test.ts): - passwordBreached: Have I Been Pwned's range API (k-anonymity). |
| `lib/auth/routes.ts` | Which of Better Auth's routes this app serves at /api/auth, and what leaves them. Pure, so it is unit-tested directly (routes.test.ts). ALLOWLIST, lik |
| `lib/auth/server.ts` | Better Auth for this process, built on first use, never at import: `next build` imports route modules and must not need the database or any secret. |

### `lib/server/`

| File | What it is |
|---|---|
| `lib/server/backend.ts` | Server-side reads from the API, for server components (layouts, auth pages). The result is a three-way outcome on purpose. The old app treated "the ba |
| `lib/server/config.ts` | Server-only configuration. `API_BASE_URL` is where the chat API listens. It is NOT a `NEXT_PUBLIC_` value: browsers never call the API, so its address |
| `lib/server/cookies.ts` | The session cookie. Better Auth (lib/auth) issues it; the BFF and server components only read it, and the browser never sees the token (the cookie is |
| `lib/server/expired.ts` | `/api/session/expired` — where a page goes when the API says the session is over. It re-checks before clearing anything. A plain "GET clears the cooki |
| `lib/server/gate.ts` | Which requests the middleware lets through, which it sends to sign-in. Middleware only GATES PAGES, and only on the presence of the session cookie — i |
| `lib/server/proxy-core.ts` | The BFF: the only path from a browser to the chat API. browser ──/api/v1/...──► this proxy ──/v1/... + Bearer <session>──► API (127.0.0.1) What it gua |
| `lib/server/public-origin.ts` | The origin the BROWSER used, which is not always what the server sees. In production the app runs behind a Cloudflare Tunnel: TLS ends at the edge and |
| `lib/server/release.ts` | Which release this web server runs, for operators. Production runs the checkout /opt/aichat/app with a RELEASE file at its root (written by deploy/ser |
| `lib/server/session.ts` | The session token from Better Auth's httpOnly cookie, for server components, once its signature is verified. Same trust rule as the BFF: on HTTPS only |
