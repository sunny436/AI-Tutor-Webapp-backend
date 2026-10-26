# Infrastructure

## Status

| | |
|---|---|
| Target (this repository) | One Ubuntu 24.04 host under systemd: PostgreSQL 16 + pgvector, the API and the web app, run from one production checkout of `main` (`/opt/aichat/app`); a deploy rebuilds and restarts only the parts a commit changes. Described below, in [deploy/](deploy/) and in [docs/deployment.md](docs/deployment.md). |
| Production today | `ayur.namahos.com` serves this application from the production checkout (`/opt/aichat/app`) only. On 2026-09-29 the owner removed the earlier release layout (`/opt/aichat/{releases,current}`), the two-checkout leftovers (`/opt/aichat/{backend,frontend}`, `/root/aichat-bundles`, saved units `aichat-*.before-*`) and the legacy Ayurveda services; PostgreSQL's container is the only one left. The history is in [production-migration.md](docs/production-migration.md). |

## Layout

| Unit | Listens | What |
|---|---|---|
| `aichat-postgres.service` | 127.0.0.1:5432 | PostgreSQL 16 + pgvector (Docker, `/opt/aichat/shared/postgres/docker-compose.yml`; volume `compose_pgdata`); the only datastore; not part of releases |
| `aichat-api.service` | 127.0.0.1:4100 | FastAPI API from `/opt/aichat/app/backend`; `MemoryMax=900M`; never migrates on start; `GET /health` reports the commit it started from |
| `aichat-web.service` | 127.0.0.1:3000 | Next.js web app from `/opt/aichat/app/frontend/apps/app` (the `.next` build), on the pinned Node (`.node-version`); reaches the API through `API_BASE_URL`; `GET /api/health` reports its commit (loopback only) |
| `aichat-pg-backup.timer` | – | nightly `pg_dump` at 03:15 to `/var/backups/aichat` (without the rows of `file_chunks`, which are rebuilt, or of `auth_sessions` and `auth_verifications`, which hold live tokens and codes; without the NCERT service's schema), `KEEP_DAYS` retention (7); refuses to dump with less than twice the database's size free; the same service runs before every migration |
| `aichat-deploy-*` | – | transient units: one deploy or rollback, detached from SSH, one at a time |
| `aichat-extract-*` | – | transient units started by the API: one student file read in a sandbox (no network, no secrets, 512 MB, 300 s); needs Tesseract (`eng`, `hin`) on the host |
| `cloudflared` | outbound | publishes **only the web app hostname** (`deploy/cloudflared/config.yml.template`) |

```
user ──► Cloudflare ──► cloudflared ──► web :3000 ──(loopback)──► API :4100 ──► PostgreSQL :5432
                                            └──── both from the checkout /opt/aichat/app
```

```
/opt/aichat/app.git                   the production Git repository (deploys push here)
/opt/aichat/app                       the production checkout: the code that runs, its .venv, node_modules and builds
/opt/aichat/app-state/HISTORY         every deploy and rollback: who, which commit, what ran, how long
/opt/aichat/runtime/                  pinned Node runtimes
/opt/aichat/shared/postgres/          database compose file + backup script
/etc/aichat/{api,web,postgres}.env    settings and secrets (mode 600), never in git; templates in deploy/env/
```

Nothing but the web app is reachable from outside the host.

## Operations

```sh
bun run status                                   # workstation: GitHub main vs production, health (MATCH/MISMATCH)
bash /opt/aichat/app/deploy/infra-check.sh       # on the host: status + services, ports, database, backups
systemctl status aichat-postgres aichat-api aichat-web
journalctl -u aichat-api -f                      # JSON logs: request_id, user_id, latency, tokens; no message content
journalctl -u 'aichat-deploy-*'                  # deploy logs
tail /opt/aichat/app-state/HISTORY
```

Deploy and roll back from a workstation: `git push origin main && bun run deploy`, `bun run rollback`. Restore a database
backup: see the header of `deploy/backup.sh`.

## Known limits

- One host, no staging environment, no replica: a host failure is an outage until restored from
  the nightly dump. Copy dumps off the host (see `deploy/backup.sh`).
- A deploy restarts only what changed: the web app is unavailable for about 3–5 s when the
  frontend changes, the API when the backend changes (a reply being generated at that moment is
  saved as cancelled). While a deploy runs, the web app and the API can briefly run different
  commits; `/v1` changes are additive, so that is safe.
- In-flight replies are tracked per process; the API is designed to run as a single instance per
  host (the database remains authoritative, so a second instance is safe but not load-balanced).
- The services run as root, and there is no alerting: `bun run status` and `infra-check.sh` are
  run by hand.
