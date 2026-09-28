# Deploy

> **AI Tutor is released as one application. Frontend and backend are never independently
> deployed to production.**

A deployment takes **one commit** of `main` with successful CI and ships the frontend and the
backend built from it, together. Ubuntu 24.04, systemd, Docker for PostgreSQL only.
How to deploy and roll back: [docs/deployment.md](../docs/deployment.md) and
[docs/rollback.md](../docs/rollback.md). Host layout: [INFRASTRUCTURE.md](../INFRASTRUCTURE.md).

```
deploy.sh                          THE deploy command (deploy machine): the verified commit checked out -> the host -> live
rollback.sh                        roll back frontend + backend together (workstation)
status.sh                          what production runs, and "INVARIANT OK" or "FAIL" (workstation)
verify.mjs                         bun run verify: the three CI jobs in a Linux container on git archive of HEAD -> evidence
verify/                            its container (Dockerfile), services (compose.yml) and CI's commands (run-ci.sh)
local-gate.mjs                     the deploy gate: passing evidence for this exact commit and tree (tests in tests/)
ci-gate.mjs                        GitHub CI's verdict on a commit: informational (bun run status), not a gate
server/bootstrap.sh                on the host, detached: lock, unpack the release, verify it, run release.sh
server/verify-release.py           every file of a release against its commit (git blob hashes)
server/release.sh                  on the host: prepare -> migrate -> validate trial copies -> switch
server/rollback.sh                 on the host: switch back to the previously live release
server/status.sh                   on the host: pointer, reported releases, processes, integrity
server/install-units.sh            installs units + the shared PostgreSQL files; never restarts
server/lib.sh                      shared helpers (checks, switch order, invariant proof, history)
install.sh                         one-time host preparation (packages, pinned Bun + Node, dirs, units, database)
infra-check.sh                     read-only health report: status.sh + ports, database, backups
backup.sh                          pg_dump + rotation (nightly, and before every migration); restore steps in its header
compose/docker-compose.yml         PostgreSQL 16 + pgvector; project/volume names pinned
systemd/aichat-api.service         API from the release /opt/aichat/current resolves to, 127.0.0.1:4100
systemd/aichat-web.service         web app from that same release on its pinned Node, 127.0.0.1:3000
systemd/aichat-postgres.service    the database (from /opt/aichat/shared/postgres, not from releases)
systemd/aichat-pg-backup.{service,timer}   nightly backup at 03:15
systemd/aichat-jobs.{service,timer}         the jobs worker, once a minute; installed, NOT enabled (docs/deployment.md)
env/{postgres,api,web}.env.example templates for /etc/aichat/*.env (chmod 600, never in git)
cloudflared/config.yml.template    ingress: the web app hostname only
rehearsal/                         bun run rehearse: the whole model on a throwaway systemd container
```

Host layout:

```
/opt/aichat/releases/<commit>/   one complete release: RELEASE, MANIFEST, CI.json, backend/ (+ .venv),
                                 frontend/ (+ build), deploy-<id>.log
/opt/aichat/current              -> releases/<commit>   the ONLY switch; both services run from it
/opt/aichat/releases/HISTORY     every deploy, migration, failure and rollback
/opt/aichat/releases/LIVE-STACK  the releases that were live, in order (rollback pops it)
/opt/aichat/runtime/             the pinned Node versions (checksum-verified downloads)
/opt/aichat/shared/postgres/     database compose file + backup script (outside releases)
/etc/aichat/{api,web,postgres}.env   secrets and settings, shared by all releases
```

There is no command, script or unit that deploys only the frontend or only the backend.
