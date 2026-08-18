# Moving Convex from Cloud to this host

Every account, consultation, uploaded report and workspace currently lives in a
Convex **Cloud** deployment. This moves that data onto the machine that already
serves the product, using the self-hosting setup that is already in the
`Ayurveda-` repo — nothing new is introduced.

## Where things stand

Measured on this host, not assumed:

| | |
|---|---|
| Data today | Convex Cloud, deployment `kindred-sockeye-79…` (live) |
| `cloudflared` | running |
| Port 3000 (Next.js) / 4000 (FastAPI) | listening |
| Ports 3210 / 3211 / 6791 (Convex) | **closed — self-hosted Convex is not running** |
| Docker | **not installed** |
| Convex CLI login (`~/.convex`) | **absent** |

`ROADMAP.md` lists "Self-hosted Convex (Docker) ✅ done". The compose file does
exist, but on this host it has never run: there is no Docker, no `.env` beside
it, and nothing points at it. The product has always used Cloud.

## Two things only you can do

Everything else in this document is scripted or mechanical.

**1. Install Docker Desktop** — <https://www.docker.com/products/docker-desktop/>
Keep "Use WSL 2 based engine" ticked; the installer adds WSL2 and may reboot.
Docker Desktop must stay running, or Convex stops with it.
Verify: `docker version` returns a server version.

**2. Log the Convex CLI in** — one time, opens a browser:

```sh
cd C:\Users\test\Desktop\ayurveda-frontend\packages\backend
npx convex login
```

Without this the export in step 5 cannot run.

## What is used, and from where

Two repos are involved. Nothing here creates a parallel setup.

| Path | Role |
|---|---|
| `Ayurveda-/self-hosted/docker-compose.yml` | the Convex backend + dashboard |
| `Ayurveda-/self-hosted/.env` | container config (written already) |
| `Ayurveda-/cloudflare/config.yml` | the existing named tunnel |
| `Ayurveda-/scripts/generateKeys.mjs` | Convex Auth RS256 keypair |
| `Ayurveda-/backend-python/.env` | `CONVEX_SITE_URL` for JWKS |
| `ayurveda-frontend/packages/backend/` | Convex schema + functions; all `npx convex` commands run here |
| `ayurveda-frontend/apps/app/.env.local` | `NEXT_PUBLIC_CONVEX_URL` |

Ports follow the template's `project.config.ts`: Convex `3210`, Convex site
`3211`, dashboard `6791`, app `3000`, backend `4000`.

---

## Steps

### 1. Add the two Convex hostnames to the tunnel

Insert into `Ayurveda-/cloudflare/config.yml`, **before** the
`- service: http_status:404` catch-all:

```yaml
  - hostname: ayur-convex.namahos.com
    service: http://127.0.0.1:3210
    originRequest:
      connectTimeout: 30s

  - hostname: ayur-convex-http.namahos.com
    service: http://127.0.0.1:3211
```

Validate before restarting anything — this file serves the live site:

```sh
C:\Users\test\.cloudflared\bin\cloudflared.exe --config <file> tunnel ingress validate
```

(The `--config` flag is global and must come *before* `tunnel`.)

### 2. DNS records

Both hostnames need records pointing at the tunnel. The token permissions and
`cloudflare/zones.mjs` for this are already set up in `cloudflare/`.

### 3. Start Convex

`self-hosted/.env` is already written, including a freshly generated
`INSTANCE_SECRET` — ROADMAP flagged the compose default as a must-fix "before
any real use".

```sh
cd C:\Users\test\Desktop\Ayurveda-\self-hosted
docker compose up -d
docker compose logs -f backend      # wait for the healthcheck
curl https://ayur-convex.namahos.com/version
```

That last command must answer over real HTTPS before continuing.

### 4. Admin key, and point the CLI at it

```sh
docker compose exec backend ./generate_admin_key.sh
```

Put it in `ayurveda-frontend/packages/backend/.env.local` (git-ignored):

```sh
CONVEX_SELF_HOSTED_URL='https://ayur-convex.namahos.com'
CONVEX_SELF_HOSTED_ADMIN_KEY='<the key>'
```

This key is unrestricted access to all data. Treat it as a root password.

### 5. Export from Cloud — do this before anything destructive

Run in a shell that does **not** have the self-hosted variables set:

```sh
cd C:\Users\test\Desktop\ayurveda-frontend\packages\backend
npx convex export --path ./cloud-backup.zip --include-file-storage
```

`--include-file-storage` is not the default. Without it you get the tables and
none of the uploaded PDFs or avatars — which you discover during a restore, not
during a backup.

Keep this file. Once the Cloud deployment is deleted it cannot be produced again.

### 6. Auth keys

Convex Auth's own setup CLI does not support self-hosted deployments, so the
keypair is generated directly. The repo already has the script:

