# Deployment

One repository, one commit, one release. A deployment ships the frontend **and** the backend built
from the same commit, validates them before users see them, and keeps the previous release for a
one-command rollback ([rollback.md](rollback.md)).

```
git commit ─► PR ─► merge to main (CI: backend + frontend + contract)
                         │
            bun run deploy    (workstation: deploy/deploy.sh)
                         │  git archive <commit> ──ssh──► host
                         ▼
 /opt/aichat/releases/<commit>/        1 prepare   backend venv, frontend install + build
                                       2 migrate   only if pending, only with --with-migrations
                                       3 validate  trial API :4101 + web :3001 on the real database
                                       4 switch    /opt/aichat/current -> releases/<commit>
                                                   restart API, then web; live checks
                                                   failed? back to the previous release, automatically
```

## What is guaranteed

| Guarantee | How |
|---|---|
| Frontend and backend are always the same commit | Both systemd units run from `/opt/aichat/current` (one symlink). `infra-check.sh` verifies both processes run from the same release directory. |
| Only commits from `main` reach production | `deploy.sh` refuses a commit that is not on the GitHub remote's `main` (`--allow-unpushed` is for emergencies). |
| Nothing live is touched until the release is proven | The release is built in its own directory, then started as trial copies on 127.0.0.1:4101 / :3001 against the production database. A request is sent through the trial web app, and the trial API's log must show the same request id: web → API → database. |
| A bad release does not stay live | After the switch the same checks run on the live ports; if they fail, `current` goes back to the previous release automatically. |
| The database is never reset | PostgreSQL is not part of releases. Its compose file lives in `/opt/aichat/shared/postgres`, and project and volume names are pinned (`compose` / `compose_pgdata`). |
| Secrets never enter git or a release | They live in `/etc/aichat/*.env` on the host and are shared by all releases. |

## Deploying

From the repository root, on a workstation that can read the GitHub repository and SSH to the host
(`root@10.1.30.37` by default; Git Bash works on Windows):

```sh
bun run deploy                                    # the tip of main on GitHub
bun run deploy -- --ref <commit>                  # a specific commit (must be on main)
bun run deploy -- --with-migrations               # the release has pending migrations
bun run deploy -- --prepare-only                  # build + validate on the host, do not switch
DEPLOY_HOST=root@other-host bun run deploy        # another host
```

Deploy commits whose CI run on GitHub passed. The script prints each phase, and ends with
`live: <commit> (previous: <commit>)`. Every deploy, failure and rollback is appended to
`/opt/aichat/releases/HISTORY`. The host keeps the live release, the previous one and one more;
older builds are deleted.

Check a host at any time (read-only):

```sh
ssh root@10.1.30.37 bash /opt/aichat/current/deploy/infra-check.sh
```

### Migrations

A release's migrations run **before** the switch, while the current release keeps serving. So a
migration must work with the code that is live when it runs (expand/contract): add columns and
tables, backfill, and only drop what the previous release no longer uses, in a later release. A
release with pending migrations stops at step 2 until you pass `--with-migrations`. Deploying code
that is older than the database schema needs `--allow-older-schema`. `backend/scripts/migration_status.py`
reports where the database stands for any code version.

### Downtime

Validation happens before anything live changes. The switch restarts the API and then the web app,
so during those seconds users see "temporarily unavailable" and a reply that is being generated is
saved as cancelled. Measured in the production-layout rehearsal: page loads under 1 s; requests
that reach the API about 7 s (mostly API start-up).

## One-time host preparation

Only for a new host (the current production host already has all of this). Copy the repository
there once and run the installer:

```sh
git archive --format=tar.gz HEAD | ssh root@<host> 'mkdir -p /root/aichat-setup && tar -xzf - -C /root/aichat-setup'
ssh root@<host> bash /root/aichat-setup/deploy/install.sh     # lists the secret files it needs
# write /etc/aichat/{postgres,api,web}.env from deploy/env/*.example (chmod 600), then run it again
```

It installs Python 3.12 and Bun 1.3.14, leaves an existing Docker alone, creates
`/opt/aichat/{releases,incoming,shared}`, installs the systemd units and starts PostgreSQL and the
nightly backup. Then `bun run deploy` from a workstation. The Cloudflare Tunnel is configured
separately (`deploy/cloudflared/config.yml.template`: the web app hostname only).

## The first deploy on the current production host

Production still runs the older layout: two checkouts, `/opt/aichat/backend` and `/opt/aichat/frontend`.
The first `bun run deploy` moves it to releases. It needs the owner's explicit approval.

