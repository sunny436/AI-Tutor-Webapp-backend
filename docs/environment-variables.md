# Environment variables

> Verified at commit `0e33ec0` (2026-10-26) against `backend/app/settings.py`,
> `frontend/apps/app/src/env.mjs`, `frontend/apps/app/src/lib/auth/`, `frontend/apps/app/src/lib/server/config.ts`,
> the Playwright configs and `deploy/env/*.example`. Every name below exists in that code; none is invented.

An **environment variable** is a named setting a program reads when it starts, such as which database to use or
which AI model to call. PadhAI keeps settings out of the code so the same commit runs on a laptop, in CI and in
production. Defaults are safe for development, except secrets, which have none.

## Where each process reads its settings

| Process | Read by | On your machine | In production |
|---|---|---|---|
| API (FastAPI) | `Settings` in `backend/app/settings.py`: the environment, then `.env` in the working directory | `backend/.env`, created from `backend/.env.example` by `bun run setup` | `/etc/aichat/api.env` |
| Jobs worker (`python -m app.jobs`) | the same `Settings` | `backend/.env` | `/etc/aichat/api.env`, read again on every run |
| Web app (Next.js) | `src/env.mjs` (validated at build), `src/lib/auth/*`, `src/lib/server/config.ts` | `frontend/apps/app/.env.local`, copied from `.env.example` | `/etc/aichat/web.env` |
| PostgreSQL container and backups | `deploy/compose/docker-compose.yml`, `deploy/backup.sh` | `docker-compose.dev.yml` uses fixed development credentials | `/etc/aichat/postgres.env` |
| Tests | the Playwright configs (`frontend/apps/app/playwright*.ts`) | your shell | – |

There is **no root `.env`**. Nothing reads one, so the repository has no root `.env.example`; each process has its
own example file next to it.

## Rules for secrets

- A real value never goes into git. `.env` files are git-ignored, and the example files hold placeholders only.
- In production, secrets live only in `/etc/aichat/{api,web,postgres}.env` (mode 600), which a deploy never
  touches. To run a one-off command with them, load the file the way the service does
  ([deployment.md](deployment.md), "On the server"); don't `source` it into a shell.
- Generate secrets on the machine that uses them (`openssl rand -base64 48`), and never print them.
- `NEXT_PUBLIC_*` values are **built into** the web app's JavaScript and reach every browser. Never put a secret
  in one.
- The provider key files in the repository root (`ollima.txt`, `ollastack.txt`, `openrouter.txt`) are git-ignored
  local notes. Never print or commit them.

## When a change takes effect

| What you changed | When it applies |
|---|---|
| API setting (`api.env`) | the next API start. A deploy restarts the API only when `backend/` changed, so a settings-only change needs a restart of `aichat-api`, a production change that needs the owner's approval |
| Jobs worker setting (`JOBS_ENABLED`, `NOTIFICATIONS_*`) | the next run, within a minute: no restart |
| Web server-only value (`API_BASE_URL`, `BETTER_AUTH_SECRET`, …) | the next web start |
| Web `NEXT_PUBLIC_*` value | the next **build**: a deploy rebuilds the frontend when one changes |
| `EMBEDDING_MODEL` or `EMBEDDING_DIMENSIONS` | needs more than a restart: re-ingestion, and for the dimension a migration ([rag.md](rag.md), "Embeddings") |

## Production safety checks

With `APP_ENV=production`, the API refuses to start (`Settings.validate_for_env`) when any of these is true:

- `SECRET_KEY` is the development placeholder or shorter than 32 characters;
- `AUTH_INTERNAL_TOKEN` is shorter than 32 characters;
- `DATABASE_URL` uses the development credentials;
- `LLM_PROVIDER=fake`, or `VOICE_PROVIDER=fake`;
- `EMBEDDING_PROVIDER=fake` while RAG is enabled;
- `EMAIL_BACKEND` is not `smtp` or `ollastack`, or `ollastack` lacks its token or mailbox;
- `APP_NAME` is not `PadhAI`;
- `PUBLIC_APP_URL` is set but is not a bare HTTPS origin;
- `NCERT_KB_BASE_URL` is neither `https://` nor loopback;
- `INTENT_ROUTER`, `STUDY_SCOPE` or `VOICE_MODE` is on without `OLLALINK_API_KEY`;
- `VOICE_MODE=qa` has no `VOICE_QA_EMAILS`;
- an Ollalink URL is not `https://`.

