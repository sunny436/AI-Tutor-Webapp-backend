> **SUPERSEDED — 2026-08-20**
>
> This plan is COMPLETE. All six phases ran on 19-20 Aug 2026. Kept as the record of what was decided and why.
>
> Production moved to the Ubuntu VM `10.1.30.37` on 19 Aug 2026.
> The authoritative description is [INFRASTRUCTURE.md](../INFRASTRUCTURE.md).
> Everything below is kept for history and may be wrong.

# Production deploy — Ubuntu VM, reproducible from git

## Why

The product currently runs on a Windows laptop, inside an RDP session, with
Docker Desktop as a GUI app. Signing out kills every process; Docker Desktop
wedges on its own; nothing restarts without a person. That is not a deployment,
it is a demo that has been left running.

Target: `10.1.30.37` — Ubuntu 24.04.4, 4 cores, 3.8 GB RAM + 4 GB swap, 46 GB
free, KVM guest, 11 days uptime. Docker is already installed there as a
**systemd service**, which removes the single worst property of the Windows
setup.

Second requirement, equally important: a fresh machine must be reconstructable
from the git repositories plus secrets plus a backup. Today it is not.

## What runs

Four components. Nothing else.

| Component | Port | What it is |
|---|---|---|
| Convex | 3210 / 3211 | database + functions, in Docker |
| Python AI backend | 4000 | FastAPI, embedding model, calls Groq |
| Next.js frontend | 3000 | the web app |
| cloudflared | — | outbound tunnel; publishes 3000/4000/3210/3211 |

Two repositories are involved and both are needed:
`Ayurveda-` (python backend, tunnel, deploy) and `ayurveda-frontend`
(Next.js + Convex functions).

## Target layout

```
/opt/ayurveda/
  Ayurveda-/            git clone
  ayurveda-frontend/    git clone
/etc/ayurveda/          secrets, mode 600, NEVER in git
  convex.env  backend.env  frontend.env  cloudflared.env
/var/backups/convex/    nightly exports
```

Everything is a systemd unit. No scripts polling every 30 seconds, no scheduled
tasks that need a logged-in user, no supervisor of our own — systemd already is
one, and it is better than anything we would write.

```
docker.service              (stock)
  └─ convex.service         compose up for the Convex stack
ayurveda-backend.service    python, After=convex
ayurveda-frontend.service   next start, After=convex
cloudflared.service         installed by `cloudflared service install`
convex-backup.timer         nightly export + off-box copy
```

`Restart=always`, `After=`/`Requires=` ordering, and `MemoryMax=` on each unit.
The memory limits are not decoration: the Python backend peaks near 2 GB
loading bge-m3, and on a 3.8 GB box an unbounded spike would have the OOM killer
choose a victim — quite possibly Convex, i.e. the database.

## Making it reproducible

This is the part that does not exist yet. Add to `Ayurveda-`:

```
deploy/
  install.sh              idempotent bootstrap for a fresh Ubuntu 24.04
  systemd/*.service       the four units + backup timer
  compose/docker-compose.yml    Convex (moved out of self-hosted/)
  cloudflared/config.yml.template
  env/*.env.example       the secret CONTRACT for each component
  README.md               fresh machine -> running system
```

`install.sh` must be safe to re-run: install packages, clone or pull both repos,
render configs, install units, enable them. It must not touch secrets and must
not destroy data.

Disaster recovery then reduces to four steps, which is the whole point:

```
1. fresh Ubuntu 24.04
2. git clone both repos into /opt/ayurveda
3. drop /etc/ayurveda/*.env in from the password manager
4. deploy/install.sh  &&  convex import <latest backup>
```

## Phases

Each phase leaves the live site working. The cutover is one short window at the
end, not a big-bang migration.

**0 — Close the git gaps** *(nothing deployed yet)*
`Ayurveda-` has 15 unpushed commits and one uncommitted file. Until those are on
GitHub, "rebuild from git" would rebuild the wrong thing. Commit, push, verify
the remote matches local.

**1 — Write `deploy/`** *(still nothing deployed)*
Units, install.sh, compose, env examples, README. Commit and push.

**2 — Provision the VM by running `deploy/install.sh`**
Deliberately done by running the committed script rather than by hand, because a
script that has never been executed is a guess. Anything done manually here is a
bug in the script and gets fixed there, not on the box.

**3 — Move the data**
`convex export --include-file-storage` from the Windows deployment, import into
the VM's Convex. A backup already exists and the tooling is proven.

**4 — Move the tunnel**
Install cloudflared as a service on the VM using the same tunnel credentials and
the same four hostnames. DNS does not change. The tunnel can only run in one
place at a time, so this is the start of the cutover window.

**5 — Cutover and verify**
Rebuild the frontend on the VM so `NEXT_PUBLIC_CONVEX_URL` is baked correctly,
start every unit, then verify: sign in as a migrated account, open an OLD
consultation and continue it, upload a file, check `/library`.

**6 — Decommission and harden**
Stop everything on Windows. Enable the backup timer. Add the off-box copy, which
is still missing. Confirm units come back after `reboot`.

## Decisions worth stating

**Build on the VM, not on the laptop.** `next build` needs roughly 1-2 GB. With
4 GB swap it fits, but only if the Python backend is not resident at the same
time — so the build happens during the cutover window, before the backend unit
starts. Building on the laptop and copying `.next` would be faster and is the
fallback if the VM build proves too slow.

**Secrets never enter git.** They live in `/etc/ayurveda/*.env`, mode 600, root
owned, and are backed up separately. `deploy/env/*.env.example` documents every
variable each component needs. This includes `INSTANCE_SECRET` and the Convex
admin key, which are as sensitive as the database itself.

**Convex stays in Docker.** On Windows, Docker was the problem, because Docker
Desktop is a GUI application. On Linux it is a systemd service — auto-starting,
self-restarting, headless. The native Windows binary that was discussed earlier
solves a Windows problem that no longer exists here.

**cloudflared uses its own service installer** rather than a hand-written unit,
because it manages credentials and updates in ways worth not reimplementing.

## What this does not fix

Honest limits, so nobody is surprised later:

- **Single machine.** The VM is one host. Power, disk or network loss takes the
  site down. Real availability needs a second machine, and that is a different
  conversation about cost.
- **Groq.** The AI answers are generated on Groq's servers. Migrating the
  database does not change where consultation text is processed.
- **Backups on the same disk** are not backups. Until the off-box copy in phase
  6 is pointed somewhere real, a disk failure loses both the database and every
  archive of it.
