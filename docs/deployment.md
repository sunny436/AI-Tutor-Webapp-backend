# Deployment

> **The owner's production rule (hard):** Keep production simple and deterministic — Git main is the source of truth; deploy the exact verified commit to the server, build/run directly on the production VM, and keep frontend/backend versions strictly matched. No unnecessary containers, infrastructure layers, or deployment complexity; use system services/process supervision, health checks, backups, and rollback capability. After every release: verify the exact commit is live, services are healthy, and no stale/old release is serving traffic.
>
> Here: `Status: MATCH` is the match (both processes run the checkout's code); PostgreSQL's pinned
> Compose project is the only container; systemd supervises the API, the web app and the jobs
> timer; backups are nightly plus one before any migration; `bun run rollback` goes back. After
> every release: `bun run status` (MATCH, healthy, no legacy port 4000/3210/3211/6791 listening)
> and `bun run smoke`.

## How a change reaches production

1. You commit the change.
2. You push it to GitHub: `git push origin main`.
3. `bun run deploy` pushes the **same commit** to the production Git repository on the server.
4. The server moves its checkout to exactly that commit.
5. Only the parts that changed are rebuilt and restarted: the web app, the API, or both. A
   commit that only changes docs or tests restarts nothing.
6. A small smoke check confirms the app is alive.
7. Done. It prints GitHub main, what production runs, and `MATCH`.
8. You run `bun run smoke`: the live site, checked in a browser as the owner (below).

```
commit ─► git push origin main ─► bun run deploy ─► production Git ─► production checkout
        ─► changed parts only ─► smoke check ─► live
```

There are no pull requests and nothing waits for GitHub CI. CI still runs on every push, but it is
advisory: `bun run status` shows its verdict and never blocks anything. `bun run verify` runs the
same CI jobs locally when you want them; a deploy never requires it.

## Deploy

```sh
git push origin main
bun run deploy
```

`bun run deploy` refuses if your checkout has uncommitted changes or is not exactly GitHub `main`
(push first). It takes seconds for a backend change and a minute or two when the frontend must be
rebuilt. The work runs on the server as its own process, so closing the terminal or losing the
connection does not stop it halfway, and a second deploy started meanwhile stops at once
("another deploy is running").

The end of every deploy:

```
GitHub main SHA:          <sha>
Production checkout SHA:  <sha>
Backend running SHA:      <sha>   (same backend code as the checkout)
Frontend running SHA:     <sha>
Status: MATCH
```

A part that did not change keeps running, so it can show an older commit whose code is identical;
that is still `MATCH`. `MISMATCH` names what differs, for example after a rollback.

### What runs for which change

The server compares the new commit with what each part runs, by content (the git objects of its
files, tests excluded), and does only what differs, in this order:

| Changed | What happens |
|---|---|
| `backend/requirements.lock` | `pip install --require-hashes` into the existing venv, then `pip check` |
| a `package.json` or `frontend/bun.lock` | `bun install --frozen-lockfile` into the existing `node_modules` |
| `frontend/`, `.node-version`, `NEXT_PUBLIC_*` in `web.env` | the frontend is **built beside the build being served**; a failed build never reaches users |
| `backend/alembic/versions/` | if a migration is pending: a backup, then `alembic upgrade head` |
| `backend/` | restart the API only (about 3–5 s; a reply being written is saved as stopped) |
| the frontend (built above) | swap the new build in and restart the web app only (about 3–5 s) |
| `deploy/systemd/*` | changed unit files rewritten; the affected service restarts |
| anything else (docs, tests) | nothing |

Then the smoke check, on the server itself: both services active, API `/health` and `/ready`, web
`/login`, and a request through web → API → database. The public URL through Cloudflare is not part
of it (`bun run status` shows it).

The previous frontend build is kept (`.next-prev`), so going back to it (a rollback, or redeploying
what was there before) is a swap without a build. Next.js's build cache is kept between builds
(`.next-cache`), so a rebuild only recompiles what changed.

## Check production

```sh
bun run status        # read-only: health, what each part runs, GitHub main vs production, MATCH
```

On the server (`ssh root@10.1.30.37`):

```sh
systemctl status aichat-api aichat-web          # the two services
journalctl -u aichat-api -u aichat-web -n 50    # their logs
journalctl -u 'aichat-deploy-*'                 # deploy logs
tail /opt/aichat/app-state/HISTORY              # every deploy and rollback: who, what, how long
git -C /opt/aichat/app log -1                   # the commit production runs
bash /opt/aichat/app/deploy/infra-check.sh      # status plus ports, database and backups
```

## After every deploy: `bun run smoke`

```sh
bun run smoke         # the live site as the owner: headed Chrome, then an emulated iPhone and Android
```

The deploy's own smoke check only proves the services answer on the server. `bun run smoke`
(`frontend/apps/app/playwright.smoke.config.ts`, checks in `frontend/apps/app/smoke/`) uses the
public site the way a student does: it signs in once, checks the new chat (the greeting's rendered
contrast), the sidebar, the composer, menus, the bell, the streak, Settings, a 320px window and
motion, asks one real question and deletes that chat again, then repeats the layout checks on an
emulated iPhone (WebKit) and Android phone, and logs out. Every page is also checked in dark, by
switching the page to dark; the account's own theme is never changed.

- It signs in with `SMOKE_EMAIL` and `SMOKE_PASSWORD`, or the first two lines of
  `dummy_account.txt` in the repository root (git-ignored). The session it saves while running is
  deleted when it logs out.
- It writes as little as it can: the one question (which counts toward today's learning day, as any
  question does) and a sign-in. Marking notifications read is intercepted; nothing in Settings is
  saved. With student email on, the sign-in can send the owner a sign-in alert.
- `SMOKE_HEADLESS=1` hides the browser, `SMOKE_SHOTS=<folder>` saves screenshots there,
  `SMOKE_BASE_URL` points it elsewhere.
- Emulated phones are the phones' engines and sizes, not real devices: check a real iPhone and
  Android phone by hand for anything touch or keyboard specific.

Every check prints PASS or FAIL. Any FAIL means the deploy is not done: find out why, and
`bun run rollback` if production is impaired.

## Roll back

```sh
bun run rollback                  # back to the commit that was live before the last deploy
bun run rollback -- <commit>      # back to any earlier commit
```

Details: [rollback.md](rollback.md).

## When a deploy fails

A deploy stops at the first failure with `STOP:` and the reason, prints what each part runs, and
exits non-zero. It never reports success when a step failed. What was not restarted keeps serving;
the next deploy redoes whatever did not finish.

| It says | Do |
|---|---|
| `uncommitted or untracked changes` / `is not GitHub main` | commit, `git push origin main`, deploy again |
| `another deploy is running` | wait for it, then deploy again |
| `the frontend build failed` | users still get the previous build. Fix the code, push, deploy |
| `pip install failed` / `bun install failed` | nothing was restarted. Fix the lockfile, push, deploy |
| `the migration failed (backup: …)` | the API was not restarted. Read `journalctl -u 'aichat-deploy-*'`, fix the migration, push, deploy |
| `the API is not ready after its restart` | `bun run rollback`, then read `journalctl -u aichat-api` |
| `the new frontend did not start` | the previous build is already serving again; read `journalctl -u aichat-web` |
| `web.env must set …` | fix `/etc/aichat/web.env` on the server, deploy again |

## On the server

```
/opt/aichat/app.git      the production Git repository: deploys push here (the server never reaches GitHub)
/opt/aichat/app          the production checkout: the code that runs
  backend/.venv            its Python packages (reused; reinstalled only when requirements.lock changes)
  frontend/node_modules    its JS packages (reused; reinstalled only when package.json/bun.lock change)
  frontend/apps/app/.next  the served build (.next-prev: the one before; .next-cache: Next's cache)
  RELEASE                  the commit, reported by the API's /health and the web app's /api/health
/opt/aichat/app-state    what each part runs (content keys), previous, HISTORY
/opt/aichat/shared       the database's compose file and backup script (never part of a deploy)
/opt/aichat/runtime      the pinned Node versions
/etc/aichat/*.env        the secrets (never in Git, never touched by a deploy)
```

`git reset --hard` only changes tracked source files. The venv, `node_modules`, the builds, the
database, backups and secrets are outside Git and are never deleted by a deploy (it never runs
`git clean`). PostgreSQL (with pgvector) is the only datastore; a deploy never restarts it.

The first `bun run deploy` on a server that still runs the older release layout
(`/opt/aichat/current` → `/opt/aichat/releases/<commit>`) moves it to the checkout: it builds
everything while the old release keeps serving, then switches the services (a few seconds). If
that first deploy fails, it puts the old services back. The old release directory is left in place,
unused; delete it once you no longer want it (`bun run status` lists it).

### Migrations

A migration runs while the previous API is still serving, and a rollback runs older code on the
newer schema, so **every migration must be backward compatible** (expand, then contract):

- **Allowed in one step:** adding tables, nullable columns or columns with a server default, and
  adding indexes.
- **Needs several deploys** (new code first, the removal later): renaming or dropping a column or
  table, adding a NOT NULL without a default, or changing a type.
- **Every migration is preceded by a backup** in `/var/backups/aichat` (named in the deploy output).
- **Future native clients:** once a native client exists, a migration and the API change it serves
  must also keep the **oldest supported client** working
  ([api-contract.md](api-contract.md#compatibility-and-versioning)).

## One-time host preparation

Only for a new host. Copy the repository there once and run the installer:

```sh
git archive --format=tar.gz HEAD | ssh root@<host> 'mkdir -p /root/aichat-setup && tar -xzf - -C /root/aichat-setup'
ssh root@<host> bash /root/aichat-setup/deploy/install.sh     # lists the secret files it needs
# write /etc/aichat/{postgres,api,web}.env from deploy/env/*.example (chmod 600), then run it again
```

It installs Git, Python 3.12, the pinned Bun and Node, leaves an existing Docker alone, creates
`/opt/aichat/{app-state,shared,runtime}`, installs the units and starts PostgreSQL and the nightly
backup. Then `bun run deploy` (the first one builds everything and runs every migration).

## Environment variables

All production values live in `/etc/aichat/*.env` (root, mode 600), never in git. Templates:
`deploy/env/`. Local development: `backend/.env` and `frontend/apps/app/.env.local`.

| File | Variable | Used by | When | Secret |
|---|---|---|---|---|
| `web.env` | `API_BASE_URL` | frontend server (BFF, server components) | runtime | no. **The link to the backend**: must be `http://127.0.0.1:4100`; a deploy refuses anything else |
| `web.env` | `NEXT_PUBLIC_SITE_URL` | frontend (metadata URLs) | **build time** (baked into the build; required) | no |
| `web.env` | `NEXT_PUBLIC_SENTRY_DSN` | frontend error reporting, only bundled if set | build time | no (public DSN) |
| `web.env` | `NEXT_PUBLIC_TERMS_URL`, `NEXT_PUBLIC_PRIVACY_URL` | Settings › Help & Support links; each shown only when set to an http(s) address | build time | no |
| `api.env` | `SECRET_KEY`, `DATABASE_URL` | backend | runtime | **yes** |
| `api.env` | `SMTP_USERNAME`, `SMTP_PASSWORD`, `OLLASTACK_TOKEN` | backend email | runtime | **yes** |
| `api.env` | `LLM_PRIMARY_API_KEY`, `LLM_FALLBACK_API_KEY`, `EMBEDDING_API_KEY` | backend | runtime | **yes** |
| `api.env` | `APP_ENV`, `APP_NAME`, `EMAIL_*`, `SMTP_HOST/PORT/…`, `OLLASTACK_BASE_URL/MAILBOX_ID`, `LLM_*` names/URLs/models, `RAG_*`, `EMBEDDING_*` (other), `CHAT_*`, `STREAM_*`, `DEFAULT_TIMEZONE`, `AVATAR_MAX_BYTES`, limits | backend | runtime | no |
| `api.env` | `JOBS_ENABLED`, `NOTIFICATIONS_*`, `PUBLIC_APP_URL`, `SUPPORT_EMAIL` | jobs worker (and the API, for support forwards and links) | read on every worker run | no |
| `api.env` | `FILES_ENABLED` (default on), `FILES_EXTRACTOR` (`auto`: the systemd sandbox in production) | File Library (below) | runtime | no |
| `api.env` | `TUTOR_INTERACTIVE_BLOCKS` (default off) | Teaches the tutor the practice blocks (quiz, MCQ, flashcards, fill-in-the-blank, graph, concept diagram, file and PDF previews, downloads); the web app already renders them. Owner decision: it adds about 1,430 characters to every prompt (a chat with practice tests or exercises also tells the tutor their record, at most 2,600 more, with the wording of the latest missed questions), and the worst-case history reserve falls from 34% to 31% of `LLM_MAX_INPUT_CHARS` (25% with that record). After changing what the tutor is told, run `scripts/eval_tutor_record.py` against the model. Restart the API after changing it | runtime | no |
| `postgres.env` | `POSTGRES_PASSWORD` | database, backup | runtime | **yes** |
| `postgres.env` | `POSTGRES_USER`, `POSTGRES_DB`, `BACKUP_DIR`, `KEEP_DAYS` | database, backup | runtime | no |

A runtime value takes effect on the next restart of the service; a build-time value
(`NEXT_PUBLIC_*`) on the next deploy (the frontend is rebuilt when they change).

## File Library (app/files)

- **Needs:** embeddings configured (`EMBEDDING_*`, any OpenAI-compatible API, e.g. OpenRouter; the
  model must return 1536 dimensions with the `dimensions` parameter) and Tesseract with English and
  Hindi on the host (`apt install tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin`, in `install.sh`).
- **After a start** the API's file worker, in the background, kills leftover `aichat-extract-*`
  units, settles files a previous process left, and runs a self-test through the real sandbox. Files
  are available only if it passes: `GET /health` → `"files": "available"`; `bun run status` and
  `infra-check.sh` show it. Otherwise uploads get 503 and chat is unaffected.
- **Sandbox check on the host:** `cd /opt/aichat/app/backend && .venv/bin/python scripts/sandbox_probe.py`
  (a PDF, OCR of an image, and that secrets, the tunnel's credentials and the network are out of
  reach); `systemd-analyze security aichat-extract-<…>` on a running unit.
- **During a deploy** `update.sh` writes `/run/aichat-deploying`; the worker makes no new claims
  while it exists (the checkout and venv are changing).
- **Capacity:** uploads stop (503 `files_capacity_reached`) when the database reaches 3 GB or the
  disk has less than 5 GB free. `backup.sh` refuses to dump with less than twice the database's
  size free, and leaves out `file_chunks` (derived data; after a restore, re-queue ready files as
  its header says). Keep `KEEP_DAYS` at 7: up to ~9 dumps share the database's disk.
- **Kill switch:** `FILES_ENABLED=false` in `api.env` and `systemctl restart aichat-api`: no uploads
  and no processing (pending files become `stored`); ready attachments keep working.

## Jobs worker

`python -m app.jobs` (backend/app/jobs) does what no request should wait for: it sends the email
outbox (sign-in and password alerts, reminders, support forwards), plans reminders, and applies
retention (expired sessions with their IP and user agent, old throttling counters and codes, sent
emails redacted after 7 days). `aichat-jobs.timer` starts one run a minute; each run exits.

It ships **installed but not enabled**, and every email to students is **off** until you turn it on:

| Setting (`api.env`) | Default | Meaning |
|---|---|---|
| `JOBS_ENABLED` | `false` | `false`: a run exits at once. Nothing is sent, nothing is cleaned up. |
| `NOTIFICATIONS_MODE` | `off` | `off`: no student email is planned or sent (it waits, then expires). `dry_run`: planned and recorded as `dry_run`, never sent. `allowlist`: sent only to `NOTIFICATIONS_ALLOWLIST`, the rest recorded as `suppressed`. `on`: sent. |
| `NOTIFICATIONS_ALLOWLIST` | – | comma-separated user ids or email addresses (for `allowlist`) |
| `NOTIFICATIONS_KINDS` | every kind | comma-separated: `security_sign_in`, `security_password_changed`, `daily_reminder`, `streak_warning`, `weekly_summary` |
| `NOTIFICATIONS_MAX_PER_RUN` | `50` | emails a run sends at most |
| `PUBLIC_APP_URL` | – | the site's address, for links in emails; required for any mode but `off` (the worker keeps student email off without it, and logs why) |
| `SUPPORT_EMAIL` | – | where support requests are forwarded (independent of `NOTIFICATIONS_MODE`); empty: stored only |

The worker reads these on every run: editing `api.env` takes effect for it within a minute, with no
restart. The API reads them when it starts, to tell each student in Settings whether their emails
are being sent (`delivery`); after changing the rollout, `systemctl restart aichat-api` (about 3 s)
so Settings says the same as the worker does.
Suggested order, checking the outbox and deliverability at each step:

```sh
ssh root@10.1.30.37
# 1. enable the worker, emails still off: retention runs, support forwards go out
printf 'JOBS_ENABLED=true\nPUBLIC_APP_URL=https://ayur.namahos.com\n' >> /etc/aichat/api.env
systemctl enable --now aichat-jobs.timer
journalctl -u aichat-jobs -o cat -n 5                     # "jobs run finished", a report of counts
# 2. NOTIFICATIONS_MODE=dry_run: what would be sent is recorded, nothing leaves
# 3. NOTIFICATIONS_MODE=allowlist with NOTIFICATIONS_ALLOWLIST=<your address>
# 4. NOTIFICATIONS_MODE=on
```

**Delivery guarantees** (app/notifications/sender.py, app/jobs/runner.py; each has a test in
`backend/tests/test_jobs.py`):
- **One run at a time.** The timer starts a oneshot service, and each run takes a PostgreSQL
  advisory lock; rows are claimed `FOR UPDATE SKIP LOCKED`. The API never runs jobs itself.
- **One email or bell item per logical event.** Unique dedup keys: `<user>:<kind>:<period>` for
  reminders, one per event for alerts (`email_outbox.dedup_key`,
  `user_notifications (user_id, dedup_key)`). Re-running the worker adds nothing twice.
- **Failures:**
  - a definite provider refusal goes back to `pending` with backoff (1, 5, 15 minutes) and becomes
    `failed` after 3 attempts;
  - a possibly delivered message (a timeout after sending) becomes `unknown` and is never resent;
  - a run that dies after claiming leaves the row `sending`, and the next run marks it `unknown`.
  - Nothing is ever marked `sent` without the provider accepting it, and each row is sent on its
    own, so one failure never blocks the others.
- `sent` means the provider accepted the email. It does not prove the email reached an inbox.

Inspect the outbox (counts only, never bodies, in shared logs):
`docker exec compose-postgres-1 psql -U aichat -d aichat -c "select kind, status, count(*) from email_outbox group by 1, 2"`.
Delivery is at most once: a run that dies between claiming an email and recording the result
leaves it `unknown`, never resent. `bun run status` prints the timer's state.

## Stop conditions and release order

A release goes in this order, and stops at the first failure:
1. code and checks;
2. GitHub `main` equals the checkout;
3. deploy;
4. health and MATCH;
5. `bun run smoke`;
6. backups/exports verified (before anything destructive);
7. destructive or infrastructure steps;
8. enabling features (jobs, email);
9. live proofs;
10. a final smoke and SHA check.

STOP, and `bun run rollback` if production is impaired, when:
- a health check fails, or MATCH or the SHA check fails;
- the smoke fails;
- a migration or precheck fails;
- the jobs worker fails its checks, or the outbox shows an inconsistent state (rows stuck in
  `sending`, or duplicates);
- a legacy-removal precondition, or health after it, fails;
- a temporary change on the owner's account cannot be restored and verified.

Never continue to a later or destructive step after a failure.

## Changing the database container on purpose

`install-units.sh` never replaces `/opt/aichat/shared/postgres/docker-compose.yml`. If a commit
changes `deploy/compose/docker-compose.yml`, the deploy prints a warning. Apply it deliberately:
take a backup (`systemctl start aichat-pg-backup`), copy the file into `/opt/aichat/shared/postgres/`,
then `systemctl restart aichat-postgres aichat-api` (a short outage). Never change the pinned
`name: compose` or the volume name `compose_pgdata`.

## Rehearsing a change to the deploy scripts: `bun run rehearse`

Optional, local, never a deploy prerequisite. It runs the real `deploy.sh`, `rollback.sh` and
`status.sh` against a throwaway systemd container that starts on the older release layout: the
cutover (and a failed cutover that puts it back), frontend-only, backend-only, docs-only, migration
and full-stack commits, a failed build, a rollback, two deploys at once, the refusals, and that
database rows and secrets survive. It prints how long each deploy took. Use it when you change
`deploy/`.

## Never do this

- Edit files in `/opt/aichat/app` by hand (the next deploy resets them; `bun run status` flags local edits).
- Run migrations outside a deploy, or `git clean` in `/opt/aichat/app`.
- `docker compose down -v`, or anything that recreates the database volume.
- Change `API_BASE_URL` in `web.env` (the frontend's default `:4000` is the old API on that host).
- Put secrets in Git.
