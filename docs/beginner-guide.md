# Beginner guide: run PadhAI on your own computer

> Verified at commit `0e33ec0` (2026-10-26) against `scripts/run.mjs`, `docker-compose.dev.yml`,
> `backend/.env.example`, `frontend/apps/app/.env.example`, `frontend/apps/app/src/lib/auth/config.ts`,
> `frontend/apps/app/playwright.config.ts` and `backend/app/settings.py`.
>
> **How far this is verified:**
> - **Verified by reading the code, not by running it.** The owner's PC has no Docker (the owner's rule), so
>   this local setup was not run there.
> - **Windows and Linux** commands come from the scripts.
> - **macOS is not verified.** The Linux steps are the closest guide.

This guide is for someone who has never seen the project. Every step says:
- what it is for;
- what you need first;
- what to type;
- what you should see;
- what to do if it fails.

The short version, for experienced developers, is [development.md](development.md).

## Contents

- [What you are setting up](#what-you-are-setting-up)
- [Local, test and production](#local-test-and-production)
- [Step 1: Install the tools](#step-1-install-the-tools)
- [Step 2: Get the code](#step-2-get-the-code)
- [Step 3: Install the dependencies](#step-3-install-the-dependencies)
- [Step 4: Configure the API](#step-4-configure-the-api)
- [Step 5: Configure the web app](#step-5-configure-the-web-app)
- [Step 6: Start everything](#step-6-start-everything)
- [Step 7: Create an account and ask a question](#step-7-create-an-account-and-ask-a-question)
- [Step 8: Check that it is healthy](#step-8-check-that-it-is-healthy)
- [Step 9: Run the checks before you change anything](#step-9-run-the-checks-before-you-change-anything)
- [Step 10: Stop, and start again later](#step-10-stop-and-start-again-later)
- [Windows notes](#windows-notes)
- [Linux notes](#linux-notes)
- [What to read next](#what-to-read-next)

## What you are setting up

PadhAI is two programs that work together, plus a database:

```mermaid
flowchart LR
  B[Your browser<br/>http://localhost:3000] --> W[Web app<br/>Next.js, port 3000]
  W -->|only the web app talks to the API| A[API<br/>FastAPI, port 4000]
  A --> P[(PostgreSQL + pgvector<br/>Docker, port 5432)]
  W -->|sign-in data| P
  A -->|emails with codes| M[Mailpit<br/>Docker, inbox on port 8025]
  A -->|answers| L[An AI model<br/>or the fake one]
```

- **The web app** (`frontend/`) is what you see. It also runs sign-in, and it passes your requests on to the API.
- **The API** (`backend/`) holds the rules and the data, and writes the tutor's answers.
- **PostgreSQL** is the database. **Mailpit** catches every email the API sends, so you can read sign-up codes
  without a real mailbox. Both run in Docker.
- **The AI model** can be a real one (it needs a key) or the built-in **fake** one, which simply answers
  `You said: …`. The fake is enough to try everything.

New words are explained in the [glossary](glossary.md).

## Local, test and production

| | Local (this guide) | Tests | Production |
|---|---|---|---|
| Where | Your computer | Your computer or CI | One server, run by the owner |
| Web app | http://localhost:3000 (`next dev`) | A production build on :3100 | systemd, port 3000, behind Cloudflare |
| API | http://127.0.0.1:4000, reloads on save | :4100 with the fake model | systemd, port 4100 |
| Database | `aichat` in Docker | `aichat_test` (pytest), dropped and recreated | PostgreSQL on the server |
| Emails | Mailpit | An in-memory mailbox (pytest), Mailpit (e2e) | A real email service |
| Changed by | You | The test runners | Only `bun run deploy`, with the owner's approval |

Nothing in this guide touches production.

## Step 1: Install the tools

**Goal:** have the five tools the project needs.

**Why:** the API is Python, the web app runs on Bun and Node, and the database runs in Docker.

**Before you start:** an account that can install software on your computer.

| Tool | Version | Why it's needed |
|---|---|---|
| Git | any recent | To get the code |
| Python | **3.12** | The API (`backend/.venv`) |
| Bun | **1.3.14** (`.bun-version`) | Installs and runs the web app and the task runner |
| Node.js | **24** (`.node-version` pins 24.19.0) | Runs the web app's server, as production does |
| Docker | Docker Desktop (Windows), or Docker Engine with the Compose plugin (Linux) | Runs PostgreSQL and Mailpit |

**Command:** check what you have.

Windows (PowerShell or Git Bash):

```sh
git --version
py -3.12 --version
bun --version
node --version
docker compose version
```

Linux:

```sh
git --version
python3.12 --version
bun --version
node --version
docker compose version
```

**Expected result:** a version for each: Python `3.12.x`, Bun `1.3.14`, Node `v24.x`, and a Docker Compose version.

**If it fails:**
- `py -3.12` isn't found (Windows): install Python 3.12 from python.org with the "py launcher" option. The setup
  script runs `py -3.12`.
- `python3.12` isn't found (Linux): install `python3.12` and `python3.12-venv` (on Ubuntu 24.04:
  `sudo apt-get install python3.12 python3.12-venv`).
- `bun --version` shows another version: install 1.3.14 from https://bun.sh. The lockfile is checked with
  `--frozen-lockfile`, and another version can refuse it.
- `docker compose version` fails: install Docker, start it, and try again.

## Step 2: Get the code

**Goal:** a copy of the repository on your computer.

**Why:** everything (web app, API, deploy scripts and docs) is in one repository.

**Before you start:** access to the private repository. Ask the owner.

**Command:**

```sh
git clone <the repository URL>
cd <the folder it created>
```

**Expected result:** a folder with `backend/`, `frontend/`, `docs/`, `deploy/`, `package.json` and `README.md`.

**If it fails:** "Repository not found" or "Permission denied" means your GitHub account has no access yet.

## Step 3: Install the dependencies

**Goal:** install the API's Python packages and the web app's packages, and create the API's settings file.

**Why:** `bun run setup` does all of it in one go (`scripts/run.mjs`).

**Before you start:** Step 1's tools. Run it from the repository's top folder. **Never run `bun install` in the
top folder**: the Bun workspace is `frontend/`.

**Command:**

```sh
bun run setup
```

**Expected result:** the script prints each step, then `✓ all steps passed`. It creates:
- `backend/.venv`, the API's Python environment, with the packages from `backend/requirements-dev.txt`;
- `backend/.env`, copied from `backend/.env.example`, with the message
  `created backend/.env from .env.example: add your LLM key (or set LLM_PROVIDER=fake)`;
- `frontend/node_modules`, installed with `bun install --frozen-lockfile`.

**If it fails:**
- The venv step fails: see Step 1 for Python 3.12.
- `pip install` fails: check your internet connection and proxy, then run `bun run setup` again. It keeps what
  already worked.
- `bun install` reports a lockfile problem: check `bun --version` is 1.3.14.

## Step 4: Configure the API

**Goal:** settings that let the API run without any paid keys.

**Why:** `backend/.env` comes with an empty AI key. Two more settings are needed for sign-in and file uploads to
work locally.

**Before you start:** a random value of at least 32 characters, to share between the API and the web app. Make one
with Python:

```sh
# Windows
py -3.12 -c "import secrets; print(secrets.token_hex(32))"
# Linux
python3.12 -c "import secrets; print(secrets.token_hex(32))"
```

**Command:** open `backend/.env` in an editor, and set these lines (change them where they already exist, add them
where they don't):

```sh
LLM_PROVIDER=fake
EMBEDDING_PROVIDER=fake
AUTH_INTERNAL_TOKEN=<the random value you just made>
```

What each line does:

| Setting | Why |
|---|---|
| `LLM_PROVIDER=fake` | Answers `You said: …` word by word, with no key. For real answers, keep `openai_compatible` and set `LLM_PRIMARY_API_KEY` instead |
| `EMBEDDING_PROVIDER=fake` | Turns on the File Library and the knowledge base offline. Without it (and without `EMBEDDING_API_KEY`), `/health` reports `"files": "unavailable"`. The fake only matches shared words, so it proves the plumbing, not search quality |
| `AUTH_INTERNAL_TOKEN` | The web app's sign-in asks the API to email codes, and this token proves the request is the web app's. It isn't in `backend/.env.example` yet; without it those routes don't exist and no code is sent |

Leave the other lines as they are. They already point at the local database (`DATABASE_URL`) and at Mailpit
(`SMTP_HOST=127.0.0.1`, `SMTP_PORT=1025`).

**Expected result:** a saved `backend/.env`. Never commit it: it is git-ignored, and it may later hold real keys.

**If it fails:** if the API later refuses to start with a settings error, the message names the setting. Every
setting is explained in [environment-variables.md](environment-variables.md).

## Step 5: Configure the web app

**Goal:** settings that let the web app sign people in.

**Why:** sign-in (Better Auth) runs inside the web app. It needs:
- its own database connection;
- a secret to sign the session cookie;
- the same internal token as the API.

`frontend/apps/app/.env.example` says nothing is required. That is true for building the app, but not for
signing in (`lib/auth/config.ts` refuses without these values).

**Before you start:** the random value from Step 4, and one more new random value for the cookie secret (run the
same command again).

**Command:** create `frontend/apps/app/.env.local` with:

```sh
API_BASE_URL=http://127.0.0.1:4000
NEXT_PUBLIC_SITE_URL=http://localhost:3000
AUTH_DATABASE_URL=postgresql://aichat:aichat@127.0.0.1:5432/aichat
BETTER_AUTH_SECRET=<a second random value, at least 32 characters>
AUTH_INTERNAL_TOKEN=<the same value as in backend/.env>
```

- `AUTH_DATABASE_URL` uses the local database's development user, as the end-to-end tests do
  (`playwright.config.ts`). Production uses a separate, limited role ([deployment.md](deployment.md)).
- `aichat` / `aichat` are local development credentials from `docker-compose.dev.yml`. Never use them anywhere
  else.

**Expected result:** a saved `frontend/apps/app/.env.local`. It is git-ignored; never commit it.

**If it fails:** if sign-in later shows an error, and the web app's terminal says
`BETTER_AUTH_SECRET is not set` or `must be at least 32 characters`, fix this file and restart Step 6.

## Step 6: Start everything

**Goal:** the database, Mailpit, the API and the web app all running.

**Why:** `bun run dev` does it in order:
1. it starts PostgreSQL and Mailpit (`docker compose -f docker-compose.dev.yml up -d --wait`);
2. it brings the database up to date (`alembic upgrade head`);
3. it starts the API on port 4000 (reloading when you save a Python file) and the web app on port 3000.

**Before you start:** Docker is running (on Windows, open Docker Desktop and wait until it says it is running).
Ports 3000, 4000, 5432, 1025 and 8025 are free.

**Command:**

```sh
bun run dev
```

**Expected result:**
- the database and migration steps, then `✓ all steps passed`;
- log lines from the API (uvicorn on `http://127.0.0.1:4000`) and from the web app (Next.js on port 3000).

Leave this terminal open: closing it stops the API and the web app.

**If it fails:**
- `docker` errors: Docker isn't running, or port 5432 is already used (often by another PostgreSQL). Stop the
  other one and try again.
- `backend/.venv is missing. Run bun run setup first.`: do Step 3.
- A migration error: the database container may still be starting. Run `bun run dev` again. If it persists, see
  [troubleshooting.md](troubleshooting.md).
- One process exits, and the runner prints `■ api exited` (or `web`) and stops the other: read the lines just
  above it for the reason.

## Step 7: Create an account and ask a question

**Goal:** use the app the way a student does.

**Why:** this proves the whole chain works: browser, web app, sign-in, API, database, email and the model.

**Before you start:** Step 6 is running.

**Command:** in the browser:
1. Open **http://localhost:3000**. Use `localhost`, not `127.0.0.1`: the session cookie belongs to one host name.
2. Choose **Create an account**. Type a name (optional) and any email address, for example `you@example.com`.
   Choose **Send code**.
3. Open Mailpit at **http://127.0.0.1:8025**, open the newest email, and copy the 6-digit code. It expires in 15
   minutes.
4. Enter the code and choose **Create account**.
5. Choose a password (8–128 characters), or choose **Skip for now**: an email code always signs you in.
6. Type a question in the chat and send it.

**Expected result:** you're signed in on a new chat. With `LLM_PROVIDER=fake`, the answer `You said: <your
question>` appears word by word, and the chat shows up in the sidebar.

**If it fails:**
- No email in Mailpit: check `AUTH_INTERNAL_TOKEN` is the same in both files (Steps 4 and 5), then restart Step 6.
- Saving a password fails with "service unavailable": the breached-password check needs to reach
  `api.pwnedpasswords.com`, and it refuses when it can't (it fails closed). Skip the password and sign in with a
  code.
- The page shows an outage screen: the API isn't running. Look at the terminal from Step 6.
- More: [troubleshooting.md](troubleshooting.md).

## Step 8: Check that it is healthy

**Goal:** confirm each part is up, without using the app.

**Why:** these are the same checks production uses ([operations.md](operations.md)).

**Command:** open these in the browser, or use `curl`:

| Address | Expected answer |
|---|---|
| http://127.0.0.1:4000/health | `{"status": "ok", "release": "development", "files": "available"}`. `files` turns `available` shortly after the start, once the file reader's self-test has passed |
| http://127.0.0.1:4000/ready | `{"status": "ok", "database": true}` (HTTP 503 with `"database": false` when the database can't be reached) |
| http://localhost:3000/api/health | The web server is up. Asked from your own computer, it also gives the release and whether sign-in reaches its database |
| http://127.0.0.1:4000/docs | The API's interactive documentation (only outside production) |

**If it fails:** `files` stays `unavailable` when there is no embedding provider (Step 4). For anything else, see
[troubleshooting.md](troubleshooting.md).

## Step 9: Run the checks before you change anything

**Goal:** know the project is in a good state before you change it, so you can tell later what you broke.

**Command:** from the repository's top folder:

```sh
bun run lint     # ruff (API) and Biome (web app)
bun run test     # API tests (need Docker's PostgreSQL and Mailpit), web app typecheck and unit tests, deploy script tests
bun run build    # is docs/openapi.json current? then the web app's production build
```

**Expected result:** each ends with `✓ all steps passed`.

**If it fails:**
- The API tests create their own database, `aichat_test`, and need the Docker containers from Step 6.
- What each layer needs, and the known failing CI job, are in [testing.md](testing.md).

## Step 10: Stop, and start again later

- **Stop the API and the web app:** press `Ctrl+C` in the terminal from Step 6.
- **Stop the containers:** `docker compose -f docker-compose.dev.yml stop`. Your local data stays.
- **Start again:** `bun run dev`.
- **Start over with an empty local database** (**this deletes all local data**, and only on your own computer):
  `docker compose -f docker-compose.dev.yml down -v`, then `bun run dev`.
- Never run `down -v` against production: on the server, it would delete the real database
  ([deployment.md](deployment.md)).

## Windows notes

- **Shells:** use Git Bash or PowerShell from the repository's top folder. Both run `bun run …`.
- **Running Python directly:**
  - the API's Python is `backend\.venv\Scripts\python` (Linux: `backend/.venv/bin/python`);
  - for example, in `backend/`: `.venv\Scripts\python -m pytest -o addopts="" -ra`.
- **Text encoding:** Windows' default encoding for Python is cp1252.
  - Set `PYTHONIOENCODING=utf-8` before a script that prints non-English text.
  - Scripts that read or write files pass `encoding="utf-8"`.
- **Line endings:** the repository uses LF (`.gitattributes`). Keep your editor on LF, especially for `.sh`
  files.
- **Formatting the web app:** use `bun run lint` (from the top folder or `frontend/`). Running
  `bunx biome format --write` inside `frontend/apps/app` skips the project's settings and rewraps files.

## Linux notes

- Install `python3.12` and `python3.12-venv`. The setup script runs `python3.12 -m venv`.
- If `docker` needs `sudo`, add your user to the `docker` group, sign out and in again, and rerun Step 6.
- The production server is Ubuntu 24.04 with Python 3.12, so the lock file `backend/requirements.lock` is made
  for Linux (`bun run lock:backend`).

## What to read next

- [start-here.md](start-here.md): the map of the project, and your first hour.
- [codebase-map.md](codebase-map.md): where each thing lives.
- [request-lifecycle.md](request-lifecycle.md): what happens when you press Send.
- [troubleshooting.md](troubleshooting.md): when something goes wrong.
- [CONTRIBUTING.md](../CONTRIBUTING.md): how a change gets to production.
