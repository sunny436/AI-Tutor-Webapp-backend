# Deploy

One repository, one release: a deployment takes **one commit** and ships the frontend and the
backend built from it, together. Ubuntu 24.04, systemd, Docker for PostgreSQL only.
How to deploy and roll back: [docs/deployment.md](../docs/deployment.md) and
[docs/rollback.md](../docs/rollback.md). Host layout: [INFRASTRUCTURE.md](../INFRASTRUCTURE.md).

```
deploy.sh                          THE deploy command (workstation): one commit -> the host -> live
rollback.sh                        roll back frontend + backend together (workstation)
server/release.sh                  on the host: prepare -> migrate -> validate trial copies -> switch
server/rollback.sh                 on the host: switch `current` back to a kept release
server/install-units.sh            installs units + the shared PostgreSQL files; never restarts
server/lib.sh                      shared helpers (checks, atomic switch, history)
install.sh                         one-time host preparation (packages, Bun, dirs, units, database)
infra-check.sh                     read-only health report, incl. "both apps run the same release"
backup.sh                          nightly pg_dump + rotation; restore steps in its header
compose/docker-compose.yml         PostgreSQL 16 + pgvector; project/volume names pinned
systemd/aichat-api.service         API from /opt/aichat/current/backend on 127.0.0.1:4100
systemd/aichat-web.service         web app from /opt/aichat/current/frontend on 127.0.0.1:3000
systemd/aichat-postgres.service    the database (from /opt/aichat/shared/postgres, not from releases)
systemd/aichat-pg-backup.{service,timer}   nightly backup at 03:15
env/{postgres,api,web}.env.example templates for /etc/aichat/*.env (chmod 600, never in git)
cloudflared/config.yml.template    ingress: the web app hostname only
```

Host layout:

```
/opt/aichat/releases/<commit>/   one complete release: backend/ (+ .venv) and frontend/ (+ build)
/opt/aichat/current              -> releases/<commit>   the ONLY switch; both services run from it
/opt/aichat/releases/HISTORY     every deploy, failure and rollback
/opt/aichat/shared/postgres/     database compose file + backup script (outside releases)
/etc/aichat/{api,web,postgres}.env   secrets and settings, shared by all releases
```
