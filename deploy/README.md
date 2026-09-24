# Deploy (target configuration — not yet applied to production)

Ubuntu 24.04, systemd, Docker for PostgreSQL. See [INFRASTRUCTURE.md](../INFRASTRUCTURE.md) for the
layout and [docs/production-migration.md](../docs/production-migration.md) before touching a host
that runs the legacy stack.

```
compose/docker-compose.yml         PostgreSQL 16 + pgvector (127.0.0.1:5432, named volume)
systemd/aichat-postgres.service    starts the compose stack
systemd/aichat-api.service         migrates, then runs the API on 127.0.0.1:4100
systemd/aichat-web.service         the web app (frontend repository) on 127.0.0.1:3000
systemd/aichat-pg-backup.{service,timer}   nightly pg_dump (backup.sh)
env/{postgres,api,web}.env.example templates for /etc/aichat/*.env (chmod 600, never in git)
cloudflared/config.yml.template    ingress: the web app hostname only
install.sh                         idempotent provisioning; never writes secrets or imports data
infra-check.sh                     read-only comparison of a host with INFRASTRUCTURE.md
backup.sh                          pg_dump + rotation; restore instructions in its header
```

Fresh host (the production host has its own step-by-step: [production-migration.md](../docs/production-migration.md)):

```sh
sudo BACKEND_REPO=<git url> FRONTEND_REPO=<git url> bash deploy/install.sh   # stops and lists missing /etc/aichat/*.env
# write /etc/aichat/{postgres,api,web}.env from deploy/env/
sudo BACKEND_REPO=<git url> FRONTEND_REPO=<git url> bash deploy/install.sh   # completes; see below
```

`install.sh` enables PostgreSQL, the API (127.0.0.1:4100) and the backup timer, and builds the web
app without starting it. It leaves an existing Docker installation untouched and stops if :4100 or
:5432 is taken by anything other than its own units. `sudo systemctl enable --now aichat-web` starts
the web app on :3000.
