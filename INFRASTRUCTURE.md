# Infrastructure

**This file is the authoritative description of where Ayurveda runs and how it is
deployed.** Where any other document in either repository disagrees with this
one, this one is correct — several of them describe a Windows laptop that stopped
being production on 19 Aug 2026.

Verify it rather than trust it: `bash deploy/infra-check.sh` compares every
claim below against the live machine and reports drift. See
[Keeping this true](#keeping-this-true).

Last verified against the live host: **2026-08-20**.

---

## 1. The machine

Everything runs on one Ubuntu VM. There is no second machine, no cloud
provider, and no container orchestrator.

| | |
|---|---|
| Hostname | `askhat-linux-325-37` |
| Address | `10.1.30.37` (private LAN — not reachable from the internet) |
| OS | Ubuntu 24.04.4 LTS, kernel 6.8.0 |
| Virtualisation | KVM guest |
| CPU / RAM | 4 cores / 3.8 GB + 4 GB swap |
| Disk | 48 GB, ~24 GB free |
| Access | `ssh root@10.1.30.37` with the key on the operator workstation |

Swap is not optional here. The Python backend peaks near 2 GB loading its
embedding model and `next build` wants another 1–2 GB; on 3.8 GB those two
cannot coexist without it.

### What is NOT here

- **The Windows laptop `10.1.30.108`** was production until 19 Aug 2026. Its
  services are stopped and its scheduled task `AyurvedaSite` is disabled. It
  still holds the pre-migration Convex volume and backups as a rollback path,
  and it is still where the only copies of some secrets live. It serves no
  traffic.
- **Any staging environment.** There is one machine and it is production.

---

## 2. Services

All five are systemd units. Nothing needs a logged-in user, a desktop session,
or a GUI application — which is the single most important difference from the
Windows setup that preceded this.

| Unit | Port | What it is | Limits |
|---|---|---|---|
| `docker.service` | — | container runtime (stock Ubuntu package) | — |
| `convex.service` | 3210, 3211 | **the database** — `docker compose up -d` | — |
| `ayurveda-backend.service` | 4000 | FastAPI + bge-m3 embeddings, calls the LLM provider | `MemoryHigh=2200M` `MemoryMax=2600M` |
| `ayurveda-frontend.service` | 3000 | Next.js production server (`bun run start`) | `MemoryMax=900M` |
| `cloudflared.service` | — | outbound tunnel; publishes all four ports | — |
| `convex-backup.timer` | — | nightly snapshot, 03:15 + up to 5 min jitter | — |

Ordering is declared, not hoped for: both app units are `After=convex.service`,
and `convex.service` is `Requires=docker.service`. All are `enabled`, so a
reboot brings the whole stack back with nobody logged in.

The memory limits are load-bearing rather than decorative. On a 3.8 GB box an
unbounded Python spike lets the kernel choose a victim, and the victim could be
Convex — i.e. the database. Capped, a bad day kills only the process that caused
it, and systemd restarts that one.

```sh
systemctl status convex ayurveda-backend ayurveda-frontend cloudflared
journalctl -u ayurveda-backend -f
systemctl list-timers convex-backup
```

### Convex dashboard

Published on `6791` but deliberately **not** in the tunnel — it has full
read/write access to the database and only the admin key in front of it. Reach
it over an SSH tunnel from a workstation:

```sh
ssh -L 6791:127.0.0.1:6791 root@10.1.30.37   # then open http://127.0.0.1:6791
```

---

## 3. How traffic arrives

Nothing listens on a public address. The tunnel makes an **outbound** connection
to Cloudflare, so the VM's IP is never exposed and no inbound port is open.

```
user ──▶ *.namahos.com ──▶ Cloudflare edge ──▶ cloudflared (VM) ──▶ 127.0.0.1:port
```

Config: `/etc/cloudflared/config.yml` on the VM, template at
`deploy/cloudflared/config.yml.template`. Tunnel `f1750626-199d-44fd-8dc2-c2d91beeb65f`.

| Hostname | → | Serves |
|---|---|---|
| `ayur.namahos.com` | `127.0.0.1:3000` | the web app |
| `ayur-api.namahos.com` | `127.0.0.1:4000` | Python AI backend |
| `ayur-convex.namahos.com` | `127.0.0.1:3210` | Convex client API (websockets) |
| `ayur-convex-http.namahos.com` | `127.0.0.1:3211` | Convex HTTP actions |
| *(anything else)* | `http_status:404` | refused |

The catch-all must stay last. All four are proxied CNAMEs to
`<tunnel-id>.cfargotunnel.com`.

`ayur-convex-http` carries more than Convex traffic. It is the **JWT issuer**
(`auth.config.ts` reads it as `CONVEX_SITE_URL`), it serves
`/.well-known/jwks.json` which the Python backend fetches to verify every login,
and it receives the Polar webhook and the two backend callbacks
(`/backend/webhook`, `/backend/user-memory`). Changing that hostname breaks
authentication everywhere at once.

> **Shared zone.** `namahos.com` also carries the company site, a Vercel
> deployment, and production email (MX/SPF/DKIM/DMARC). Zone-wide Cloudflare
> toggles can break those. This is why the HTTP→HTTPS redirect lives in
> `apps/app/src/middleware.ts` rather than in a zone rule.

---

## 4. Code and deployment

Two private GitHub repositories. The VM pulls from GitHub; the operator
workstation never pushes code to the VM.

```
workstation ──git push──▶ GitHub ──git pull──▶ VM ──serve──▶ users
```

| Repo | On the VM | Holds |
|---|---|---|
| `akshat948/Ayurveda-Backend-` | `/opt/ayurveda/Ayurveda-` | Python backend, tunnel config, `deploy/`, this file |
| `akshat948/ayurveda-frontend` | `/opt/ayurveda/ayurveda-frontend` | Next.js app, Convex schema + functions |

### Deploy keys

Both repos are private, so an unattended host cannot clone over HTTPS — there is
nobody to answer a username prompt. Each repo has its own **read-only deploy
key**, because a GitHub deploy key is scoped to exactly one repository:

```
/root/.ssh/deploy_backend    →  Ayurveda-Backend-     Settings → Deploy keys
/root/.ssh/deploy_frontend   →  ayurveda-frontend     Settings → Deploy keys
/root/.ssh/config            →  Host aliases github-backend / github-frontend
```

`IdentitiesOnly yes` is required in that config. Without it ssh offers every key
it holds and GitHub authenticates as whichever it recognises first — which will
be the wrong repository. Write access is deliberately unchecked: a production
host has no business pushing code.

### Deploying a change

There is **no CI and no automatic deploy**. `git push` does not reach the VM.

```sh
ssh root@10.1.30.37
cd /opt/ayurveda/ayurveda-frontend && git pull
cd apps/app && bun run build            # only if the frontend changed
systemctl restart ayurveda-frontend
```

Or re-run the installer, which is idempotent and pulls both repos, refreshes
dependencies and reinstalls units — it never touches secrets and never imports
data:

```sh
bash /opt/ayurveda/Ayurveda-/deploy/install.sh
```

Deployment tracks the `main` branch. There are no tags and no release numbers,
so "what is running" is answered by a commit hash:

```sh
git -C /opt/ayurveda/ayurveda-frontend log --oneline -1
```

Rollback is `git checkout <commit>` + rebuild + restart. There is no faster path.

### Rebuilding from nothing

The point of `deploy/`. A fresh Ubuntu 24.04 host, four steps:

```sh
git clone git@github-backend:akshat948/Ayurveda-Backend-.git /opt/ayurveda/Ayurveda-
sudo bash /opt/ayurveda/Ayurveda-/deploy/install.sh   # stops: secrets missing
# place /etc/ayurveda/*.env from the password manager
sudo bash /opt/ayurveda/Ayurveda-/deploy/install.sh   # completes
```

Then the six manual steps it prints: admin key → auth keys → deployment
variables → `convex deploy` → `convex import <backup>` → build and start.
Those are manual on purpose; each can destroy data if run at the wrong moment.

---

## 5. Environment variables

Four files, all `/etc/ayurveda/*.env`, mode 600, root owned, **never in git**.
Contracts (names and meaning, no values) live in `deploy/env/*.env.example`.

Two of them are symlinked into the repos, because the build and the Python
process read env from their working directory rather than from systemd — so
there is exactly one copy of every secret:

```
/opt/ayurveda/Ayurveda-/backend-python/.env                  → /etc/ayurveda/backend.env
/opt/ayurveda/ayurveda-frontend/apps/app/.env.local          → /etc/ayurveda/frontend.env
/opt/ayurveda/ayurveda-frontend/packages/backend/.env.local  → /etc/ayurveda/convex-cli.env
```

### `convex.env` — the container, not the deployment

Read by `docker compose`. Distinct from the Convex *deployment* variables below,
which is a distinction that has caused real confusion.

`CONVEX_CLOUD_ORIGIN` · `CONVEX_SITE_ORIGIN` · `INSTANCE_NAME` · `INSTANCE_SECRET` ·
`POSTGRES_URL` (empty = bundled SQLite) · `DO_NOT_REQUIRE_SSL` ·
`DOCUMENT_RETENTION_DELAY` · `DISABLE_BEACON` · `DISABLE_METRICS_ENDPOINT` ·
`REDACT_LOGS_TO_CLIENT` · `ACTIONS_USER_TIMEOUT_SECS`

`CONVEX_SITE_ORIGIN` becomes `CONVEX_SITE_URL` inside Convex. A trailing slash
or an `http://` value there produces a sign-in that appears to work and then
401s on every request. `INSTANCE_SECRET` signs admin keys; rotating it
invalidates every admin key already issued.

### `backend.env` — Python backend

`LLM_PROVIDER` · `GROQ_API_KEY` · `OPENROUTER_API_KEY` · `CONVEX_SITE_URL` ·
`CONVEX_AUDIENCE` · `SERVICE_KEY` · `WEBHOOK_SECRET` — plus the model and
retrieval tuning that `backend-python/config.py` reads.

`SERVICE_KEY` and `WEBHOOK_SECRET` must equal `BACKEND_SERVICE_KEY` and
`BACKEND_WEBHOOK_SECRET` on the Convex deployment. A mismatch surfaces as 401s
from the backend, not as a configuration error.

`config.py` defaults `CONVEX_SITE_URL` to `http://localhost:3211`. If it is
missing from this file, JWKS silently resolves to loopback and **every login
fails** with "your session expired" — a message no amount of refreshing fixes.

### `frontend.env` — Next.js, **compiled in at build time**

`NEXT_PUBLIC_CONVEX_URL` (required — the build fails without it) ·
`NEXT_PUBLIC_SITE_URL` · `NEXT_PUBLIC_AI_BACKEND_URL` ·
`NEXT_PUBLIC_CONSULT_PROVIDER` (`local` or `mock`) · `NEXT_PUBLIC_BOT_ID` ·
`NEXT_PUBLIC_GOOGLE_AUTH_ENABLED` · `NEXT_PUBLIC_SENTRY_DSN` ·
`NEXT_PUBLIC_OPENPANEL_CLIENT_ID`

Every `NEXT_PUBLIC_*` value is baked into the JavaScript bundle. Editing this
file and restarting the service keeps serving the old value. **Always
`bun run build` first.**

### `convex-cli.env` — CLI credentials

`CONVEX_SELF_HOSTED_URL` · `CONVEX_SELF_HOSTED_ADMIN_KEY`

The admin key is unrestricted access to all data. Treat it as a root password.
Generate with `docker compose exec backend ./generate_admin_key.sh` from
`deploy/compose`.

### Convex *deployment* variables — not in any file

These live on the deployment itself, set with `npx convex env set`, and are
backed up by nothing. `packages/backend/.env.example` documents them.

`SITE_URL` · `BACKEND_BASE_URL` · `BACKEND_SERVICE_KEY` · `BACKEND_WEBHOOK_SECRET` ·
`SMTP_HOST` · `SMTP_PORT` · `SMTP_SECURE` · `SMTP_USER` · `SMTP_PASS` ·
`AUTH_EMAIL_FROM` · `AUTH_GOOGLE_ID` · `AUTH_GOOGLE_SECRET` ·
`JWT_PRIVATE_KEY` · `JWKS`

Two traps:

- `JWT_PRIVATE_KEY` is a PKCS#8 PEM with newlines replaced by **spaces**, and it
  must be set with `--` before the value or the leading dash parses as a flag:
  `npx convex env set JWT_PRIVATE_KEY -- "$(cat /tmp/jwt_private_key)"`.
  Generate both with `scripts/generateKeys.mjs`. Regenerating signs every user out.
- `convex/env.ts` marks `POLAR_ORGANIZATION_TOKEN` and `POLAR_WEBHOOK_SECRET`
  **required** whenever `VALIDATE_ENV` is set. Either set both, or leave
  `VALIDATE_ENV` unset. It is currently unset.

---

## 6. Data

| | |
|---|---|
| Engine | SQLite, inside the Convex container |
| Location | docker volume `compose_data` → `/convex/data/db.sqlite3` |
| Size | ~28 MB |
| Contents | ~2160 documents: accounts, password hashes, consultations, workspaces |

**Never run `docker compose down -v`.** The volume *is* the database.
`convex.service` uses `stop` for exactly that reason.

> **CHANGED — 2026-08-29.** `backend-python/data/knowledge` and
> `data/vector_store` are gone. There is no local knowledge base and nothing
> to build on provisioning any more — every consultation answer comes from
> GraphRAG's `/v1/answer`. `install.sh` stage 6b (build the index) is dead
> and should be removed the next time that script is touched.

### Backups

`convex-backup.timer` → `deploy/backup.sh`, nightly 03:15 (+ jitter),
`/var/backups/convex/`, 30 days retained, `Persistent=true` so a missed run
catches up rather than being skipped.

```sh
# restore
cd /opt/ayurveda/ayurveda-frontend/packages/backend
node ../../node_modules/convex/bin/main.js import --replace <archive.zip>
```

`--include-file-storage` is not the default and `backup.sh` passes it. Without
it you get the tables and none of the uploaded files — which you discover during
a restore rather than during a backup.

> **The archives share a disk with the database they protect.** The off-box copy
> in `deploy/backup.sh` is still commented out. Until it points at real storage,
> this does not cover the failure a backup exists for. See
> [Known gaps](#known-gaps).

---

## 7. What is outside this machine

Moving the database here did not move these. Each is a live dependency.

| Service | What leaves the VM | Consequence if it fails |
|---|---|---|
| **Cloudflare** | all inbound traffic and DNS | site unreachable |
| **Gmail SMTP** | auth emails — sign-in codes, password reset | nobody can sign up or reset |
| **Google OAuth** | sign-in, when enabled (currently `false`) | Google sign-in only |
| **GraphRAG** | every consultation's text, and it writes the answer — the ONLY source, at `10.1.30.38` | no answers at all; there is no local model, no local knowledge base and no fallback left in this backend any more |
| **Polar** | billing, if configured | billing only |

This matters for a health product: the symptoms a user types are processed on
the model provider's hardware. Self-hosting the database did not change that.

> **GraphRAG needs a hosts entry.** It resolves via `graphrag.internal` and its
> only documentation is `docs/graphrag-api.md`, which is **git-ignored** because
> it contains a key. A fresh host loses that record. It is disabled today, so
> nothing breaks — but enabling it needs that file from the operator.

---

## 8. Known gaps

Stated plainly so nobody is surprised by them later.

1. **Backups are on the same disk as the database.** One disk failure loses
   both. `deploy/backup.sh` has the `rclone copy` line commented out awaiting a
   destination. This is the most important open item.
2. **Single machine.** Power, disk or network loss takes everything down.
   Real availability needs a second host.
3. **No CI.** The five bugs found during the migration — missing `unzip`, a
   stale lockfile, a missing exec bit, a missing Tesseract binary, an unbuilt
   knowledge index — would all have been caught by a build on push.
4. **The Convex image is `:latest`.** A `docker compose pull` would take
   whatever is newest, untested. Currently image `1f2044e3eac4`. It should be
   pinned.
5. **Two identical compose files.** `self-hosted/docker-compose.yml` is
   byte-identical to `deploy/compose/docker-compose.yml` and has its own live
   `.env`. `convex.service` uses `deploy/compose`; the older documents point at
   `self-hosted/`. Only one should exist.
6. **`packages/backend/.env.example` references `infra/convex-self-hosted/`**,
   a path that exists in neither repo. The real script is `scripts/generateKeys.mjs`.
7. **`NEXT_PUBLIC_BACKEND_URL` is dead** — it appears in the env examples and in
   the live `frontend.env`, but no source file reads it.
8. **Secrets exist in one place.** `/etc/ayurveda/*.env`, the tunnel
   credentials and the Convex deployment variables are not in git and not
   backed up by the nightly job. They belong in a password manager.
9. **No off-machine record of the Convex deployment variables.** `npx convex env
   list` is the only enumeration, and it needs a running deployment.

---

## 9. Verifying a deployment

After any change that touches auth, Convex or the tunnel:

- [ ] Sign in as an existing account with its old password
- [ ] Open an **old** consultation and send a message in it — the assistant must
      continue rather than greet you again. This is the check people skip: each
      assistant message carries a `state` blob holding the conversation context,
      and if it did not survive, chats look fine and then restart from scratch
- [ ] Upload a report on `/files`, reload, confirm it is still listed
- [ ] `/library` renders (it never touches Convex)
- [ ] Browser console clean — no websocket reconnect loop

---

## Keeping this true

A document like this rots quietly. `deploy/infra-check.sh` exists so it does not
have to be trusted:

```sh
bash /opt/ayurveda/Ayurveda-/deploy/infra-check.sh
```

It checks the units, ports, tunnel hostnames, backup timer and freshness, the
env files and their variable names, disk and memory headroom, and the pinned
facts in section 1 — then reports anything that disagrees with this file. Run it
after any infrastructure change and before believing anything written here.

**Update this file in the same commit as the change**, not afterwards:

| Change | Update |
|---|---|
| New or removed service | §2 Services, and `deploy/systemd/` |
| Port change | §2 and §3, and `cloudflare/config.yml` |
| New hostname | §3, and the tunnel config |
| New environment variable | §5, and `deploy/env/*.env.example` |
| Deployment process change | §4 |
| A gap closed | §8 — delete the entry |

Then bump the "Last verified" date at the top after running `infra-check.sh`.
