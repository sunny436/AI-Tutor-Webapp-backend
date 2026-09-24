# Deployment

> **AI Tutor is released as one application. Frontend and backend are never independently
> deployed to production.**

One repository, one `main`, one commit, one release, one deploy command, one rollback. Every
production release is identified by one immutable commit SHA, and production runs the web app
and the API from that same release, at all times.

```
feature branch ─► PR ─► main ─► CI on that exact commit: Backend + Frontend + Integration
                                        │
                           bun run deploy   (workstation)
                                        │  CI gate · git archive <commit> + file manifest ──ssh──►
                                        ▼
 /opt/aichat/releases/<commit>/   systemd unit aichat-deploy-<commit>-<id> (detached)
    verify   every file == the commit (git blob hashes)
    prepare  backend from requirements.lock (hashes) · frontend on the pinned Node
    migrate  only with --with-migrations, after a fresh backup
    validate trial API :4101 + web :3001 on the real database: both report <commit>,
             web -> API -> database proven by request id
    switch   stop web · /opt/aichat/current -> <commit> · restart API · start web
             prove: pointer == API release == web release == every process's release
             failed? -> the previous release, automatically
```

## The guarantees, and what enforces them

| Guarantee | Enforced by |
|---|---|
| Frontend and backend always run the same commit | Both units run from `/opt/aichat/current`, resolved once at start. Every switch stops the web app **before** the pointer moves and starts it **after** the API runs the new release, so an old web app never serves against a new API or the reverse. Afterwards the deploy proves pointer = API-reported release = web-reported release = the release of every `aichat-api` / `aichat-web` process, or rolls back. |
| Only approved commits reach production | `deploy.sh` fetches `main` from the pinned repository URL, accepts only commits of `main`'s own history, and requires GitHub CI **success for that exact commit** on all three jobs (`deploy/ci-gate.mjs`, fail closed). Branch protection is not available on this repository's plan; this gate is the enforcement. |
| A release is exactly its commit | `git archive` of the commit, never a working tree. Every file is checked against the commit's `git ls-tree` hashes on arrival, before the switch, on rollback and by `bun run status`. |
| What CI tested is what runs | The backend installs `backend/requirements.lock` (every package pinned, hashes required); the frontend is built and served on the release's `.node-version` Node; Bun is `.bun-version`. CI uses the same three files. |
| Nothing live changes until the release is proven | Build, migrations check and trial copies all happen before the switch; any failure stops there (fail closed). |
| A bad release does not stay live | Live checks after the switch; on failure the previous release is restored automatically. |
| A deploy cannot be interrupted half-way | The host side runs as a detached systemd unit; losing SSH or pressing Ctrl+C on the workstation does not stop it. One deploy or rollback at a time (lock). |
| Production is never starved by a build | Free disk and memory are checked first; builds run in a memory-capped, low-priority scope, so the kernel kills the build, not production or PostgreSQL. |
| The database is never reset or rolled back | PostgreSQL is not part of releases (`/opt/aichat/shared/postgres`, pinned names `compose` / `compose_pgdata`). Migrations need an explicit flag and a successful backup first. |

## Release identity: what is running

```sh
bun run status        # read-only; exits 1 unless "INVARIANT OK"
```

```
release
  ok    /opt/aichat/current -> 3f2a…
        backend  (aichat-api) reports release=3f2a…   processes run: 3f2a…
        frontend (aichat-web) reports release=3f2a…   processes run: 3f2a…   runtime: …/node-v24.19.0-linux-x64/bin/node
  ok    every aichat-api and aichat-web process runs 3f2a…
  ok    frontend release == backend release == 3f2a…
  ok    web runs the release's pinned Node
integrity
  ok    files verified: all 270 files match the commit
units …
INVARIANT OK: frontend and backend both run release 3f2a…
```

Each app reports the release it runs: the API at `GET /health` and the web app at
`GET /api/health` (`{"status": "ok", "release": "<commit>"}`), read from the `RELEASE` file of the
release the process started from. The web app shows it to local requests only; through Cloudflare
the public site answers `{"status": "ok"}` without the commit.

## Deploying

From the repository root, on a workstation that can read the GitHub repository and SSH to the host
(Git Bash works on Windows):

```sh
bun run deploy                                     # the tip of main (the normal case)
bun run deploy -- --with-migrations                # the release has pending migrations
bun run deploy -- --prepare-only                   # build + validate on the host, do not switch
bun run deploy -- --ref <commit> --older           # an older commit of main (prefer bun run rollback)
```

It shows the release, its CI result and what is live, and asks you to type the first 7 characters
of the commit (`--yes` for automation). The full log is in the journal (`journalctl -u
aichat-deploy-*`) and in `/opt/aichat/releases/<commit>/deploy-<id>.log`; every deploy,
migration, failure and rollback is appended to `/opt/aichat/releases/HISTORY`.

### Downtime

Validation happens before anything live changes. The switch itself makes the whole site
unavailable for a few seconds (about 7–8 s: the web app is down while the API restarts), which is
the price of never serving a mixed pair. A reply being generated at that moment is saved as
cancelled.

### Migrations

- A release's migrations run **before** the switch, while the current release still serves, so
  every migration must work with the code that is live when it runs (expand/contract: add, then
  backfill, then drop only what the previous release no longer uses, in a later release).
- Pending migrations stop the deploy unless `--with-migrations` is given; then a backup
  (`aichat-pg-backup`) must succeed first, and the migration is recorded in `HISTORY` with the
  backup file.
- Deploying or rolling back to code older than the schema needs `--allow-older-schema`, and is only
  safe for backward-compatible migrations. The database is never rolled back automatically; to undo
  a schema change, write a new migration.