The web app refuses to sign anyone in without `BETTER_AUTH_SECRET` and `AUTH_INTERNAL_TOKEN` of at least 32
characters, plus `AUTH_DATABASE_URL`.

## Web app

| Variable | Kind | Default | What it does |
|---|---|---|---|
| `API_BASE_URL` | server-only | `http://127.0.0.1:4000` | Where the chat API listens. Production sets `http://127.0.0.1:4100`. Never prefix it with `NEXT_PUBLIC_`: browsers never call the API |
| `NEXT_PUBLIC_SITE_URL` | public, baked into the build | none (sign-in falls back to `http://127.0.0.1:3000`) | The public origin: page metadata and Better Auth's base URL. An `https://` origin gives the `__Host-padhai_session` cookie; plain HTTP gives `padhai_session` |
| `PREVIEW_FEATURES` | server-only, read per request | unset | `1` shows preview pages with sample data (Homework Helper, Summarizer). Never in production |
| `NEXT_PUBLIC_SENTRY_DSN` | public, build | unset | Sentry is bundled only when this is set |
| `NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE` | public, build | unset | Trace sampling, when Sentry is on |
| `NEXT_PUBLIC_TERMS_URL`, `NEXT_PUBLIC_PRIVACY_URL` | public, build | unset | Links to terms and privacy pages (`src/lib/legal.ts`) |
| `NEXT_DIST_DIR` | build | `.next` | Build into another folder, so a check never touches the build being served (`NEXT_DIST_DIR=.next-verify bun run build`) |
| `BETTER_AUTH_SECRET` | **secret** | none | Signs the session cookie (at least 32 characters). Without it no session is accepted. Rotating it signs everyone out |
| `AUTH_DATABASE_URL` | **secret** | none | Better Auth's connection, as the role `aichat_auth`, which is limited to the identity tables (migration 0012) |
| `AUTH_INTERNAL_TOKEN` | **secret** | none | The same value as the API's; authenticates the web app's calls to `/internal/auth/*` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | the secret is **secret** | unset | "Continue with Google" appears only with both. Redirect URI: `https://<app host>/api/auth/callback/google` |
| `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY` | the secret is **secret** | unset | The adaptive CAPTCHA (Cloudflare Turnstile) is on only with both |
| `AUTH_RATE_LIMIT` | server-only | on | `off` disables Better Auth's own rate limiter (for tests) |
| `SKIP_ENV_VALIDATION`, `CI` | build | unset | Skip `env.mjs` validation at build |

## PostgreSQL and backups (production only: `/etc/aichat/postgres.env`)

| Variable | What it does |
|---|---|
| `POSTGRES_USER`, `POSTGRES_DB` | The database's owner role and name (`aichat`) |
| `POSTGRES_PASSWORD` | **Secret.** The owner role's password |
| `BACKUP_DIR` | Where `deploy/backup.sh` writes dumps (`/var/backups/aichat`) |
| `KEEP_DAYS` | Days of dumps kept (7) |

## Tests

| Variable | Read by | Default | What it does |
|---|---|---|---|
| `E2E_API_URL` | e2e (`e2e/env.ts`) | `http://127.0.0.1:4100` | The API the suite uses; must be loopback |
| `E2E_MAILPIT_URL` | e2e | `http://127.0.0.1:8025` | Where sign-up codes are read; must be loopback |
| `E2E_BACKEND_DIR` | `playwright.config.ts` | this repository's `backend/`, if its `.venv` exists | Where to start the API from (with that directory's `.env`), when none is running on `:4100`; `none` never starts one |
| `E2E_AUTH_DATABASE_URL` | `playwright.config.ts` | `postgresql://aichat:aichat@127.0.0.1:5432/aichat` | The web app's sign-in database during the suite |
| `E2E_SKIP_BUILD`, `E2E_REUSE_APP` | e2e | unset | Reuse the last `.next-e2e` build or a running app while iterating |
| `E2E_GOOGLE` | `playwright.config.ts` | unset | Turns on Google sign-in with fake client values |
| `E2E_VISUAL`, `E2E_VISUAL_DIR` | `e2e/visual.e2e.ts` | unset | Capture-only screenshots, saved to a folder |
| `PREVIEW_PORT` | `e2e/serve.mjs` | `3101` | Port of the second build, with preview features on |
| `SMOKE_EMAIL`, `SMOKE_PASSWORD` | the production smoke | from `dummy_account.txt` | The QA account the smoke signs in as. Never print them |
| `SMOKE_BASE_URL` | the production smoke | `https://ayur.namahos.com` | The site the smoke checks |
| `SMOKE_HEADLESS`, `SMOKE_SHOTS` | the production smoke | unset | Hide the browser; save screenshots to an absolute folder outside the repository |

