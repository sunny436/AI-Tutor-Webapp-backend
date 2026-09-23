# Production migration runbook — NOT EXECUTED

> **Status: prepared, not run. Nothing here may be executed on the production host without the
> owner's explicit approval.** Production still runs the legacy stack described below.

## What production runs today (legacy)

The previous product in this repository was an Ayurveda health-consultation chatbot. Its last
version is preserved at the git tag **`ayurveda-baseline`** (and on `main` of the original remote
until this branch is merged). On the single Ubuntu VM it runs:

| Legacy unit | Role | Replaced by |
|---|---|---|
| `convex.service` (self-hosted Convex in Docker, ports 3210/3211) | auth, users, chats, patient profiles | `aichat-postgres.service` (PostgreSQL 16 + pgvector) |
| `ayurveda-backend.service` (FastAPI `server.py`, port 4000) | consultation engine, local ChromaDB, GraphRAG client | `aichat-api.service` (this API) |
| `ayurveda-frontend.service` (Next.js, port 3000) | web app on Convex | `aichat-web.service` (after the frontend migration) |
| `convex-backup.timer` (Convex export) | backups | `aichat-pg-backup.timer` (`pg_dump`) |
| cloudflared: app, API, Convex and Convex-HTTP hostnames | public ingress | cloudflared: **app hostname only** |

## Preconditions (all required)

1. The **frontend repository** has been migrated to this API (see
   [frontend-integration.md](frontend-integration.md)); the current web app speaks the legacy API
   and Convex and will not work against this backend.
2. Owner decision on existing accounts (below).
3. SMTP credentials for production email (today they live in the Convex deployment's environment).
4. A valid fallback LLM key (the OpenRouter key on record was rejected with 401 "User not found").
5. A fresh Convex export stored off the host, as the rollback copy.

## Existing data — decision required

- **Ayurveda consultations, patient profiles and uploaded reports are NOT migrated.** They are
  health data of a product that no longer exists here; they stay only in the retained Convex volume
  and its backups until the owner decides on retention or deletion.
- **Accounts:** default is a fresh start (users sign up again). Optional, only if approved: import
  users (email, verification time, display name) from a Convex export. Their passwords can be kept:
  Convex Auth stored Lucia Scrypt hashes (`salt:key` hex; N=16384, r=16, p=1, dkLen=64; NFKC), which
  Python's `hashlib.scrypt` can verify — this would need a small legacy-hash verifier that rehashes
  to argon2id on first login, plus an import script. Neither exists yet by design.

## Cutover steps (for when approved)

1. `sudo bash /opt/aichat/backend/deploy/install.sh` with `BACKEND_REPO` set, after writing
   `/etc/aichat/postgres.env` and `/etc/aichat/api.env` from `deploy/env/*.example`.
   This starts PostgreSQL and the API on loopback; the legacy stack keeps serving users.
2. `bash deploy/infra-check.sh`; run `scripts/smoke_chat.py` against the API **on the host** with a
   throwaway account and a test SMTP target (not real users' mailboxes).
3. Deploy the migrated frontend with `/etc/aichat/web.env`; stop `ayurveda-frontend.service`,
   start `aichat-web.service` (port 3000 is shared, so this is the switch-over moment).
4. Update cloudflared from `deploy/cloudflared/config.yml.template` (app hostname only) and reload.
   Remove the legacy API and Convex hostnames.
5. Stop and disable `ayurveda-backend.service`, `convex.service`, `convex-backup.timer`.
   **Keep the Convex docker volume and backups** (rollback + pending data decision).
6. Update `INFRASTRUCTURE.md` to describe the new production state.

## Rollback

Until step 5, rollback is: stop `aichat-web.service`, start `ayurveda-frontend.service`, restore the
previous cloudflared config. After step 5, also start `convex.service` and `ayurveda-backend.service`
(`git checkout ayurveda-baseline` in the legacy checkout). No legacy data is modified by the cutover.
