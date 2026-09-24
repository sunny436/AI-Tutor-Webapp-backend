# Self-hosted observability (GlitchTip)

Error monitoring without an external SaaS. GlitchTip speaks the Sentry protocol, so the
app's existing `@sentry/nextjs` wiring (client/server/edge configs + `withSentryConfig`)
reports here with **no code change** — you only set a DSN.

## Deploy
```bash
cd self-hosted/glitchtip
cat > .env <<EOF
SECRET_KEY=$(openssl rand -hex 32)
GLITCHTIP_DOMAIN=https://<public-url-of-this-instance>
EOF
docker compose up -d
```
`GLITCHTIP_DOMAIN` must be the URL the **browser** uses to reach GlitchTip (it's baked into
the DSN). On a LAN, that's `http://<host>:8000`; for a remote browser, expose `:8000` (e.g.
a Cloudflare tunnel) and use that URL. The web app's server reaches it at the same URL.

## Create a project + DSN
Open `GLITCHTIP_DOMAIN` in a browser, create the first (admin) account, an organisation and
a project, then copy the project's DSN from its settings page.

## Wire the app
Set in the web app's environment (`/etc/aichat/web.env`; baked into the next release's build):
```
NEXT_PUBLIC_SENTRY_DSN=<the DSN above>
# optional: NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE=0.1
```
Rebuild the web app; its errors now report to GlitchTip. `ALLOWED_HOSTS` defaults to a
wildcard, so set it before exposing this beyond a trusted network.
