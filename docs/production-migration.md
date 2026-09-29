# Production migration runbook (historical record)

> **Status: executed 2026-09-24.** `ayur.namahos.com` serves this application. Phases A and B below
> were run then, from two repositories and two checkouts. Phase C (retiring the legacy stack) was
> done by the owner by hand on 2026-09-29: the legacy services, Convex and its volume are gone,
> after a `pg_dump`. The archive (32 Convex exports, `/etc/ayurveda`, the vector-store backups)
> is kept off the host, and the legacy rollback below is therefore no longer possible (see
> CLAUDE.md "Status"). Deployment has since moved to one repository and release-based deploys:
> see [deployment.md](deployment.md).

## What production runs today (legacy — historical record)

> Historical: this section describes retired code that is no longer in this repository (removed in PR #1). It is kept only so the cutover and rollback below make sense. It contains no credentials.

The previous product in this repository was an Ayurveda health-consultation chatbot. Its last
version is preserved at the git tag **`ayurveda-baseline`** and on `main` of the original remote.
On the single Ubuntu VM it runs:

| Legacy unit | Role | Replaced by |
|---|---|---|
| `convex.service` (self-hosted Convex in Docker, ports 3210/3211) | auth, users, chats, patient profiles | `aichat-postgres.service` (PostgreSQL 16 + pgvector) |
| `ayurveda-backend.service` (FastAPI `server.py`, port 4000) | consultation engine, local ChromaDB, GraphRAG client | `aichat-api.service` (this API, port **4100**) |
| `ayurveda-frontend.service` (Next.js, port 3000) | web app on Convex | `aichat-web.service` (port 3000) |
| `convex-backup.timer` (Convex export) | backups | `aichat-pg-backup.timer` (`pg_dump`) |
| cloudflared: app, API, Convex and Convex-HTTP hostnames | public ingress | cloudflared: **app hostname only** |

The new API uses port 4100, so the whole new stack can be installed and checked while the legacy
stack keeps serving users. Only port 3000 (the web app) is shared, and taking it over is the switch.

## Preconditions

| # | What | Status |
|---|---|---|
| 1 | Frontend migrated to this API | done: frontend PR #1, `288481f` |
| 2 | **Email**: SMTP credentials, or an Ollastack Agent Mail token + mailbox id (`EMAIL_BACKEND=ollastack`) | **required**: sign-up and login send email codes, so without email nobody can sign in |
| 3 | Primary LLM key (`LLM_PRIMARY_API_KEY`) | required |
| 4 | Fallback LLM key | optional; the OpenRouter key on record was rejected ("User not found"), so leave `LLM_FALLBACK_MODEL` empty until a valid key exists |
| 5 | OpenAI embedding key (`EMBEDDING_API_KEY`) | optional: without it chat works and retrieval is skipped |
| 6 | Read access for the host to both GitHub repositories | required if they are private: a read-only deploy key per repository, or a read-only fine-grained token. Never put a token inside a clone URL, where it would be saved in `.git/config` |
| 7 | Owner decision on existing accounts (below) | default: fresh start |
| 8 | A fresh Convex export stored **off the host** | required (rollback copy) |

## Existing data — decision required

- **Ayurveda consultations, patient profiles and uploaded reports are NOT migrated.** They are
  health data of a product that no longer exists here; they stay only in the retained Convex volume
  and its backups until the owner decides on retention or deletion.
- **Accounts:** default is a fresh start (users sign up again). Optional, only if approved: import
  users (email, verification time, display name) from a Convex export. Their passwords can be kept:
  Convex Auth stored Lucia Scrypt hashes (`salt:key` hex; N=16384, r=16, p=1, dkLen=64; NFKC), which
  Python's `hashlib.scrypt` can verify — this would need a small legacy-hash verifier that rehashes
  to argon2id on first login, plus an import script. Neither exists yet by design.

## Cutover

All commands run on the VM as a sudo-capable user.

### Phase A — install beside the legacy stack (users unaffected)

```sh
# A1. Look before touching anything
systemctl list-units 'ayurveda-*' 'convex*' 'aichat-*' 'cloudflared*' --no-pager
sudo ss -ltnp | grep -E ':(3000|4000|4100|5432)\b'   # 4100 and 5432 must be free (install.sh checks too)
free -h; df -h /                                      # the web build needs about 2 GB of free RAM

# A2. Rollback copy of the legacy data: run the legacy backup once and copy the result OFF the host
sudo systemctl start convex-backup.service
systemctl cat convex-backup.service                   # shows where the export was written

# A3. Code (needs precondition 6)
sudo git clone https://github.com/sunny436/AI-Tutor-Webapp-backend.git /opt/aichat/backend

# A4. Secrets: generated on the host and never printed. Refuses to overwrite existing files.
sudo bash -c '
set -euo pipefail; umask 077; mkdir -p /etc/aichat; chmod 700 /etc/aichat
for f in postgres.env api.env web.env; do [ ! -e /etc/aichat/$f ] || { echo "exists: /etc/aichat/$f"; exit 1; }; done
T=/opt/aichat/backend/deploy/env
PW=$(openssl rand -hex 24)
SK=$(openssl rand -base64 48 | tr -d "\n/+=")
sed "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$PW|" $T/postgres.env.example > /etc/aichat/postgres.env
sed -e "s|^SECRET_KEY=.*|SECRET_KEY=$SK|" -e "s|<password>|$PW|" $T/api.env.example > /etc/aichat/api.env
cp $T/web.env.example /etc/aichat/web.env
echo "written: /etc/aichat/{postgres,api,web}.env"'

sudo nano /etc/aichat/api.env   # fill email (SMTP_* + EMAIL_FROM, or EMAIL_BACKEND=ollastack + OLLASTACK_*), LLM_PRIMARY_API_KEY, EMBEDDING_API_KEY if available
sudo nano /etc/aichat/web.env   # NEXT_PUBLIC_SITE_URL=https://<app hostname>

# A5. Install: Postgres, API on 127.0.0.1:4100, backups; builds the web app but does NOT start it
sudo BACKEND_REPO=https://github.com/sunny436/AI-Tutor-Webapp-backend.git \
     FRONTEND_REPO=https://github.com/sunny436/AI-Tutor-Webapp-frontend.git \
     bash /opt/aichat/backend/deploy/install.sh

# A6. Check the new stack while the legacy site keeps serving
bash /opt/aichat/backend/deploy/infra-check.sh      # "no backup in the last 2 days" is expected on day one
journalctl -u aichat-api -n 30 --no-pager           # JSON logs; look for errors
# Optional: try the built web app on a spare port, then stop it with Ctrl+C
sudo bash -c 'cd /opt/aichat/frontend/apps/app && set -a && . /etc/aichat/web.env && set +a && /root/.bun/bin/bun x next start -p 3100 -H 127.0.0.1'
#   (second terminal) curl -sI http://127.0.0.1:3100/login | head -1   → HTTP/1.1 200
```

Stop here if anything fails. Nothing public has changed yet.

### Phase B — the switch (seconds of downtime)

```sh
# Prepare the tunnel config first (template: deploy/cloudflared/config.yml.template):
# the app hostname must point at http://127.0.0.1:3000 exactly. The new app listens on 127.0.0.1
# only, so `localhost` (may resolve to ::1) or the VM's IP would not reach it.
sudo cp /etc/cloudflared/config.yml /etc/cloudflared/config.yml.legacy
sudo cp /etc/cloudflared/config.yml /etc/cloudflared/config.yml.new
sudo nano /etc/cloudflared/config.yml.new            # app hostname → http://127.0.0.1:3000; remove the API and Convex hostnames

# Switch
sudo systemctl stop ayurveda-frontend.service
sudo systemctl enable --now aichat-web.service
curl -sI http://127.0.0.1:3000/login | head -1       # → HTTP/1.1 200
sudo cp /etc/cloudflared/config.yml.new /etc/cloudflared/config.yml && sudo systemctl restart cloudflared
```

Then, in a browser on the public URL, sign up with a real address, confirm the email code arrives,
chat, stop a reply, regenerate, and sign out and back in. Run `infra-check.sh` again.

### Phase C — retire the legacy stack (after the new site has run cleanly, e.g. a day)

```sh
sudo systemctl disable --now ayurveda-backend.service convex-backup.timer convex.service
sudo systemctl disable ayurveda-frontend.service
# KEEP the Convex docker volume and its backups: rollback + the pending data decision.
```

Finally, update `INFRASTRUCTURE.md` to say production runs the new stack.

### Optional — knowledge base (needs `EMBEDDING_API_KEY`)

```sh
# systemd-run loads api.env exactly as the API service does
sudo systemd-run --pipe --wait --collect -p EnvironmentFile=/etc/aichat/api.env \
  -p WorkingDirectory=/opt/aichat/backend/backend \
  /opt/aichat/backend/backend/.venv/bin/python scripts/ingest_documents.py --source handbook --global /path/to/docs
```

Only ingest content suitable for every signed-in user when using `--global` (see [rag.md](rag.md)).

### Updates later

**Superseded.** Updates used to mean bundling each repository and re-running `install.sh`. Now there
is one repository and one command: `bun run deploy` ([deployment.md](deployment.md)). The bundles in
`/root/aichat-bundles/` and the checkouts `/opt/aichat/{backend,frontend}` are only needed until the
first release deploy, and can then be removed.

## Rollback

- **During Phase B:** `sudo systemctl disable --now aichat-web.service && sudo systemctl start ayurveda-frontend.service`,
  then `sudo cp /etc/cloudflared/config.yml.legacy /etc/cloudflared/config.yml && sudo systemctl restart cloudflared`.
  The legacy API and Convex are still running, so the old site is back at once.
- **After Phase C:** also `sudo systemctl enable --now convex.service ayurveda-backend.service convex-backup.timer`
  (`git checkout ayurveda-baseline` in the legacy checkout if its code was changed).
- The cutover modifies no legacy data. The new stack can stay installed during a rollback; it uses
  ports 4100 and 5432, not the legacy ones.