- **It changes:** the four systemd units (the replaced ones are kept as `*.before-<time>`),
  `/opt/aichat/current`, and `/opt/aichat/shared/postgres`.
- **It does not change:** the database container (not restarted; the pinned names keep the same volume
  when it next starts), `/etc/aichat/*.env`, the old checkouts (left in place), the legacy services
  or the Cloudflare configuration.
- **If it fails**, `release.sh` puts the old unit files back and restarts the old layout by itself.
  This was rehearsed on a copy of the production layout.
- **Afterwards**, once the new layout has run for a few days, `/opt/aichat/backend`, `/opt/aichat/frontend`
  and `/root/aichat-bundles` can be deleted by hand.

## Environment variables

All production values live in `/etc/aichat/*.env` (root, mode 600). Templates are in `deploy/env/`.
For local development use `backend/.env` (from `backend/.env.example`) and
`frontend/apps/app/.env.local` (from `.env.example`).

| File | Variable | Used by | When | Secret |
|---|---|---|---|---|
| `web.env` | `API_BASE_URL` | frontend server (BFF, server components) | runtime | no. **The link to the backend**: must be `http://127.0.0.1:4100` (the frontend's default `:4000` is the development port; `release.sh` refuses a web.env without it) |
| `web.env` | `NEXT_PUBLIC_SITE_URL` | frontend (metadata URLs) | **build time** (baked into the release build) | no |
| `web.env` | `NEXT_PUBLIC_SENTRY_DSN` | frontend error reporting, only bundled if set | build time | no (public DSN) |
| `api.env` | `SECRET_KEY` | backend (HMAC of email codes) | runtime | **yes** |
| `api.env` | `DATABASE_URL` | backend | runtime | **yes** (contains the password) |
| `api.env` | `APP_ENV`, `APP_NAME`, `LOG_LEVEL`, `TRUST_FORWARDED_FOR`, `ALLOWED_ORIGINS`, `MAX_BODY_BYTES` | backend | runtime | no |
| `api.env` | `EMAIL_BACKEND`, `EMAIL_FROM`, `SMTP_HOST/PORT/STARTTLS/SSL`, `OLLASTACK_BASE_URL`, `OLLASTACK_MAILBOX_ID` | backend email | runtime | no |
| `api.env` | `SMTP_USERNAME`, `SMTP_PASSWORD`, `OLLASTACK_TOKEN` | backend email | runtime | **yes** |
| `api.env` | `LLM_*` names, base URLs, models, timeouts | backend | runtime | no |
| `api.env` | `LLM_PRIMARY_API_KEY`, `LLM_FALLBACK_API_KEY`, `EMBEDDING_API_KEY` | backend | runtime | **yes** |
| `api.env` | `RAG_*`, `EMBEDDING_*` (other), `CHAT_*`, `STREAM_*`, auth limits | backend | runtime | no |
| `postgres.env` | `POSTGRES_USER`, `POSTGRES_DB`, `BACKUP_DIR`, `KEEP_DAYS` | database, backup | runtime | no |
| `postgres.env` | `POSTGRES_PASSWORD` | database, backup | runtime | **yes** |

Changing a runtime value: edit the file, then `systemctl restart aichat-api` (or `aichat-web`).
Changing a build-time value (`NEXT_PUBLIC_*`): edit `web.env`, then deploy (the frontend is rebuilt
for the next release; the live build keeps the old value).

## Changing the database container on purpose

`install-units.sh` never replaces `/opt/aichat/shared/postgres/docker-compose.yml`. If a release
changes `deploy/compose/docker-compose.yml`, the deploy prints a warning. Apply it deliberately:
take a backup (`systemctl start aichat-pg-backup`), copy the new file into
`/opt/aichat/shared/postgres/`, then `systemctl restart aichat-postgres aichat-api`. This causes a
short outage. Never change the pinned `name: compose` or the volume name `compose_pgdata`.

## Never do by hand

- Edit files inside `/opt/aichat/releases/*`: releases are immutable. Fix it in git and deploy.
- Point `/opt/aichat/current` somewhere by hand, except in the emergency steps in [rollback.md](rollback.md).
- Run migrations outside `release.sh` (the API unit deliberately does not migrate on start).
- Rename the compose project or volume, or run `docker compose down -v`.
- Put a secret in the repository, or change `API_BASE_URL` in `web.env`.
- Use the old deployment (git bundles, `install.sh` with `BACKEND_REPO`/`FRONTEND_REPO`): it no longer exists.