## API settings

All 120 fields of `Settings` (`backend/app/settings.py`), in the file's own order. The name is the field's name in
capitals (`database_url` is `DATABASE_URL`).

**Secret** marks a value that must never be printed or committed. "Declared but not read" means the field exists
and does nothing today.

### Process

| Variable | Type / allowed | Default | What it does |
|---|---|---|---|
| `APP_ENV` | one of `development` \| `test` \| `production` | `development` | `production` turns on the startup safety checks (`validate_for_env`), hides `/docs` and selects the systemd file sandbox. Tests run with `test`. |
| `APP_NAME` | string | `Assistant` | The product name in emails, prompts and the API title. Production refuses anything but `PadhAI`. |
| `HOST` | string | `127.0.0.1` | Declared but not read: the address comes from uvicorn's `--host` (`scripts/run.mjs`, `deploy/systemd/aichat-api.service`). |
| `PORT` | integer | `4000` | Declared but not read: the port comes from uvicorn's `--port` (4000 in development, 4100 in production). |
| `LOG_LEVEL` | string | `INFO` | Level of the JSON logs (`app/logging.py`), for the API and the jobs worker. |
| `SECRET_KEY` | string | `dev-only-secret-change-me` (refused in production) | **Secret.** Keys HMACs of one-time email codes. Must be set to a long random value in production. |
| `AUTH_INTERNAL_TOKEN` | string | empty | **Secret.** Shared with the web app's Better Auth (web.env): it authenticates its calls to /internal/auth/* (app/auth/internal.py). Empty = those routes do not exist (404). |

### Database

| Variable | Type / allowed | Default | What it does |
|---|---|---|---|
| `DATABASE_URL` | string | `postgresql+asyncpg://aichat:aichat@127.0.0.1:5432/aichat` | The PostgreSQL connection (asyncpg driver), the single source of truth. Production refuses the development credentials. |
| `DB_POOL_SIZE` | integer | `5` | SQLAlchemy connection pool size (`app/db/session.py`). |
| `DB_MAX_OVERFLOW` | integer | `5` | Extra connections allowed above the pool size. |
| `DB_CONNECT_TIMEOUT_S` | number | `5.0` | Seconds to wait for a database connection. |

### HTTP