- `backend/scripts/migration_status.py` reports where the database stands for any code version.

## One-time host preparation

Only for a new host. Copy the repository there once and run the installer:

```sh
git archive --format=tar.gz HEAD | ssh root@<host> 'mkdir -p /root/aichat-setup && tar -xzf - -C /root/aichat-setup'
ssh root@<host> bash /root/aichat-setup/deploy/install.sh     # lists the secret files it needs
# write /etc/aichat/{postgres,api,web}.env from deploy/env/*.example (chmod 600), then run it again
```

It installs Python 3.12, the pinned Bun and Node, leaves an existing Docker alone, creates
`/opt/aichat/{releases,incoming,shared,runtime}`, installs the units and starts PostgreSQL and the
nightly backup. Then `bun run deploy -- --with-migrations` (a new database is empty, so the first
release has every migration pending; without the flag it stops before the switch).

## The first release deploy on the current production host

Production still runs the older two-checkout layout (`/opt/aichat/backend` and
`/opt/aichat/frontend`, from two repositories and two commits). The first `bun run deploy` moves it
to releases. **It needs the owner's explicit approval.**

- **It changes:** the systemd units (the replaced ones are kept as `*.before-<time>`),
  `/opt/aichat/current`, `/opt/aichat/shared/postgres`, `/opt/aichat/runtime` (the pinned Node).
- **It does not change:** the database container (not restarted; the pinned names keep the same
  volume), `/etc/aichat/*.env`, the old checkouts (left in place, unused), the legacy services or
  Cloudflare.
- **If it fails**, it restores the old unit files and restarts the old layout by itself (rehearsed).
- **Afterwards**, once the release layout has run for a few days, delete `/opt/aichat/backend`,
  `/opt/aichat/frontend` and `/root/aichat-bundles` (they are only a trap: running their old
  `install.sh` would bring back two independently deployed checkouts; `bun run status` reports them).

## Environment variables

All production values live in `/etc/aichat/*.env` (root, mode 600), shared by every release and
never in git. Templates: `deploy/env/`. Local development: `backend/.env` and
`frontend/apps/app/.env.local`.

| File | Variable | Used by | When | Secret |
|---|---|---|---|---|
| `web.env` | `API_BASE_URL` | frontend server (BFF, server components) | runtime | no. **The link to the backend**: must be `http://127.0.0.1:4100`; a release refuses anything else |
| `web.env` | `NEXT_PUBLIC_SITE_URL` | frontend (metadata URLs) | **build time** (baked into the release build; required) | no |
| `web.env` | `NEXT_PUBLIC_SENTRY_DSN` | frontend error reporting, only bundled if set | build time | no (public DSN) |
| `api.env` | `SECRET_KEY`, `DATABASE_URL` | backend | runtime | **yes** |
| `api.env` | `SMTP_USERNAME`, `SMTP_PASSWORD`, `OLLASTACK_TOKEN` | backend email | runtime | **yes** |
| `api.env` | `LLM_PRIMARY_API_KEY`, `LLM_FALLBACK_API_KEY`, `EMBEDDING_API_KEY` | backend | runtime | **yes** |
| `api.env` | `APP_ENV`, `APP_NAME`, `EMAIL_*`, `SMTP_HOST/PORT/…`, `OLLASTACK_BASE_URL/MAILBOX_ID`, `LLM_*` names/URLs/models, `RAG_*`, `EMBEDDING_*` (other), `CHAT_*`, `STREAM_*`, limits | backend | runtime | no |
| `postgres.env` | `POSTGRES_PASSWORD` | database, backup | runtime | **yes** |
| `postgres.env` | `POSTGRES_USER`, `POSTGRES_DB`, `BACKUP_DIR`, `KEEP_DAYS` | database, backup | runtime | no |

A runtime value takes effect on the next restart of the service; a build-time value
(`NEXT_PUBLIC_*`) on the next deploy (the release is rebuilt when they change).

## Changing the database container on purpose

`install-units.sh` never replaces `/opt/aichat/shared/postgres/docker-compose.yml`. If a release
changes `deploy/compose/docker-compose.yml`, the deploy prints a warning. Apply it deliberately:
take a backup (`systemctl start aichat-pg-backup`), copy the file into `/opt/aichat/shared/postgres/`,
then `systemctl restart aichat-postgres aichat-api` (a short outage). Never change the pinned
`name: compose` or the volume name `compose_pgdata`.

## Proving the model: `bun run rehearse`

A throwaway Ubuntu 24.04 container with real systemd, PostgreSQL + pgvector and SSH, prepared by
`install.sh`, on which the real `deploy.sh`, `rollback.sh` and `status.sh` run through
frontend-only, backend-only and combined releases, a broken build, a broken backend, a failed live
check, double rollback, migration guards, every bypass and a killed SSH connection, while a poller
checks that the two apps never report different releases. Local only (Docker, about 45 minutes).

## Never do this

- **Deploy the frontend or the backend on its own.** There is no command for it and there never
  will be; a change to either half is released as a new commit of the whole application.
- Run `release.sh` or `rollback.sh` by hand (they refuse), edit files inside
  `/opt/aichat/releases/*` (verified against the commit; a changed release is refused), or point
  `/opt/aichat/current` somewhere by hand except in the emergency steps of [rollback.md](rollback.md).
- Deploy a commit that is not on `main`, or whose CI did not pass (refused).
- Run migrations outside a deploy, rename the compose project or volume, or `docker compose down -v`.
- Put a secret in the repository, or change `API_BASE_URL` in `web.env`.
- Use the retired deployment (git bundles, `install.sh` with `BACKEND_REPO`/`FRONTEND_REPO`, the
  old frontend repository): it no longer exists.
