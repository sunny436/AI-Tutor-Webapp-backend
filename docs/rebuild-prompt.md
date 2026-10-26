# Rebuild prompt

> Verified at commit `0e33ec0` (2026-10-26) against `scripts/run.mjs`, `docker-compose.dev.yml`, the
> `.env.example` files, `frontend/apps/app/src/lib/auth/config.ts`, `frontend/apps/app/playwright.config.ts` and
> [CLAUDE.md](../CLAUDE.md).

A prompt to give an AI coding agent that has a fresh clone of this repository. It sets the project up locally,
proves it works, and reports honestly. It does **not** deploy, and it never touches production.

**How to use it:**
1. Copy everything inside the block below into the agent's first message.
2. Replace nothing: the agent finds the facts in the repository.
3. If the agent runs on the owner's development PC, the owner's rule applies: no Docker there. The prompt tells the
   agent to stop at the static checks in that case.

```text
You are setting up PadhAI (an AI tutor: a FastAPI API in backend/ and a Next.js web app in frontend/, one
repository) on this machine, from this clone, for local development. Work only from what the repository says.
Report what you actually ran and saw.

GROUND RULES (they override everything below)
- Never touch production. Never run `bun run deploy`, `bun run rollback`, `bun run smoke`, or anything in deploy/
  that reaches a server. Never ssh anywhere. Never push to git.
- Never print, copy or commit secrets. Do not open or print: any .env file's real values, ollima.txt, ollastack.txt,
  openrouter.txt, dummy_account.txt. Generate your own local random values where a secret is needed.
- Never fake success. Do not mock a component to make a check pass, skip a failing step and report it as passing,
  or "simplify the architecture". If something can't be done, say exactly what blocked it.
- Never delete data you did not create. The one destructive command allowed is resetting the LOCAL development
  database (`docker compose -f docker-compose.dev.yml down -v`), and only after you say why.
- Don't change product code to make the setup work. If the code or docs are wrong, report it with the file and line.
- Read CLAUDE.md first. Its rules apply to you.

STEP 1: INSPECT
- Run `git rev-parse --short HEAD` and `git status`. Record the commit.
- Read README.md, docs/start-here.md, docs/beginner-guide.md and docs/development.md.
- Record the pinned runtimes: .bun-version, .node-version, and Python 3.12 (scripts/run.mjs runs `py -3.12` on
  Windows and `python3.12` elsewhere).
- Check the installed tools: git, Python 3.12, bun (must equal .bun-version), node (major version from
  .node-version), and `docker compose version`.
- Decide if Docker may be used here. On the owner's development PC it may not (CLAUDE.md, "The owner's hard rules").
  If not, do only steps 2, 3 and 7 (static checks) and report the rest as "not run: no Docker by rule".

STEP 2: INSTALL (from the lockfiles only)
- From the repository root: `bun run setup`. It creates backend/.venv (requirements-dev.txt), copies
  backend/.env from backend/.env.example if missing, and runs `bun install --frozen-lockfile` in frontend/.
- Never run `bun install` in the repository root. The Bun workspace is frontend/.
- Expected: "✓ all steps passed". On failure, see docs/troubleshooting.md, "Setting up".

STEP 3: CONFIGURE (local values only)
- In backend/.env set: LLM_PROVIDER=fake, EMBEDDING_PROVIDER=fake, and AUTH_INTERNAL_TOKEN=<a random value of
  at least 32 characters>. Generate it with `python -c "import secrets; print(secrets.token_hex(32))"` using
  the venv's Python. Do not print it in your report.
- Create frontend/apps/app/.env.local with API_BASE_URL=http://127.0.0.1:4000,
  NEXT_PUBLIC_SITE_URL=http://localhost:3000,
  AUTH_DATABASE_URL=postgresql://aichat:aichat@127.0.0.1:5432/aichat (the local dev database, as
  playwright.config.ts uses), BETTER_AUTH_SECRET=<another random value of at least 32 characters> and
  AUTH_INTERNAL_TOKEN=<the same value as in backend/.env>.
- Why: sign-in (Better Auth, frontend/apps/app/src/lib/auth/config.ts) refuses to work without these, even
  though frontend/apps/app/.env.example says nothing is required (docs/environment-variables.md lists the gaps).

STEP 4: DATABASE AND START
- `bun run dev` starts PostgreSQL 16 + pgvector and Mailpit (docker-compose.dev.yml), runs `alembic upgrade head`,
  then the API on 127.0.0.1:4000 and the web app on port 3000. Run it in the background, and keep its output.
- If port 5432 is taken by another PostgreSQL, report it. Don't stop someone else's database without asking.

STEP 5: HEALTH
- GET http://127.0.0.1:4000/health. Expect {"status": "ok", "release": "development", "files": ...}. `files`
  should become "available" shortly after the start, because EMBEDDING_PROVIDER=fake.
- GET http://127.0.0.1:4000/ready. Expect 200 with {"status": "ok", "database": true}.
- GET http://localhost:3000/api/health. Expect 200.

STEP 6: ONE REAL FLOW
- Sign up through the web app (http://localhost:3000, "Create an account") with an @example.com address. Read the
  6-digit code from Mailpit's API or UI (http://127.0.0.1:8025). You may skip the password step ("Skip for now").
- Ask one question in a new chat. Expect a streamed reply "You said: <question>" (the fake model), and the chat in
  the sidebar.
- Use a browser automation tool if you have one. Otherwise, say that this step was not run, and why.

STEP 7: CHECKS
- `bun run lint` (ruff and Biome).
- `bun run build` (contract check, then the web app's production build).
- `bun run test` (needs the Docker database and Mailpit: backend pytest in its own aichat_test database, the web
  app's typecheck and unit tests, the deploy script tests).
- Optional, if Playwright browsers can be installed: `bun run test:e2e`. It refuses non-loopback addresses by
  design.
- Report each command's real exit code. Pipes can hide failures. A known red CI job is described in
  docs/testing.md, "Known baseline"; say whether you saw the same failures.

STEP 8: RECOVERY (use only when needed, and say which one you used)
- Broken Python environment: delete backend/.venv (local, safe), then `bun run setup`.
- Broken web dependencies: delete frontend/node_modules (local, safe), then `bun install --frozen-lockfile` in
  frontend/.
- Contract out of date (`routes.test.ts` or "API contract current" fails): `bun run contract`, then report the
  diff. Don't commit it.
- Local database in a bad state: DESTRUCTIVE, local only: `docker compose -f docker-compose.dev.yml down -v`, then
  `bun run dev`.
- Anything about production (MISMATCH, a deploy, the live site): stop and report. Production changes need the
  owner's approval (docs/operations.md, docs/deployment.md).

STEP 9: REPORT
Give a short report with:
- the commit;
- the tools and versions found;
- each step with PASS, FAIL or NOT RUN, and the evidence (command, exit code, the key output line);
- what was blocked by missing credentials or rules (for example: no real LLM key, so only the fake model was
  tested; no Docker, so steps 4 to 7 were not run);
- every mismatch between the docs and the code, with the file and line;
- what you changed on disk (the env files you created, anything you deleted).
Do not claim anything you did not see.
```

**Related:**
- [beginner-guide.md](beginner-guide.md): the same steps for a person, with explanations.
- [troubleshooting.md](troubleshooting.md): what the agent should consult when a step fails.
