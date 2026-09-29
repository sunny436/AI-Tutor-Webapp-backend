# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The web app of PadhAI, an AI tutor built on a ChatGPT-style chat: Next.js 14 App Router, React 18, TypeScript, Tailwind, Radix, in a Bun + Turborepo monorepo (`apps/app` is the app, `packages/ui` the design system). **Frontend only.** Accounts, conversations, messages and the LLM all live in the chat API: FastAPI + PostgreSQL/pgvector, in this repository's `backend/`. The app was converted from an Ayurveda chatbot that ran on Convex. No Convex, i18n or Ayurveda code remains, apart from a `/consult` → `/` legacy redirect.

It is the API's first client, not the platform: durable data and business rules belong in the API (root `CLAUDE.md`, "web-first, not web-only"); browser storage holds UI state only.

Git: this folder is part of the single application repository (see the root `CLAUDE.md`); commit and push from there. The old frontend repository (`sunny436/AI-Tutor-Webapp-frontend`) is no longer used. `ollastack.txt` and `ollima.txt` in the repository root hold tokens and are gitignored. Never add them.

## Commands

```bash
bun install
bun dev                          # http://localhost:3000; expects the API at http://127.0.0.1:4000
cd apps/app
bun run typecheck
bun run lint                     # biome lint (formatting not enforced in apps/app)
bun run test                     # unit tests: bun test ./src
bun test src/lib/api/sse.test.ts # one file
bun test ./src -t "stop"         # tests whose name matches
NEXT_DIST_DIR=.next-verify bun run build   # verify a build without touching .next
```

