# Troubleshooting and FAQ

> Verified at commit `0e33ec0` (2026-10-26) against `scripts/run.mjs`, `docker-compose.dev.yml`, the
> `.env.example` files, `frontend/apps/app/src/lib/auth/`, `backend/app/settings.py`, `backend/app/files/` and the
> test configuration. The local fixes are verified by reading the code; local Docker was not run on the owner's PC.

**How to read the tables:** each row starts from what you see, then gives the likely cause, how to confirm it,
and the fix.
- **Production problems** (MISMATCH, a failed deploy, an outage on the live site) are in the
  [operations runbooks](operations.md#runbooks).
- **First-time setup** is in the [beginner guide](beginner-guide.md).

## Contents

- [Setting up](#setting-up)
- [Starting the app](#starting-the-app)
- [Signing in](#signing-in)
- [Chat and answers](#chat-and-answers)
- [Files](#files)
- [Voice and dictation](#voice-and-dictation)
- [Tests and checks](#tests-and-checks)
- [Windows](#windows)
- [FAQ](#faq)

## Setting up

| You see | Likely cause | Check | Fix |
|---|---|---|---|
| `bun run setup` fails at `backend venv` | Python 3.12 isn't installed, or isn't on the path | Windows: `py -3.12 --version`; Linux: `python3.12 --version` | Install Python 3.12 (on Linux also `python3.12-venv`), then rerun `bun run setup` |
| `✗ backend/.venv is missing. Run bun run setup first.` | Setup hasn't run in this clone | `backend/.venv` doesn't exist | `bun run setup` |
| `bun install` refuses the lockfile | Another Bun version | `bun --version` should be `1.3.14` (`.bun-version`) | Install Bun 1.3.14 |
| A `node_modules` folder or lockfile appeared in the top folder | `bun install` was run there. The workspace is `frontend/` | `git status` lists them as new | Delete what it created, and install from `frontend/` (or with `bun run setup`) |

## Starting the app

| You see | Likely cause | Check | Fix |
|---|---|---|---|
| `bun run dev` fails at `dev database` | Docker isn't running, or port 5432 is taken | `docker compose version`, `docker ps` | Start Docker (on Windows, Docker Desktop). Stop any other PostgreSQL on 5432 |
| `bun run dev` fails at `migrations` | The database isn't ready yet, or `DATABASE_URL` in `backend/.env` points elsewhere | `docker compose -f docker-compose.dev.yml ps` shows `postgres` healthy | Run `bun run dev` again. Keep `DATABASE_URL` as in `backend/.env.example` |
| `■ api exited` (or `web`), and the other process stops | One process failed; the runner stops both | The lines just above it | Fix that error, then `bun run dev` again |
| `address already in use` on 3000 or 4000 | Another copy of the app, or another program | `netstat -ano` (Windows), `ss -ltnp` (Linux) | Stop the other program |
| The browser shows **"We can't reach the service"** | The web app can't reach the API. This is an outage screen, not a sign-out | http://127.0.0.1:4000/health | Start the API (`bun run dev` or `bun run dev:backend`). Check `API_BASE_URL` in `frontend/apps/app/.env.local` is `http://127.0.0.1:4000` |
| The API refuses to start with a settings error | A value in `backend/.env` has the wrong type or range | The message names the setting | Fix it ([environment-variables.md](environment-variables.md)) |

## Signing in

| You see | Likely cause | Check | Fix |
|---|---|---|---|
| Sign-in or sign-up fails, and the web app's terminal says `BETTER_AUTH_SECRET is not set`, `AUTH_INTERNAL_TOKEN is not set` or `AUTH_DATABASE_URL is not set` | `frontend/apps/app/.env.local` lacks the sign-in settings (the `.env.example` there doesn't list them) | The file's contents | Add them as in [beginner-guide.md, Step 5](beginner-guide.md#step-5-configure-the-web-app), then restart |
| `… must be at least 32 characters` | The secret or token is too short | Its length | Make a new value: `py -3.12 -c "import secrets; print(secrets.token_hex(32))"` (Linux: `python3.12 …`) |
| No code arrives | `AUTH_INTERNAL_TOKEN` is missing from `backend/.env`, or differs from the web app's. Without it, the API's `/internal/auth/*` routes don't exist (404) | Both files; Mailpit at http://127.0.0.1:8025 | Set the same value in both, and restart both |
| Signed in, but sent straight back to sign-in | The site was opened as `127.0.0.1:3000`; the session cookie belongs to one host name | The address bar | Use **http://localhost:3000** |
| Saving a password fails with "service unavailable" | The breached-password check couldn't reach `api.pwnedpasswords.com`, and it refuses when it can't (fails closed) | Internet access from your computer | Sign in with an email code meanwhile ("Email me a code instead") |
| "Too many attempts" while testing | The per-account limits (for example 10 sign-ins in 15 minutes, 5 codes in 15 minutes) or Better Auth's per-address limit | The limits in [security.md](security.md) | Wait for the window to pass. Locally only, `AUTH_RATE_LIMIT=off` in `.env.local` turns off Better Auth's per-address limit, as the end-to-end tests do; the per-account limits stay. Never set it in production |
| No "Continue with Google" button | Google sign-in isn't configured | `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` unset | Expected locally. Production setup: [deployment.md](deployment.md) |

## Chat and answers

| You see | Likely cause | Check | Fix |
|---|---|---|---|
| Every answer is `You said: …` | `LLM_PROVIDER=fake` | `backend/.env` | Expected with the fake. For real answers: `LLM_PROVIDER=openai_compatible` and `LLM_PRIMARY_API_KEY` |
| Answers fail with `llm_unavailable` or `llm_timeout` | The model provider refused (key missing, wrong or out of credit) or was too slow | The API's log (generation errors) | Fix the key. With `LLM_FALLBACK_*` set, the fallback is tried, but only before the first word arrives |
| 409 `conflict` when sending | A reply is still being written in that chat, perhaps in another tab | The other tab | Wait, or press Stop |
| 429 `rate_limited` | The per-student reply quota (`CHAT_GENERATIONS_PER_MINUTE` 20, `CHAT_GENERATIONS_PER_DAY` 500 by default) | The response | Wait, or raise the quota locally |
| Answers have no textbook sources | No knowledge source: the NCERT service isn't configured (`NCERT_KB_*`), and the local knowledge base is empty | The API log's `rag.retrieval` reason | Expected locally. To try retrieval, ingest something: [rag.md](rag.md). Retrieval never stops an answer |
| "hi" doesn't count for the streak | A learning day needs a meaningful, fully answered question (or 5 answers to bank tests) | Settings > Learning & Streak | Ask a real question |

## Files

| You see | Likely cause | Check | Fix |
|---|---|---|---|
| `/health` says `"files": "unavailable"`, and uploads don't work | No embedding provider: files need one | `EMBEDDING_PROVIDER` and `EMBEDDING_API_KEY` in `backend/.env` | `EMBEDDING_PROVIDER=fake` (offline) or a real key, then restart. The self-test runs in the background after the start |
| An image or a scanned PDF fails | Reading images needs Tesseract with English and Hindi (`eng`, `hin`) | `tesseract --list-langs` | Install Tesseract and both languages |
| `files_capacity_reached` | Less than 5 GB free on the disk, or PadhAI's own tables have reached 3 GiB | Free disk space | Free space (`app/files/service.py`, `check_capacity`) |
| A file stays "processing" | Files are read one at a time, fairly across students; a stuck one is retried after its lease | The API log (files worker) | Wait. A failed file can be retried from the File Library |

## Voice and dictation

| You see | Likely cause | Check | Fix |
|---|---|---|---|
| No voice button | `VOICE_MODE` is `off` (the default), or `qa` without your address in `VOICE_QA_EMAILS`, or the tutor's language isn't English | `GET /v1/voice` says `enabled: false` | Turn it on with the OllaLink settings ([ai-architecture.md, "Voice mode"](ai-architecture.md#voice-mode)). Locally, `VOICE_PROVIDER=fake` works without OllaLink, as the end-to-end tests use it |
| The microphone doesn't start | The browser's permission was refused | The site's permission in the browser | Allow the microphone for the site. The site allows only its own pages to use it (`Permissions-Policy`) |
| No dictation button in the composer | The browser has no speech recognition (`SpeechRecognition` or `webkitSpeechRecognition`) | Another browser | Use a browser that has it; dictation is the browser's own feature |

## Tests and checks

| You see | Likely cause | Fix |
|---|---|---|
| `routes.test.ts` fails: a route or field isn't in the contract | The API changed, or a new route is missing from the proxy's allowlist | `bun run contract`; add the route to `frontend/apps/app/src/lib/api/routes.ts` |
| `bun run build` fails at "API contract current" | `docs/openapi.json` is out of date | `bun run contract`, and commit the result with the change |
| `test_foundation.py` reports a schema difference | `app/db/models.py` and the migrations disagree | Fix the migration until both match ([data-model.md](data-model.md)) |
| `test_route_auth.py` fails for a new route | The route has no sign-in dependency | Add `get_principal`, or record a reason in its `PUBLIC` list (a decision for the owner) |
| The backend tests refuse their database | A test database's name must end in `_test` | Fix `TEST_DATABASE_URL` |
| The backend tests can't connect | They need PostgreSQL + pgvector and Mailpit | Start them with `bun run dev`, or `docker compose -f docker-compose.dev.yml up -d` |
| End-to-end tests refuse to start | `global-setup.ts` allows only loopback API and Mailpit addresses, so the suite can never touch production | Point them at `127.0.0.1` |
| Playwright: "Executable doesn't exist" | The browsers aren't installed | In `frontend/apps/app`: `bunx playwright install chromium webkit` |
| Biome rewraps many files | `bunx biome format --write` was run inside `frontend/apps/app`, without the project's settings | Revert those files and use `bun run lint` |
| `bun run verify`, `bun run lock:backend` or `bun run rehearse` fail at once | They need Docker | Run them where Docker is available |
| A red CI job | CI is advisory, and one job has a known failing baseline | [testing.md, "Known baseline"](testing.md#known-baseline) |

## Windows

| You see | Fix |
|---|---|
| `UnicodeEncodeError` (cp1252) from a script | `PYTHONIOENCODING=utf-8`; scripts that write files pass `encoding="utf-8"` |
| A `.sh` script fails with `$'\r'` | The file has Windows line endings. The repository is LF (`.gitattributes`): restore the file from git, and set your editor to LF |
| `bash deploy/...` runs inside WSL instead of Git Bash | Call Git Bash explicitly: `"C:\Program Files\Git\bin\bash.exe" deploy/status.sh` |

## FAQ

**Can I run PadhAI without any AI key?**
Yes. Use `LLM_PROVIDER=fake` and `EMBEDDING_PROVIDER=fake`. Everything works except real answers and real search
quality.

**Where are the sign-up codes in development?**
In Mailpit, at http://127.0.0.1:8025. The API sends every email there.

**Why can't the browser call the API directly?**
The session token must never reach page code. The browser calls the web app's own `/api/v1/*`, which checks the
request and adds the token ([security.md](security.md)).

**Why is the API on port 4000 here and 4100 in production?**
4000 is development (`bun run dev`). 4100 is production's port, and the end-to-end tests also use it.

**Why can't I see the API's `/docs` in production?**
They exist only outside production (`APP_ENV`), so the live API doesn't publish its interface. The contract is
[openapi.json](openapi.json).

**Why do learning days end at midnight India time?**
The streak and the learning day follow India time on purpose (`app/progress/learning.py`), whatever the
student's own time zone.

**How do I start over with an empty local database?**
Run `docker compose -f docker-compose.dev.yml down -v`, then `bun run dev`. This deletes all **local** data. Never
run it on the production server.

**Where do I report a security problem?**
See [SECURITY.md](../SECURITY.md). Don't open a public issue.
