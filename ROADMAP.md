# Roadmap

Deferred work, captured so it isn't lost. Ordered roughly by priority.

## ✅ Done (current state)
Self-hosted Convex (Docker) · multi-tenant platform (workspaces/RBAC/invites) · hybrid backend adapter (proxy / JWKS-direct / webhook) · jobs · usage · API keys · audit · events · files · **full auth** (email+password, mandatory email verification, password reset, magic OTP, Google provider [creds pending], password policy, brute-force lockout 5/hr) · real HTTPS via Cloudflare tunnel · **left sidebar shell** + reactive workspace switcher + responsive drawer · **toasts + confirm dialogs** · CI (typecheck+lint) + branch protection · nightly backup.

## 1. Dashboard UX
- ✅ **Home overview** — real stat cards (consultations, open jobs, files, members), 7-day
  consultations chart, recent-activity feed, quick actions.
- ✅ **Command palette (⌘K)** + **notifications center** (`notifications` table with
  `by_user` / `by_user_read` indexes, functions, bell UI).
- ✅ **Pagination / load-more** on jobs · files · audit · events — closes **BUG-8**.
  All four use `paginate(paginationOpts)` + `usePaginatedQuery` (20/page). The unpaginated
  `audit.recent` / `backend.listEvents` (`take(50)`) are kept for the home activity feed.
- ✅ **Account security** — change password, active sessions / sign-out-everywhere,
  delete account UI (all on the General settings page).
- ✅ **Polish** — 404 page, error boundary, empty states; dead `_components/navigation.tsx` removed.
- **Remaining: settings restructure** — settings has only two sections (General · Billing).
  Split into Profile · Security · Notifications · Team · Billing · API keys · Danger zone,
  moving the security cards out of General and the team/API-key surfaces off `/platform`.
- **Remaining: polish tail** — loading skeletons, footer/version, help/docs link,
  keyboard-shortcut hints.

## 2. Production-readiness
- **Named Cloudflare tunnel + real domain** — replaces the ephemeral `*.trycloudflare.com` URLs (which change on `cloudflared` restart and require an app rebuild). Gives stable URLs, real Let's Encrypt certs, and **activates Google OAuth** (stable redirect URI).
- **Email — local option DONE (Mailpit), or Resend for real delivery.** Auth emails now send
  over SMTP via a Node action (`convex/email.ts` + `nodemailer`); set `SMTP_HOST`/`SMTP_PORT`
  (+ optional `SMTP_USER`/`SMTP_PASS`/`SMTP_FROM`). Pointed at self-hosted **Mailpit**
  (`deploy/50-mailpit.sh`, SMTP `:1025`, web inbox `:8025`) and verified a signup email lands.
  The code is still logged as a fallback, so log-mode keeps working when SMTP is unset. For
  real outbound mail, set `SMTP_*` to Resend's SMTP (or any provider) — no code change.
- **Google OAuth** — add `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET` + register the callback (needs the domain above).
- **Strong `INSTANCE_SECRET`** for the Convex backend (currently the compose default) before any real use.
- **Observability — DONE via self-hosted GlitchTip** (no external SaaS). `self-hosted/glitchtip/`
  brings up a Sentry-protocol-compatible stack; the app's existing `@sentry/nextjs` wiring reports
  to it by setting `NEXT_PUBLIC_SENTRY_DSN` to the GlitchTip DSN. Verified end-to-end on the VM
  (injected error stored as an `IssueEvent`). Trace sampling defaults to 10%
  (`NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE`). For a real deployment, set GlitchTip `ALLOWED_HOSTS`.
  (Sentry SaaS still works too — just use its DSN instead.)
- **Verify `deploy/setup.sh` on a clean VM** — the one-command clone install is written but never run end-to-end.

## 3. Audit backlog (low severity)
- ✅ **BUG-6** — internal seed/test functions are gated behind `DEV_SEED=1` via
  `convex/devGuard.ts` (`requireDevSeed()`), applied across `seed`, `orgs`, `jobs`,
  `apiKeys`, `audit`, `counters`. `backend-echo` remains reference-only.
- ✅ **BUG-8** — pagination done on jobs · files · audit · events (see Dashboard UX above).

## Performance (from the read-amplification audit)
Profiled with `convex/seed.ts` (DEV_SEED-gated load generators + profilers) on a
seeded 8k-job / 5k-notification workspace:
- **Fixed:** `notifications.unreadCount` read **5001 rows** (collect-all) → now **10**
  (indexed `by_user_read` + `take(10)`; the bell only needs 0..9 / "9+"). O(10) at any scale.
- **FIXED:** `dashboard.stats` no longer scans every row. A `counters` table (jobs/openJobs/
  files/members) is maintained via `bump()` in `jobs.create`/`complete`, `files.saveFile`/`remove`,
  and member add/remove; `stats` reads O(#metrics) instead of O(workspace size). Drift-guarded by
  a unit test (create→complete→counts) and backfilled for existing data (`counters:backfillAll`).
  Was ~8001 rows/render on an 8k-job workspace. (`orgs.members`/`myWorkspaces` still do N+1
  `ctx.db.get` per row — fine at team sizes; revisit only if memberships grow large.)

## Notes / caveats
- Email is **log-fallback** until Resend is configured (codes appear in Convex logs).
- The `trycloudflare` URLs are **ephemeral**; `NEXT_PUBLIC_CONVEX_URL` is baked at build, so a tunnel restart needs a rebuild — move to a named tunnel/domain for stability.