```sh
node C:\Users\test\Desktop\Ayurveda-\scripts\generateKeys.mjs
```

It writes `/tmp/jwt_private_key` and `/tmp/jwks`. Set both on the deployment:

```sh
npx convex env set JWT_PRIVATE_KEY -- '<contents of /tmp/jwt_private_key>'
npx convex env set JWKS -- '<contents of /tmp/jwks>'
```

The `--` matters: without it the leading dash of the PEM parses as a flag. The
private key is a PKCS#8 PEM with newlines replaced by **spaces** — that is the
format `@convex-dev/auth` expects, and a normal multi-line PEM will not import.

Generate these once. Regenerating signs every user out.

### 7. Remaining deployment variables

`packages/backend/.env.example` documents each. From `packages/backend`:

```sh
npx convex env set SITE_URL "https://ayur.namahos.com"
npx convex env set BACKEND_BASE_URL "https://ayur-api.namahos.com"
npx convex env set BACKEND_SERVICE_KEY "…"      # must equal backend-python SERVICE_KEY
npx convex env set BACKEND_WEBHOOK_SECRET "…"   # must equal backend-python WEBHOOK_SECRET
npx convex env set SMTP_HOST "…"                # and SMTP_PORT, SMTP_SECURE, SMTP_USER, SMTP_PASS
npx convex env set AUTH_EMAIL_FROM "…"
```

A `BACKEND_*` mismatch surfaces as 401s from the backend, not as a config error.

Do **not** set `CONVEX_SITE_URL` by hand — the backend derives it from
`CONVEX_SITE_ORIGIN`.

One trap: `convex/env.ts` marks `POLAR_ORGANIZATION_TOKEN` and
`POLAR_WEBHOOK_SECRET` **required** whenever `VALIDATE_ENV` is set. Either set
both, or leave `VALIDATE_ENV` unset on this deployment.

### 8. Deploy functions, then import the data

Order matters — the schema has to exist before the rows land.

```sh
npx convex deploy
npx convex import --replace ./cloud-backup.zip
```

If the import is rejected on schema validation, do not edit the snapshot: import
into an empty deployment first so you can see which table disagrees.

### 9. Repoint the three consumers

**Frontend** — `ayurveda-frontend/apps/app/.env.local`:

```sh
NEXT_PUBLIC_CONVEX_URL=https://ayur-convex.namahos.com
```

Then **rebuild**. `start-all.ps1` says it plainly: *"After changing any
`NEXT_PUBLIC_*` value, run `bun run build` before restarting — those values are
compiled into the bundle, not read at runtime."*

**Python backend** — `Ayurveda-/backend-python/.env`, one line:

```sh
CONVEX_SITE_URL=https://ayur-convex-http.namahos.com
```

`server.py:207` builds `${CONVEX_SITE_URL}/.well-known/jwks.json` from this to
verify every login token. `CONVEX_AUDIENCE=convex` is unchanged.

**Polar** — webhook URL to `https://ayur-convex-http.namahos.com/polar/events`.

**Google OAuth**, only when you enable it — redirect URI to
`https://ayur-convex-http.namahos.com/api/auth/callback/google`.
`packages/backend/.env.example` used to claim this URI never changes when the app
moves; that is true of the *app* moving, not of *Convex* moving. The note there
has been corrected.

---

## Verify before deleting anything

- [ ] Sign up fresh, receive the email code, finish onboarding
- [ ] Sign in as a **migrated** account with its old password
- [ ] Open an **old** consultation — the transcript is there *and continues*
      rather than greeting you again
- [ ] Send a message and get an answer
- [ ] Upload a report on `/files`, reload, still listed
- [ ] Rename and delete a consultation
- [ ] `/library` renders (it never touched Convex)
- [ ] No websocket reconnect loop in the console

The old-consultation check is the one people skip. Each assistant message carries
a `state` JSON blob holding the consultation `context`; if that did not survive,
chats look fine and then restart from scratch on the next message.

## Expect this

**Everyone is signed out once.** `JWT_PRIVATE_KEY` is new, so existing session
tokens stop validating. Passwords still work — the hashes migrate with the data.

**Backups are now yours.** Cloud snapshotted automatically; nothing does now. Put
`npx convex export --include-file-storage` on a schedule, and test a restore into
a throwaway deployment. An untested backup is a guess.

**The docker volume `data` is the database.** Never `docker compose down -v`.

## Rollback

Until step 9 is applied, nothing is committed: the Cloud deployment is untouched
and still serving. To go back, restore the previous `NEXT_PUBLIC_CONVEX_URL` and
`CONVEX_SITE_URL`, and rebuild.

Delete the Cloud deployment only after the checklist above passes and
`convex export` has produced at least one good archive from the **new**
deployment.
