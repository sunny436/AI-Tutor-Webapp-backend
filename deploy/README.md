# Deploying Ayurveda

Ubuntu 24.04. Everything runs under systemd; nothing needs a logged-in user,
a desktop session, or a GUI application.

## Rebuild from nothing

This is the path that matters. A fresh host, four steps:

```sh
git clone https://github.com/akshat948/Ayurveda-Backend-.git /opt/ayurveda/Ayurveda-
sudo bash /opt/ayurveda/Ayurveda-/deploy/install.sh     # stops: secrets missing
# drop /etc/ayurveda/*.env in from the password manager
sudo bash /opt/ayurveda/Ayurveda-/deploy/install.sh     # completes
```

Then follow the numbered steps it prints: admin key, auth keys, deployment
variables, `convex deploy`, `convex import <backup>`, `bun run build`, start.

`install.sh` is idempotent — re-run it after any change. It never writes
secrets and never imports data, because both are things you want to do
deliberately rather than as a side effect of provisioning.

## What runs

| Unit | Port | Notes |
|---|---|---|
| `convex.service` | 3210 / 3211 | database, via docker compose |
| `ayurveda-backend.service` | 4000 | FastAPI, `MemoryMax=2600M` |
| `ayurveda-frontend.service` | 3000 | `bun run start`, production build |
| `cloudflared.service` | — | outbound tunnel |
| `convex-backup.timer` | — | nightly 03:15, `Persistent=true` |

```sh
systemctl status convex ayurveda-backend ayurveda-frontend cloudflared
journalctl -u ayurveda-backend -f
```

## Three things that bite

**`NEXT_PUBLIC_*` is compiled in, not read at runtime.** Editing
`/etc/ayurveda/frontend.env` and restarting keeps serving the old value. Always:

```sh
cd /opt/ayurveda/ayurveda-frontend/apps/app && bun run build
systemctl restart ayurveda-frontend
```

**Never `docker compose down -v`.** The volume is the database. `convex.service`
uses `stop` for exactly this reason.

**`CONVEX_SITE_ORIGIN` is load-bearing twice.** It is the JWT issuer for
`auth.config.ts`, and the Python backend builds
`<site>/.well-known/jwks.json` from it to verify every login. Wrong value =
sign-in appears to work, then every request 401s.

## Memory

3.8 GB plus 4 GB swap. The Python backend peaks near 2 GB loading bge-m3 and
`next build` wants 1-2 GB, so **do not build while the backend is running** —
stop it, build, start it. `MemoryMax` on each unit means a spike kills the
process that caused it rather than letting the kernel pick a victim, which
could otherwise be Convex.

## Backups

`convex-backup.timer`, nightly, 30 days retained, `/var/backups/convex`.
Restore:

```sh
cd /opt/ayurveda/ayurveda-frontend/packages/backend
node ../../node_modules/convex/bin/main.js import --replace <archive.zip>
```

The off-box copy in `deploy/backup.sh` is still commented out. Until it points
at real storage, the archives share a disk with the database they exist to
protect — which is not a backup.

## Secrets

`/etc/ayurveda/*.env`, mode 600, root owned, never in git. Every variable is
documented in `deploy/env/*.env.example`. These are not recoverable from the
repository: `INSTANCE_SECRET`, the Convex admin key, `JWT_PRIVATE_KEY`, the Groq
key and the SMTP password all need to live somewhere else as well.