- Root `bun run lint` also runs `packages/ui`'s `biome check .`, which **does** enforce formatting. Run `biome check --write .` in `packages/ui` after editing there.
- `next build` rewrites `apps/app/tsconfig.json` (it adds its dist dir's types and reformats). Revert that with `git checkout -- apps/app/tsconfig.json` rather than committing it.
- Open `http://localhost:3000`, not `127.0.0.1`. Next's `NextURL` rewrites 127.0.0.1 to `localhost` in middleware redirects, and the session cookie is per host name.

**End-to-end** (Playwright + axe, Chromium, `apps/app/e2e/*.e2e.ts`) runs a production build on :3100 (`.next-e2e`, via `e2e/serve.mjs`) against a **local** API on :4100 with the fake LLM, and reads sign-up codes from Mailpit (:8025). `global-setup.ts` refuses any non-loopback URL.

```bash
bunx playwright install chromium             # once
bun run test:e2e                             # reuses an API on :4100, else starts ../backend (needs backend/.venv)
E2E_BACKEND_DIR=none bun run test:e2e        # never start the API; one must already be running
bun run test:e2e e2e/journey.e2e.ts -g "journey"            # one spec / test (--list to preview)
E2E_SKIP_BUILD=1 bun run test:e2e            # reuse the last .next-e2e build
```

The fake LLM replies `You said: <message>` word by word, so tests assert on echoes. The API rejects the `.test` TLD, so test addresses use `@example.com`.

## Architecture

**Browser → BFF → API.** The browser never calls the API. `app/api/v1/[...path]/route.ts` is a thin wrapper over `lib/server/proxy-core.ts`, which forwards only the routes allowlisted in `lib/api/routes.ts` to `API_BASE_URL`, a server-only env var. The proxy:
- **Session cookie:** keeps the API's session token in an httpOnly cookie (`__Host-aichat_session` over HTTPS, `aichat_session` on local HTTP). On login, verify-email and password-reset it sets the cookie and strips the token from the body, returning only `{user}`.
- **Headers upstream:** sends the token upstream as `Authorization: Bearer`, plus `X-Request-ID`. `X-Forwarded-For` is taken **only** from `cf-connecting-ip`, because the API rate-limits on its first entry.
- **Request checks:** enforces an Origin check (`403 forbidden`), JSON-only bodies and a 64 KB cap.
- **401s:** clears the cookie on an upstream 401, **except** `invalid_credentials`, so a wrong password must not sign the user out.
- **Streams and errors:** pipes SSE unbuffered, and a downstream cancel aborts upstream. It also re-wraps error envelopes to `{code, requestId, fields}`.

Adding an endpoint means adding it to `ROUTES`. `routes.test.ts` fails unless the route and its request-body fields exist in the repository's `docs/openapi.json`, which the backend generates. The API contract is the backend's, and both live in this repository. `docs/frontend-api.md` lists the BFF behaviour and the known contract gaps: feedback isn't returned with messages, and there's no server-side search.

**Settings** (`/settings/<section>`, `features/settings/`): each section is one or more versioned API resources (`{version, set, reset}`, docs/api-contract.md). Toggles save as they change through `AutoSaver` (batched, rolled back on failure, rebased once on 409 `version_conflict`); forms save on submit, keep the user's edit on a conflict and ask them to save again, and warn before leaving unsaved (`useUnsavedChanges`, backed by the one guard in `features/navigation/navigation-guard.ts`: links, Close, search, log out, reload, and the browser's Back/Forward through a sentinel history entry that relies on Next 14.2's support for external `history.pushState`; re-check it on a Next upgrade). Enums and limits come from `lib/api/contract.gen.ts`; label maps are `Record<Enum, string>`, so a new API value is a compile error until named. A section appears in `SETTINGS_SECTIONS` only once it works end to end. **The workspace** (`settings-workspace.tsx`): Settings is not inside the app shell. `app/(app)/layout.tsx` holds the session check, every provider, the heartbeat and the guard, once; `(app)/(main)/layout.tsx` wraps the app in `AppShell`; `(app)/settings/layout.tsx` renders the workspace (panel with brand, Close, search and sections; top bar; the section). Close goes to the last app page of the tab (`features/navigation/app-return.ts`, sessionStorage, through `safeRedirect`). Below 768px `/settings` is the list and each section its own screen (All settings goes up); from 768px the panel sits beside the section and `/settings` opens the first one. Focus moves only when a view replaced what was used (`features/navigation/route-focus.ts`; section headings take it via `heading-focus.ts`). **Progress:** `useActivityHeartbeat` (mounted once in `app/(app)/layout.tsx`) reports an active minute to `POST /v1/progress/activity` by the rule in `lib/activity.ts` and fires `padhai:activity` when one is credited; the Progress section refreshes on it. There is no made-up number anywhere: when progress can't be read, it isn't shown. **Streak and bell** (`features/streak/`, `features/notifications/`): the learning streak is the server's (India days, a real question fully answered, `GET /v1/progress/streak`); `useStreak` refetches after each finished reply (`padhai:learning`, fired by `chat.onReplyFinished`), when the tab is shown again and at India midnight. The header shows `StreakBadge` ("–" when it can't be read, never 0; hidden by Appearance `showStreak`), `DayCountdown` (the only timer) and `NotificationBell` (fetched on mount, focus and `padhai:learning`; no polling; opening marks what it shows read; milestones get one toast per tab). `LearningActivityCalendar.tsx` is the only importer of `@goujon/react-calendar-heatmap` (d3), loaded with `next/dynamic` on Settings > Learning & Streak only. Appearance is applied as `data-*` attributes on `<html>` (`lib/appearance.ts`, tokens in `packages/ui/src/globals.css`), cached for a pre-paint script, and reconciled from the API by `AppearanceProvider`; next-themes stays the only theme system.

**Client API layer (`lib/api/`).**
- `http.ts`: `callRoute(key, …)`, which calls `/api` + path.
- `sse.ts`: a WHATWG-style parser for LF, CRLF or CR, split chunks and multi-line data.
- `chat.ts`: stream outcomes `done | error | interrupted | aborted`.
- `errors.ts`: maps every API code to the app's own copy plus a recovery action. The API's message text is never shown.

**Server-only code is split** into pure, unit-testable cores (`proxy-core.ts`, `gate.ts`, `cookies.ts`, `public-origin.ts`, `expired.ts`) and thin `server-only` modules (`session.ts`), because `server-only` throws outside Next.

**Auth and gating.**
- `middleware.ts` + `lib/server/gate.ts` only check that the cookie is present; `/api` is never redirected.
- `(app)/layout.tsx` validates the session with `GET /v1/me`. A 401 goes to `/api/session/expired`, which re-checks `/me` before clearing the cookie. An unreachable API renders `ServiceUnavailable` instead of signing the user out.
- Redirects are built from forwarded headers via `publicUrlFor`, because production sits behind a Cloudflare Tunnel. The HTTPS redirect is gated on `cf-ray`.
- `safeRedirect` guards every `?redirect=`.

**Routes.** The `(auth)` group holds `/login` and `/signup`; one `AuthForm` handles sign-in, sign-up, verify, forgot and reset. In `(app)/(main)/(chat)/`, **the layout renders `ChatView`** and the two pages (`/`, `/c/[conversationId]`) return null. That way a new chat getting its URL on `meta` doesn't remount the view or stop its stream. `(app)/(main)/` holds every page inside the app shell; `/settings` is its own workspace beside it (see Settings); `/help` and `/about` are plain signed-in pages (`features/help/`). `/unsubscribe` (an email's link) is public (`PUBLIC_PAGES` in `lib/server/gate.ts`), has its own layout, and only unsubscribes when its button is pressed.

**Chat state (`features/chat/chat-store.ts`).** An external store read through `useSyncExternalStore`, created once in `ChatProvider`:
- **Keys:** entries are keyed by conversation id. An unsent new chat gets a `draft:n` key, aliased to the real id when `meta` arrives.
- **Subscriptions:** the message list subscribes to `order` and each message to its own id, and tokens are batched (~50 ms). A token therefore re-renders only the streaming message, which an E2E test checks with a `MutationObserver`.
- **Stream ownership:** the store owns streams, not pages, so switching chats never stops a reply.
- **Rules that must hold:**
  - send only `{conversationId?, message, attachmentIds?}` (ids of ready files, omitted when there are none) and never send history;
  - never re-send on a failed or cut-off stream; re-read the conversation instead;
  - Stop means `POST cancel`, then read until `done` (≤3 s), then abort.
- **Drafts** live in a silent map, so typing doesn't notify subscribers.
- **Attachments** (`features/files/attachment-store.ts`, also created in `ChatProvider`): a draft's files and their way to ready (one upload at a time, polling while read), so uploads survive navigation. Send waits until every chip is ready; Remove only detaches (deleting is a File Library action). A refused send gives the files back (`onSendRefused`). The File Library (`/library`, `features/files/library-view.tsx`) uploads through the same store and is a standalone sidebar link, not a `NAV_ITEMS` entry.
- **Dictation** (`features/chat/dictation.ts`, `use-dictation.ts`): the browser's Web Speech API, final results only, appended to the draft, never sent by itself; hidden where the browser has no recognizer. Needs `microphone=(self)` in `next.config.mjs`.
- **Sidebar:** `features/conversations/conversations-store.ts` backs the sidebar list.

**Reply renderer (`features/markdown/`).** `message-content.tsx` runs react-markdown + GFM + math, with rehype-sanitize **first**, then KaTeX (`trust:false`) and highlight.
- Raw HTML is shown as text (no `rehype-raw`), links are limited to http, https and mailto, and images become links.
- The `components` map is the extension point for future block types.
- UI code imports the lazy wrapper `lazy-message-content.tsx`: the renderer is a separate ~170 kB gzipped chunk, preloaded when the chat mounts. Unit tests import `message-content.tsx` directly.
- KaTeX and highlight CSS load in `(app)/layout.tsx`, which keeps the renderer testable.

**Styling.** Use the tokens in `packages/ui/src/globals.css` (contrast-checked, light and dark), not raw colours. **Type** is Noto Sans (self-hosted variable fonts, `src/lib/fonts.ts`; Devanagari loads only when shown) on one rem scale in `packages/ui/tailwind.config.ts`: body `text-base` 16/1.65, UI `text-sm` 14/1.45, captions `text-xs` 13/1.40, headings H3 `text-lg` 17, H2 `text-xl` 20, H1 `text-2xl` 24 (600); the reading width is `max-w-prose` (680px). **Motion** is one small system: the tokens `--motion-fast|base|slow` and `--ease-standard|enter|exit` in `packages/ui/src/globals.css` (Tailwind `duration-fast|base|slow`, `ease-standard|enter|exit`; a bare `transition` is fast + standard, and tailwindcss-animate reads the same scale). Enter decelerates, exit is fast and accelerates; only transform/opacity move (the sidebar width is the one exception); never `transition-all`, bounce or decorative loops. Deliberate exceptions are listed next to the tokens. Reduced motion (OS or Settings) is global; JS smooth scrolling must check it itself (`use-stick-to-bottom.ts`). `e2e/motion.e2e.ts` enforces it. The one typeface is Poppins, vendored (`src/fonts/poppins`, OFL) and loaded by `next/font/local` in `lib/fonts.ts` as `--font-poppins`; Tailwind's `sans` and `display` use it, so nothing fetches a font at build or run time. The CSP in `next.config.mjs` allows only `'self'`, with `'unsafe-eval'`/`ws:` in dev only.

**Preview UI.** The learning tools (My Courses, Homework Helper, Summarizer, Course Creator, Flashcards), the leaderboard and similar sample-data UI render only with `PREVIEW_FEATURES=1`: a server env var read per request by `(app)/layout.tsx` (`lib/preview.ts`), never set in production. `e2e/gated.e2e.ts` and `e2e/preview.e2e.ts` check both states. Build the real versions on `/v1` APIs; `features/learning-hub/demo-data.ts` is a placeholder, not data.

## Production

This app is deployed from the same commit of `main` as the API (`git push origin main && bun run
deploy`; see the root `CLAUDE.md`, `docs/deployment.md` and `docs/rollback.md`). A single Ubuntu VM
behind a Cloudflare Tunnel:
- **Web app:** `ayur.namahos.com` → `aichat-web.service` on 127.0.0.1:3000 (`bun run start` in
  `/opt/aichat/app/frontend/apps/app`, env `/etc/aichat/web.env`).
- **API:** `aichat-api` on 127.0.0.1:4100, from the same checkout. `API_BASE_URL` in `web.env` must
  stay `http://127.0.0.1:4100`.
- **Builds:** only when the frontend changed, built beside the served build (`NEXT_DIST_DIR=.next-build`)
  and swapped in, never in place under the running app. `NEXT_PUBLIC_*` values are baked in at build
  time from `web.env`.
- **Legacy stack:** the old Ayurveda stack (`ayurveda-*`, `convex`) is still installed there for rollback.
