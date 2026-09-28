# Deploy

`git push origin main`, then `bun run deploy`: the same commit goes to the production Git
repository on the host, the production checkout moves to it, and only the parts that changed are
rebuilt and restarted, then a local smoke check. No pull requests; GitHub CI is advisory.
Ubuntu 24.04, systemd, Docker for PostgreSQL only. How to deploy and roll back:
[docs/deployment.md](../docs/deployment.md) and [docs/rollback.md](../docs/rollback.md). Host
layout: [INFRASTRUCTURE.md](../INFRASTRUCTURE.md).

```
deploy.sh                          THE deploy (workstation): this checkout == GitHub main -> production Git -> update.sh
rollback.sh                        deploy an earlier commit the same way (workstation)
status.sh                          GitHub main vs production, what each part runs, health; MATCH or MISMATCH (workstation)
summary.sh                         the SHA lines and MATCH/MISMATCH that deploy, rollback and status end with
server/update.sh                   on the host, detached, locked: reset the checkout, then only what changed, then smoke
server/lib.sh                      shared helpers: content keys, health and chain checks, pinned Node/Bun, build limits
server/status.sh                   on the host: checkout, what each part runs, units, health (read-only)
server/install-units.sh            installs changed units + the shared PostgreSQL files; never restarts
install.sh                         one-time host preparation (packages incl. git, pinned Bun + Node, dirs, units, database)
infra-check.sh                     read-only health report: status.sh + ports, database, backups
backup.sh                          pg_dump + rotation (nightly, and before every migration); restore steps in its header
compose/docker-compose.yml         PostgreSQL 16 + pgvector; project/volume names pinned
systemd/aichat-api.service         the API from /opt/aichat/app/backend, 127.0.0.1:4100
systemd/aichat-web.service         the web app from /opt/aichat/app/frontend/apps/app on its pinned Node, 127.0.0.1:3000
systemd/aichat-postgres.service    the database (from /opt/aichat/shared/postgres, never part of a deploy)
systemd/aichat-pg-backup.{service,timer}   nightly backup at 03:15
systemd/aichat-jobs.{service,timer}         the jobs worker, once a minute; installed, NOT enabled (docs/deployment.md)
env/{postgres,api,web}.env.example templates for /etc/aichat/*.env (chmod 600, never in git)
cloudflared/config.yml.template    ingress: the web app hostname only
verify.mjs, verify/                optional: `bun run verify` runs CI's three jobs locally in a Linux container
ci-gate.mjs                        GitHub CI's verdict on a commit, shown by `bun run status` (advisory)
rehearsal/                         optional: `bun run rehearse` tries deploy changes on a throwaway systemd container
```

Host layout:

```
/opt/aichat/app.git              the production Git repository (deploys push here)
/opt/aichat/app                  the production checkout: RELEASE, backend/ (+ .venv), frontend/ (+ node_modules,
                                 .next, .next-prev, .next-cache)
/opt/aichat/app-state/           what each part runs (content keys), deployed, previous, HISTORY
/opt/aichat/runtime/             the pinned Node versions (checksum-verified downloads)
/opt/aichat/shared/postgres/     database compose file + backup script
/etc/aichat/{api,web,postgres}.env   secrets and settings, never in git, never touched by a deploy
```
