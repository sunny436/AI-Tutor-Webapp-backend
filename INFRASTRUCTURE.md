# Infrastructure

> **AI Tutor is released as one application. Frontend and backend are never independently
> deployed to production.**

## Status

| | |
|---|---|
| Target (this repository) | One Ubuntu 24.04 host under systemd: PostgreSQL 16 + pgvector, the API and the web app, deployed as **one release** per commit of `main` with successful CI. Described below, in [deploy/](deploy/) and in [docs/deployment.md](docs/deployment.md). |
| Production today | `ayur.namahos.com` serves this application (since 2026-09-24), still from the earlier two-checkout layout (`/opt/aichat/backend`, `/opt/aichat/frontend`). Moving it to the release layout is the first `bun run deploy` ([deployment.md](docs/deployment.md#the-first-release-deploy-on-the-current-production-host)) and needs the owner's approval. The legacy Ayurveda services still run beside it for rollback ([production-migration.md](docs/production-migration.md)). |

## Layout

| Unit | Listens | What |
|---|---|---|
| `aichat-postgres.service` | 127.0.0.1:5432 | PostgreSQL 16 + pgvector (Docker, `/opt/aichat/shared/postgres/docker-compose.yml`; volume `compose_pgdata`); the only datastore; not part of releases |
| `aichat-api.service` | 127.0.0.1:4100 | FastAPI API from the release `/opt/aichat/current` resolves to at start; `MemoryMax=900M`; never migrates on start; `GET /health` reports its release |
| `aichat-web.service` | 127.0.0.1:3000 | Next.js web app from that same release, on the release's pinned Node (`.node-version`); reaches the API through `API_BASE_URL`; `GET /api/health` reports its release (loopback only) |
| `aichat-pg-backup.timer` | – | nightly `pg_dump` at 03:15 to `/var/backups/aichat`, 30-day retention; the same service runs before every migration |
| `aichat-deploy-*`, `aichat-rollback-*` | – | transient units: one deploy or rollback, detached from SSH, one at a time |
| `cloudflared` | outbound | publishes **only the web app hostname** (`deploy/cloudflared/config.yml.template`) |

```
user ──► Cloudflare ──► cloudflared ──► web :3000 ──(loopback)──► API :4100 ──► PostgreSQL :5432
                                            └──── both from /opt/aichat/current -> releases/<commit>
```

```
/opt/aichat/releases/<commit>/        complete releases (the last live ones: at least the live and the previous)
/opt/aichat/current                   -> the live release; the only thing a deploy or rollback switches
/opt/aichat/releases/HISTORY          every deploy, migration, failure and rollback (operator, CI run, backup)
/opt/aichat/releases/LIVE-STACK       the releases that were live, in order
/opt/aichat/runtime/                  pinned Node runtimes
/opt/aichat/shared/postgres/          database compose file + backup script
/etc/aichat/{api,web,postgres}.env    settings and secrets (mode 600), never in git; templates in deploy/env/
```

Nothing but the web app is reachable from outside the host.

## Operations

```sh
bun run status                                   # workstation: one release for both apps? (INVARIANT OK/FAIL)
bash /opt/aichat/current/deploy/infra-check.sh   # on the host: status + services, ports, database, backups
systemctl status aichat-postgres aichat-api aichat-web
journalctl -u aichat-api -f                      # JSON logs: request_id, user_id, latency, tokens; no message content
journalctl -u 'aichat-deploy-*'                  # deploy logs (also releases/<commit>/deploy-<id>.log)
tail /opt/aichat/releases/HISTORY
```

Deploy and roll back from a workstation: `bun run deploy`, `bun run rollback`. Restore a database
backup: see the header of `deploy/backup.sh`.

## Known limits

- One host, no staging environment, no replica: a host failure is an outage until restored from
  the nightly dump. Copy dumps off the host (see `deploy/backup.sh`).
- A release switch makes the whole site unavailable for about 7–8 s (web stopped, API restarted,
  web started, so the two never run different releases); a reply being generated at that moment is
  saved as cancelled.
- In-flight replies are tracked per process; the API is designed to run as a single instance per
  host (the database remains authoritative, so a second instance is safe but not load-balanced).
- The services run as root, and there is no alerting: `bun run status` and `infra-check.sh` are
  run by hand.