| Variable | Type / allowed | Default | What it does |
|---|---|---|---|
| `ALLOWED_ORIGINS` | string | empty | Comma-separated browser origins. Empty = no CORS (the API is called by the web app's server-side proxy, not by browsers directly). |
| `TRUST_FORWARDED_FOR` | true/false | `False` | Only enable when the API is reachable exclusively through a trusted proxy. |
| `MAX_BODY_BYTES` | integer | `64 * 1024` | Largest JSON request body (`app/middleware.py`); the photo, file and voice uploads have their own limits. |

### Accounts and throttling

| Variable | Type / allowed | Default | What it does |
|---|---|---|---|
| `EMAIL_CODE_TTL_MINUTES` | integer | `15` | Lifetime of an email-change code issued by the API. |
| `EMAIL_CODE_MAX_ATTEMPTS` | integer | `5` | Wrong guesses allowed per email-change code. |
| `CODE_REQUESTS_PER_EMAIL` | integer | `5` | per auth_window_minutes |
| `AUTH_WINDOW_MINUTES` | integer | `15` | The window the per-account auth limits count in (`app/auth/service.py`). |
| `EMAIL_CHANGE_REQUESTS_PER_USER` | integer | `3` | per auth_window_minutes |
| `ARGON2_TIME_COST` | integer | `3` | Argon2id time cost for the password checks the API does (re-authentication). |
| `ARGON2_MEMORY_KIB` | integer | `64 * 1024` | Argon2id memory cost (KiB). |
| `ARGON2_PARALLELISM` | integer | `2` | Argon2id parallelism. |

### Profile photo

| Variable | Type / allowed | Default | What it does |
|---|---|---|---|
| `AVATAR_MAX_BYTES` | integer (ge 64 * 1024, le 20 * 1024 * 1024) | `5 * 1024 * 1024` | The upload is the original file (JPEG/PNG/WebP); the stored photo is a 256 px WebP. The web app's proxy caps uploads at the default (docs/openapi.json `x-max-bytes`), so raising this alone changes nothing for browsers. |
| `AVATAR_UPLOADS_PER_USER` | integer | `10` | per auth_window_minutes |

### Progress

| Variable | Type / allowed | Default | What it does |
|---|---|---|---|
| `DEFAULT_TIMEZONE` | string | `Asia/Kolkata` | Decides which day "today" is for a user who has not chosen a time zone (users.timezone). |

### Jobs worker and email notifications

| Variable | Type / allowed | Default | What it does |
|---|---|---|---|
| `JOBS_ENABLED` | true/false | `False` | (python -m app.jobs, started every minute by aichat-jobs.timer) Read on every run, so a change to api.env applies from the next minute, no restart needed. |
| `NOTIFICATIONS_MODE` | one of `off` \| `dry_run` \| `allowlist` \| `on` | `off` | Rollout of emails to students: off (nothing is planned or sent) -> dry_run (planned and recorded as `dry_run`, nothing sent) -> allowlist (sent only to NOTIFICATIONS_ALLOWLIST) -> on. Support forwards to SUPPORT_EMAIL do not depend on this. |
| `NOTIFICATIONS_ALLOWLIST` | string | empty | comma-separated user ids or email addresses |
| `NOTIFICATIONS_KINDS` | string | empty | comma-separated kinds to allow; empty = every kind |
| `NOTIFICATIONS_MAX_PER_RUN` | integer (ge 1, le 1000) | `50` | Most emails the jobs worker sends in one run. |
| `PUBLIC_APP_URL` | string | empty | The public web address, for links in emails (unsubscribe). Required once emails are sent. |
| `SUPPORT_EMAIL` | string | empty | Where support requests are forwarded. Empty: requests are only stored. |

### Email delivery

| Variable | Type / allowed | Default | What it does |
|---|---|---|---|
| `EMAIL_BACKEND` | one of `smtp` \| `ollastack` \| `memory` | `smtp` | `smtp` (Mailpit locally), `ollastack` (the Agent Mail API) or `memory` (tests only; refused in production). |
| `EMAIL_FROM` | string | `Assistant <no-reply@localhost>` | Sender address for SMTP (unused with `ollastack`, whose mailbox sets the sender). |
| `SMTP_HOST` | string | `127.0.0.1` | SMTP server host. |
| `SMTP_PORT` | integer | `1025` | SMTP server port (Mailpit listens on 1025). |
| `SMTP_USERNAME` | string | empty | SMTP login, if the server needs one. |
| `SMTP_PASSWORD` | string | empty | **Secret.** SMTP password. |
| `SMTP_STARTTLS` | true/false | `False` | Upgrade the SMTP connection with STARTTLS. |
| `SMTP_SSL` | true/false | `False` | Connect to SMTP over TLS from the start. |
| `OLLASTACK_BASE_URL` | string | `https://login.ollastack.com` | Ollastack Agent Mail (EMAIL_BACKEND=ollastack): the mailbox sets the sender; EMAIL_FROM is unused. |
| `OLLASTACK_TOKEN` | string | empty | **Secret.** Token for the Ollastack Agent Mail API. |
| `OLLASTACK_MAILBOX_ID` | string | empty | The Ollastack mailbox that sends PadhAI's email. |

### Language model

| Variable | Type / allowed | Default | What it does |
|---|---|---|---|
| `LLM_PROVIDER` | one of `openai_compatible` \| `fake` | `openai_compatible` | "openai_compatible" uses the primary (and optional fallback) provider below. "fake" is a deterministic local provider for tests and offline development. |
| `LLM_PRIMARY_NAME` | string | `ollima` | Label of the primary provider in logs and usage records. |
| `LLM_PRIMARY_BASE_URL` | string | `https://api.ollima.com/v1` | Base URL of the primary OpenAI-compatible chat-completions API. |
| `LLM_PRIMARY_API_KEY` | string | empty | **Secret.** Key for the primary provider. |
| `LLM_PRIMARY_MODEL` | string | `gemini-3.1-flash-lite` | Model the tutor answers with (also used by `scripts/eval_tutor_record.py`). |
| `LLM_PRIMARY_STREAM_USAGE` | true/false | `True` | Ask the primary provider to report token usage in the stream. |
| `LLM_FALLBACK_NAME` | string | `openrouter` | Label of the fallback provider. |
| `LLM_FALLBACK_BASE_URL` | string | `https://openrouter.ai/api/v1` | Base URL of the fallback provider. |
| `LLM_FALLBACK_API_KEY` | string | empty | **Secret.** Key for the fallback provider. |
| `LLM_FALLBACK_MODEL` | string | empty | empty = no fallback provider |
| `LLM_FALLBACK_STREAM_USAGE` | true/false | `True` | Ask the fallback provider to report token usage in the stream. |
| `LLM_TEMPERATURE` | number | `0.7` | Sampling temperature for the tutor's replies. |
| `LLM_MAX_OUTPUT_TOKENS` | integer | `4096` | Most tokens one reply may produce. |
| `LLM_CONNECT_TIMEOUT_S` | number | `10.0` | Seconds to connect to a provider. |
| `LLM_FIRST_TOKEN_TIMEOUT_S` | number | `60.0` | Seconds to wait for the first token; past it the turn fails, or the fallback provider is tried. |
| `LLM_TOTAL_TIMEOUT_S` | number | `180.0` | Most seconds one reply may take in total. |
| `LLM_FAKE_TOKEN_DELAY_S` | number | `0.0` | Delay between the fake provider's words (tests and demos only). |
| `LLM_MAX_INPUT_CHARS` | integer | `48000` | Total characters sent to the model per turn (system prompt + retrieved context + history + new message). Characters approximate tokens (~4 chars/token for English; Devanagari costs ~2.6x more tokens per character). See app/rag/context.py. |

### Chat

| Variable | Type / allowed | Default | What it does |
|---|---|---|---|
| `CHAT_MAX_MESSAGE_CHARS` | integer | `16000` | Longest message a student may send. |
| `CHAT_HISTORY_MAX_MESSAGES` | integer | `50` | Most earlier messages considered for the prompt (the character budget also applies). |
| `CHAT_GENERATIONS_PER_MINUTE` | integer | `20` | Per-student reply quota per minute (429 `rate_limited`). |
| `CHAT_GENERATIONS_PER_DAY` | integer | `500` | Per-student reply quota per day. |
| `STREAM_KEEPALIVE_S` | number | `15.0` | Seconds of silence before the SSE stream sends a `: keepalive` comment. |
| `STREAM_STALE_AFTER_S` | integer | `300` | A reply still `streaming` after this long is treated as dead and marked interrupted. |
| `STREAM_CANCEL_POLL_S` | number | `1.0` | How often a generation checks the database's stop flag (a stop from another tab or process). |

### JEV: intent router

| Variable | Type / allowed | Default | What it does |
|---|---|---|---|
| `INTENT_ROUTER` | one of `off` \| `shadow` \| `on` | `off` | (app/intents): Ollalink's classification model reads what each new message asks for (one of 46 intents). off: nothing is sent; shadow: read and recorded beside the reply, never applied; on: applied. Rollout off -> shadow -> on (docs/deployment.md). The key is a secret. |
| `OLLALINK_BASE_URL` | string | `https://ai.ollalink.com` | Ollalink's classification API (the intent router and the study scope). Must be `https://` in production. |
| `OLLALINK_API_KEY` | string | empty | **Secret.** Ollalink key: the intent router, the study scope and voice mode all need it. |
| `INTENT_ROUTER_TIMEOUT_S` | number (gt 0, le 5) | `1.5` | The whole reading (both requests); never retried. Then the turn goes on without an intent. |
| `INTENT_MIN_CONFIDENCE` | number (ge 0, le 1) | `0.5` | An intent is applied only when P(group) and P(group) x P(intent \| group) reach these; below the group threshold the second request is not made. scripts/eval_intents.py chooses both (dev split). |
| `INTENT_MIN_GROUP_CONFIDENCE` | number (ge 0, le 1) | `0.5` | P(group) needed before the second classification request is made and an intent applied. |

### JEV: study scope filter

| Variable | Type / allowed | Default | What it does |
|---|---|---|---|
| `STUDY_SCOPE` | one of `off` \| `shadow` \| `on` | `off` | (app/intents/scope.py): is the latest message something PadhAI helps with? One more Ollalink request, with the router's key, client and time limit. off: nothing is sent; shadow: read and recorded, never applied; on: unrelated requests are redirected and the tutor keeps to learning. |
| `SCOPE_MIN_REDIRECT` | number (ge 0, le 1) | `0.5` | P(unrelated) needed to redirect, and P(support \| unclear \| mixed) needed to apply one: chosen with scripts/eval_scope.py on the dev split (no learning request there above 0.31 for unrelated). |
| `SCOPE_MIN_CONFIDENCE` | number (ge 0, le 1) | `0.5` | P(support, unclear or mixed) needed to apply that scope decision. |
| `OLLALINK_WARM_AFTER_S` | number (ge 0, le 3600) | `45.0` | While students use the app, one small warm-up to Ollalink when nothing was sent for this long, so a message after a quiet spell is not slow (IntentClassifier.nudge). 0: never. |

### Voice mode

| Variable | Type / allowed | Default | What it does |
|---|---|---|---|
| `VOICE_MODE` | one of `off` \| `qa` \| `on` | `off` | (app/voice): the student speaks, OllaLink's speech-to-text hears it, the tutor answers as for a typed message, and OllaLink's text-to-speech reads the answer aloud, sentence by sentence. English only (OllaLink's speech output has no Hindi), for students whose tutor language is English or unset. Rollout off -> qa (only the accounts in VOICE_QA_EMAILS, comma-separated) -> on; every voice route checks it itself. The key is OLLALINK_API_KEY. |
| `VOICE_QA_EMAILS` | string | empty | Comma-separated accounts voice mode is offered to while `VOICE_MODE=qa` (read through `voice_rollout_allows`). |
| `VOICE_PROVIDER` | one of `ollalink` \| `fake` | `ollalink` | `ollalink`, or `fake` for tests (refused in production). |
| `OLLALINK_STT_URL` | string | `https://gpu-transcribe.ollalink.com` | OllaLink speech-to-text service (must be `https://` in production). |
| `OLLALINK_TTS_URL` | string | `https://gpu-tts.ollalink.com` | OllaLink text-to-speech service (must be `https://` in production). |
| `VOICE_TTS_VOICE` | string | `hadley` | English; GET {OLLALINK_TTS_URL}/voices lists them (hadley is its default) |
| `VOICE_TRANSCRIPTIONS_PER_MINUTE` | integer (ge 1, le 600) | `20` | Per student, counted in auth_attempts (they hold across processes and restarts). |
| `VOICE_TRANSCRIPTIONS_PER_DAY` | integer (ge 1, le 100000) | `400` | Per-student transcriptions per day. |
| `VOICE_SPEECH_PER_MINUTE` | integer (ge 1, le 6000) | `120` | Per-student speech requests per minute. |
| `VOICE_SPEECH_PER_DAY` | integer (ge 1, le 1000000) | `3000` | Per-student speech requests per day. |
| `VOICE_TRANSCRIPTIONS_IN_FLIGHT_PER_USER` | integer (ge 1, le 8) | `1` | Calls to OllaLink at once, counted in THIS process (the API runs as one: deploy/systemd/aichat-api.service); with more processes each would allow these. Per student, and in all. |
| `VOICE_SPEECH_IN_FLIGHT_PER_USER` | integer (ge 1, le 8) | `2` | Speech requests one student may have running at once. |
| `VOICE_TRANSCRIPTIONS_IN_FLIGHT` | integer (ge 1, le 256) | `8` | Transcriptions running at once, all students together, in this process. |
| `VOICE_SPEECH_IN_FLIGHT` | integer (ge 1, le 256) | `16` | Speech requests running at once, all students together, in this process. |
| `VOICE_SPEECH_CHARS_PER_MESSAGE` | integer (ge 600, le 100000) | `8000` | Speech for one reply at most (characters, summed over its sentences), also counted in this process. |

### Study time

| Variable | Type / allowed | Default | What it does |
|---|---|---|---|
| `STUDY_IDLE_READING_S` | integer (ge 60, le 1800) | `300` | (app/study): how long without input counts as idle, by mode. Reading allows longer (reading and thinking need no clicks); the reading prompt is always shorter than this. |
| `STUDY_IDLE_SOLVING_S` | integer (ge 30, le 1800) | `120` | Seconds without input before practice or test time counts as idle. |

### Retrieval (knowledge base and NCERT)

| Variable | Type / allowed | Default | What it does |
|---|---|---|---|
| `RAG_ENABLED` | true/false | `True` | Search the knowledge base (pgvector, or the NCERT service) on each turn; `false` skips it (reason `disabled`). Files attached to a chat are read either way. |
| `RAG_TOP_K` | integer | `5` | Passages retrieved per turn (the NCERT service is asked for three times as many for a student with a curriculum, then ranked). |
| `RAG_MIN_SCORE` | number | `0.3` | Cosine similarity floor (0..1). Uncalibrated default: tune with scripts/eval_retrieval.py. |
| `RAG_MAX_CONTEXT_CHARS` | integer | `8000` | Most characters of retrieved passages put in the prompt (whole passages only). |
| `RAG_RETRIEVAL_TIMEOUT_S` | number | `8.0` | Seconds the knowledge-base search may take before the turn goes on without it. |
| `RAG_HNSW_EF_SEARCH` | integer | `100` | pgvector HNSW `ef_search` for knowledge-base queries. |
| `NCERT_KB_BASE_URL` | string | empty | The NCERT Knowledge Service (app/rag/ncert.py): with a URL and a key, the tutor's knowledge source; empty = the pgvector knowledge base. The key is the service's client key (a secret). The timeout is the whole call: live searches took ~1.7 s, p95 2.8 s, at most 3.9 s (2026-10-15..19). |
| `NCERT_KB_API_KEY` | string | empty | **Secret.** Client key for the NCERT Knowledge Service. |
| `NCERT_KB_TIMEOUT_S` | number (gt 0, le 10) | `6.0` | Seconds for one NCERT search; slower calls fail with `ncert_timeout`. |
| `RAG_CHUNK_SIZE` | integer | `1000` | Characters per chunk when ingesting documents and reading student files. |
| `RAG_CHUNK_OVERLAP` | integer | `150` | Characters shared by consecutive chunks. |
| `RAG_MAX_DOCUMENT_BYTES` | integer | `5 * 1024 * 1024` | Largest document `scripts/ingest_documents.py` accepts. |

### Embeddings

| Variable | Type / allowed | Default | What it does |
|---|---|---|---|
| `EMBEDDING_PROVIDER` | one of `openai_compatible` \| `fake` | `openai_compatible` | "openai_compatible" calls an OpenAI-compatible /embeddings API. "fake" is a deterministic keyword-hashing embedder for tests and offline development. |
| `EMBEDDING_BASE_URL` | string | `https://api.openai.com/v1` | OpenAI-compatible `/embeddings` API. |
| `EMBEDDING_API_KEY` | string | empty | **Secret.** Key for the embeddings API. Without one, the knowledge-base search is skipped and student files cannot be read. |
| `EMBEDDING_MODEL` | string | `text-embedding-3-small` | Embedding model. Changing it hides older chunks until they are re-ingested (files: Retry). |
| `EMBEDDING_DIMENSIONS` | integer | `1536` | Must equal the pgvector column dimension (app/db/models.py EMBEDDING_DIMENSIONS). |
| `EMBEDDING_BATCH_SIZE` | integer | `64` | Texts per embeddings request. |
| `EMBEDDING_TIMEOUT_S` | number | `20.0` | Seconds per embeddings request. |

### File Library

| Variable | Type / allowed | Default | What it does |
|---|---|---|---|
| `FILES_ENABLED` | true/false | `True` | (app/files) Off = no uploads and no processing; READY attachments keep answering. Text chat never depends on files, and no files setting can stop the API from starting. |
| `FILES_EXTRACTOR` | one of `auto` \| `subprocess` \| `systemd` | `auto` | Where untrusted files are parsed. "systemd": a sandboxed transient unit (no network, no secrets, own memory limit); "subprocess": a plain child process with an empty environment (development and tests); "auto": systemd in production, subprocess otherwise. Production never parses unsandboxed: with anything but systemd there, files are unavailable. |

### Tutor behaviour

| Variable | Type / allowed | Default | What it does |
|---|---|---|---|
| `TUTOR_INTERACTIVE_BLOCKS` | true/false | `False` | Teach the model the interactive practice blocks (quizzes, flashcards, graphs, file previews; app/chat/assistant.py INTERACTIVE_BLOCKS). The web app renders them either way. Off until the owner turns it on; it costs prompt characters on every turn. |
| `TUTOR_TEACHING_POLICY` | true/false | `False` | Give the tutor its teaching defaults (app/chat/teaching.py: direct answers when asked, mistakes diagnosed before they are corrected, one hint at a time when stuck); the student's own settings still come first. Off until the owner turns it on; it costs prompt characters on every turn. |
| `QUESTION_BANK_TESTS` | true/false | `True` | Practice tests in the chat come only from the question bank (app/qbank/chat_tests.py): the model names a chapter, the app sets stored questions, and a practice block the model writes itself is never shown as a test. The owner's decision, 2026-10-16. |
| `ADAPTIVE_CHAT_TESTS` | true/false | `True` | A bank test chooses each next question from the answer before it (app/qbank/chat_tests.py). Off: every question is chosen when the test is set (a fixed-length test), still recorded as practice. A kill switch, no rollback needed (docs/question_bank.md). |

## What the example files list

Checked on 2026-10-26. The example files show the settings most installations change; anything they leave out keeps its default above.
These **are not listed in either** `backend/.env.example` or `deploy/env/api.env.example`, so set them from this
page when you need them:

- **Voice mode:** `VOICE_MODE`, `VOICE_QA_EMAILS`, `VOICE_PROVIDER`, `OLLALINK_STT_URL`, `OLLALINK_TTS_URL`,
  `VOICE_TTS_VOICE` and the `VOICE_*` limits. The code defaults are `off` and the OllaLink endpoints.
- **Study time:** `STUDY_IDLE_READING_S`, `STUDY_IDLE_SOLVING_S`.
- **Question bank:** `QUESTION_BANK_TESTS`, `ADAPTIVE_CHAT_TESTS` (both default `true`).
- **Development:** `backend/.env.example` also leaves out `AUTH_INTERNAL_TOKEN`, which the web app's sign-in needs
  locally; set the same value in `backend/.env` and in `frontend/apps/app/.env.local`.
- **The web app's example:** `frontend/apps/app/.env.example` lists none of the sign-in settings
  (`AUTH_DATABASE_URL`, `BETTER_AUTH_SECRET`, `AUTH_INTERNAL_TOKEN`; `deploy/env/web.env.example` has them), and
  says nothing is required. That is true for a build, but sign-in refuses to work without them, also in
  development ([beginner-guide.md, Step 5](beginner-guide.md#step-5-configure-the-web-app)).
- The remaining omissions are tuning values (timeouts, pool sizes, Argon2 costs, stream timing) whose defaults are
  intended.

## Related

- [deployment.md](deployment.md): where production's env files live, the jobs-worker rollout and the sign-in setup.
- [rag.md](rag.md): retrieval and embedding settings in context.
- [ai-architecture.md](ai-architecture.md): what the model, JEV and voice settings change.
- [security.md](security.md): how secrets and keys are handled.
