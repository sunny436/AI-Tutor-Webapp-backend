# Roadmap — frontend

Deferred work for the Next.js app and the Convex backend that serves it.

**The AI backend has its own roadmap.** Retrieval, prompts, safety rules, the
GraphRAG document service, the Cloudflare tunnel and the self-hosted stacks live
in the backend repository. Anything about `backend-python/` belongs there.

---

## 1. Dashboard UX

Done: home overview with real stat cards and a 7-day chart · command palette (⌘K)
· notifications centre · pagination on jobs/files/audit/events (20/page via
`usePaginatedQuery`) · account security (change password, active sessions,
delete account) · 404 page, error boundary, empty states.

**Remaining:**

- **Settings restructure.** Settings has only two sections (General · Billing).
  Split into Profile · Security · Notifications · Team · Billing · API keys ·
  Danger zone — moving the security cards out of General and the team/API-key
  surfaces off `/platform`.
- **Polish tail.** Loading skeletons, footer/version, help/docs link,
  keyboard-shortcut hints.

## 2. Auth and email

- **Email** works over SMTP (`convex/email.ts` + `nodemailer`), pointed at
  self-hosted Mailpit and verified. The code is still logged as a fallback, so
  log-mode keeps working when SMTP is unset. For real outbound mail, point
  `SMTP_*` at Resend or any provider — **no code change**.
- **Google OAuth** — the button is **removed from the code**, not merely switched
  off. The credentials are NOT the gap: `AUTH_GOOGLE_ID` and `AUTH_GOOGLE_SECRET`
  were verified present on the Convex deployment, so the provider was registered
  and working. **The redirect URI is the gap.** The callback lives on the
  HTTP-actions origin, `https://ayur-convex-http.namahos.com/api/auth/callback/google`,
  and that address only exists since Convex moved onto the Ubuntu VM — Google
  Console still holds the previous one, so Google rejects the round trip before it
  reaches us. Every click failed, and silently, because the handler discarded the
  promise. **Restoring it is a Google Console round trip**, not an env-var fix:
  update the authorised redirect URI, then restore the block from git. Full note
  at the foot of `auth-form.tsx`.

## 3. Performance (from the read-amplification audit)

Both original findings are fixed; kept as a record of what the numbers were and
what maintains them, because both regress silently.

- `notifications.unreadCount` read **5001 rows** → now **10** (indexed
  `by_user_read` + `take(10)`; the bell only needs 0..9 / "9+"). O(10) at any scale.
- `dashboard.stats` no longer scans every row. A `counters` table is maintained
  via `bump()` in `jobs.create`/`complete`, `files.saveFile`/`remove`, and member
  add/remove. Was ~8001 rows per render on an 8k-job workspace. Drift-guarded by a
  unit test and backfilled via `counters:backfillAll` — **if you add a new writer
  to jobs, files or members, it must call `bump()`** or the counters silently drift.
- Still open, low priority: `orgs.members` / `myWorkspaces` do an N+1 `ctx.db.get`
  per row. Fine at team sizes; revisit only if memberships grow large.

## 4. Audit backlog

Both closed, kept for the record: **BUG-6** — internal seed/test functions gated
behind `DEV_SEED=1` via `convex/devGuard.ts`. **BUG-8** — pagination, above.

## Notes

- `NEXT_PUBLIC_CONVEX_URL` is **baked in at build time**, so a Convex URL change
  needs a rebuild, not just a restart. This is why a tunnel restart currently
  breaks the app.
- `apps/app/src/content/library.json` is **generated in the backend repository**
  and committed here. Treat it as read-only — content changes happen there.
- Staging is yours; production promotion is done by the backend team.
