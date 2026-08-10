# Test report — production deployment

**Target:** https://ayur.namahos.com (app) · https://ayur-api.namahos.com (AI backend)
**Date:** 2026-08-10
**Ran against:** the live site, through Cloudflare, in a real Chromium browser.

---

## Summary

| Suite | Result |
|---|---|
| `e2e/prod-full.js` — full flow on the live domain | **17 / 17 passed** |
| `e2e/auth-live.js` — every sign-in path, live domain | **11 / 11 passed** |
| `backend-python/tests/test_retrieval.py` | **84 / 84 passed** |
| `backend-python/tests/test_safety.py` | **40 / 40 passed** |
| `backend-python/tests/test_memory.py` | **12 / 12 passed** |
| `backend-python/tests/test_provider_split.py` | **16 / 16 passed** |
| `backend-python/tests/test_cooldown.py` | **9 / 9 passed** |
| `backend-python/tests/test_persona.py` | **7 / 8 passed** — see below |
| `packages/backend` typecheck | passed |
| `packages/backend` unit tests | **could not run on Windows** — see below |

---

## What was verified on the live site

Every line below was checked against `https://ayur.namahos.com`, not localhost.

**Transport and headers**
- Page loads over HTTPS with a valid certificate
- `http://` is answered with a 308 to `https://`
- `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Content-Security-Policy: frame-ancestors 'none'`,
  `Referrer-Policy`, `Permissions-Policy` all present
- No mixed content, no CORS failures, no critical console errors

**Authentication** (all five paths, with codes read from a real inbox over IMAP)
- Sign up with email and password
- Email verification code delivered and accepted
- Password sign-in
- Forgot password → reset code → new password
- Passwordless email OTP
- Google button reaches `accounts.google.com` with a client id Google accepts
- Sign out ends the session; `/consult` then redirects to `/login`
- A session survives a full page refresh

**Application**
- Consult screen opens and accepts input
- AI answers in **English**, **Devanagari Hindi** and **Hinglish**
- An existing conversation reloads with its history

**Authorisation**
- A second account cannot see the first account's conversation
- The AI backend returns **401** to unauthenticated callers
- `/debug/retrieve` returns **404** — indistinguishable from a path that does
  not exist, so it does not advertise itself

**Network exposure**
- `http://<machine-lan-ip>:3000` — connection refused
- `http://<machine-lan-ip>:4000` — connection refused
- Both processes listen on `127.0.0.1` only

**Secrets**
- The Cloudflare token is absent from the built browser bundle, from Git, from
  Git history, and from the runtime logs
- No `.env` file is tracked; `cloudflare/.env` is invisible even to `git add -A`

**Resilience**
- Killing `cloudflared` took the site to 502; the watchdog restarted it and the
  site returned **200** without intervention

---

## Bugs found and fixed during this work

These were all real, and all of them were invisible before the app was published.

1. **`/login` redirected to itself forever.** The public-route matcher listed
   `/login`, but the i18n layer had already rewritten the path to `/en/login`, so
   the login page counted as protected. Nobody could sign in.

2. **Users were redirected to `localhost:3000`.** Next does not trust the `Host`
   header for `request.nextUrl` behind a proxy, so redirects were built against
   localhost. On the live domain that sent visitors to an address on their own
   machine.

3. **Every page returned 500 behind the tunnel.** The locale rewrite was built
   from `request.url`, which reads `https://localhost:3000` behind a TLS proxy —
   an origin this server does not serve — so Next tried to proxy the request to
   itself over TLS and the connection was refused.

4. **Sign-in appeared to hang.** After the rewrite was made "internal", the
   re-entrant middleware run arrived with `Host: localhost`, and Convex Auth
   names its cookies from `Host` — dropping the `__Host-` prefix on localhost. It
   looked for a cookie the browser had never set, decided the visitor was signed
   out, and bounced `/` → `/login` → `/` until the browser gave up. Fixed by
   switching the i18n strategy from rewrite to redirect.

5. **The AI backend accepted anonymous requests from the internet.** Deliberate
   on localhost; unacceptable once published, because anyone could spend the
   free-tier LLM quota and take the product down for real users. `/consult`,
   `/upload`, `/transcribe` and `/speak` now require a signed-in caller.

6. **Login tokens were never actually verified.** Convex issues JWTs with no
   `kid`, and PyJWT's `get_signing_key_from_jwt()` matches on `kid`. Verification
   always failed, and the failure was swallowed into the same empty string used
   for genuinely anonymous callers. **Consequence: conversation memory and
   uploaded reports were never retrieved for the person who owned them** — the
   consultation still answered, just without any of the caller's own context.

7. **The `/backend/user-memory` route was not deployed.** It existed in the
   repository but returned 404 on the deployment, so cross-session memory could
   not work. Fixed by deploying.

8. **A Convex error on every sign-out.** `ensureWorkspace` was called before the
   auth state settled and threw "Not authenticated" into the browser console.

---

## Not passing, and why

**`test_persona` 7/8 — Devanagari input sometimes gets a Latin-script reply.**
The rule is in the system prompt and the other seven assertions pass. The model
does not always follow it. This is model behaviour, not a regression: it fails
intermittently across runs with no code change in between. Worth revisiting with
a stricter prompt or a post-check on the reply script.

**`packages/backend` unit tests do not run on Windows.** Documented in
`vitest.config.ts`: vitest 3.2.7 pins vite-node 3.2.4, whose executor calls
`pathToFileURL("/@vite/env")` — an absolute path on POSIX, but not on Windows,
where it throws. The suite runs correctly on Linux and macOS. Typecheck passes
here, and user isolation was instead verified live with two real accounts, which
is the stronger test.

---

## What was deliberately not done

**Cloudflare zone-level settings were left alone.** `namahos.com` also carries
the company's main site, a Vercel deployment and production email. *Always Use
HTTPS*, *SSL: Full (strict)*, *HSTS* and *Minimum TLS 1.2* are zone-wide, so
enabling them for this app could break services owned by other people. The
HTTP→HTTPS redirect and all security headers are therefore applied inside this
application, where their blast radius is this application.

Two zone settings are worth raising with whoever owns the domain:
- `min_tls_version` is **1.0**; 1.2 would be better for everyone on the zone.
- Zone-level HSTS is off. Enabling it needs a check that every subdomain,
  including `mail.`, is HTTPS-ready.

---

## Honest limits of this report

- This tests the paths listed above. It is not a proof that the application is
  free of defects, and it is not a security audit.
- Uptime depends on the machine staying powered, awake and connected. Sleep and
  hibernate are disabled and a watchdog restarts crashed processes, but a
  reboot needs someone to log in before the site returns, because installing a
  real Windows service requires administrator rights this account does not have.
- The AI answers were verified as *arriving and being coherent in the right
  language*. Clinical quality was not assessed.
