# Infrastructure

## Status

| | |
|---|---|
| Target (this branch) | PostgreSQL 16 + pgvector, the chat API and the web app on one Ubuntu 24.04 host, under systemd. Described below and in [deploy/](deploy/). |
| Production today | **Still the legacy stack.** Nothing in this branch has been applied to the host. Cutover is a separate, approved step: [docs/production-migration.md](docs/production-migration.md). |

## Target layout

| Unit | Listens | What |
|---|---|---|
| `aichat-postgres.service` | 127.0.0.1:5432 | PostgreSQL 16 + pgvector via `deploy/compose/docker-compose.yml`; the only datastore |
| `aichat-api.service` | 127.0.0.1:4100 | FastAPI chat API; runs `alembic upgrade head` before start; `MemoryMax=900M`. Port 4100 (not the development 4000) so it can run beside the legacy API during the cutover |
| `aichat-web.service` | 127.0.0.1:3000 | Next.js web app from the frontend repository (enabled after its migration) |
| `aichat-pg-backup.timer` | – | nightly `pg_dump` to `/var/backups/aichat`, 30-day retention (`deploy/backup.sh`) |
| `cloudflared` | outbound | publishes **only the web app hostname** (`deploy/cloudflared/config.yml.template`) |

```
user ──► Cloudflare ──► cloudflared ──► web app :3000 ──(loopback)──► API :4100 ──► PostgreSQL :5432
```

Nothing but the web app is reachable from outside the host. Secrets live in `/etc/aichat/*.env`
(mode 600), never in git; templates are in `deploy/env/`.

## Operations

```sh
systemctl status aichat-postgres aichat-api aichat-web
journalctl -u aichat-api -f          # JSON logs: request_id, user_id, latency, ttft, tokens — no message content
bash deploy/infra-check.sh           # compares the host with this document
```

Restore a backup: see the header of `deploy/backup.sh`.

## Known limits

- One host, no staging environment, no replica: a host failure is an outage until restored
  from the nightly dump. Copy dumps off the host (see `deploy/backup.sh`).
- In-flight replies are tracked per process; the API is designed to run as a single instance per
  host (the database remains authoritative, so a second instance is safe but not load-balanced).
