# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The web app of PadhAI, an AI tutor built on a ChatGPT-style chat: Next.js 15 App Router, React 19, TypeScript, Tailwind, Radix, in a Bun + Turborepo monorepo (`apps/app` is the app, `packages/ui` the design system). **Frontend only.** Accounts, conversations, messages and the LLM all live in the chat API: FastAPI + PostgreSQL/pgvector, in this repository's `backend/`. The app was converted from an Ayurveda chatbot that ran on Convex. No Convex, i18n or Ayurveda code remains, apart from a `/consult` → `/` legacy redirect.

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
- **Session cookie:** Better Auth's httpOnly cookie (`__Host-padhai_session` over HTTPS, `padhai_session` on local HTTP); `lib/server/cookies.ts` verifies its HMAC signature (BETTER_AUTH_SECRET) before a token goes anywhere, and sign-out/deletion clear it (and the pre-Better-Auth `aichat_session`).
- **Headers upstream:** sends the token upstream as `Authorization: Bearer`, plus `X-Request-ID`. `X-Forwarded-For` is taken **only** from `cf-connecting-ip`, because the API rate-limits on its first entry.
- **Request checks:** enforces an Origin check (`403 forbidden`), JSON-only bodies and a 64 KB cap.
- **401s:** clears the cookie on an upstream 401, **except** `invalid_credentials`, so a wrong password must not sign the user out.
- **Streams and errors:** pipes SSE unbuffered, and a downstream cancel aborts upstream. It also re-wraps error envelopes to `{code, requestId, fields}`.

Adding an endpoint means adding it to `ROUTES`. `routes.test.ts` fails unless the route and its request-body fields exist in the repository's `docs/openapi.json`, which the backend generates. The API contract is the backend's, and both live in this repository. `docs/frontend-api.md` lists the BFF behaviour and the known contract gaps: feedback isn't returned with messages, and there's no server-side search.

**Settings** (`/settings/<section>`, `features/settings/`): each section is one or more versioned API resources (`{version, set, reset}`, docs/api-contract.md). Toggles save as they change through `AutoSaver` (batched, rolled back on failure, rebased once on 409 `version_conflict`); forms save on submit, keep the user's edit on a conflict and ask them to save again, and warn before leaving unsaved (`useUnsavedChanges`, backed by the one guard in `features/navigation/navigation-guard.ts`: links, Close, search, log out, reload, and the browser's Back/Forward through a sentinel history entry that relies on Next's support for external `history.pushState` (14.2+; re-checked on 15.5 by the WebKit Settings-workspace spec); re-check it on a Next upgrade). Enums and limits come from `lib/api/contract.gen.ts`; label maps are `Record<Enum, string>`, so a new API value is a compile error until named. A section appears in `SETTINGS_SECTIONS` only once it works end to end. **The workspace** (`settings-workspace.tsx`): Settings is not inside the app shell. `app/(app)/layout.tsx` holds the session check, every provider, the heartbeat and the guard, once; `(app)/(main)/layout.tsx` wraps the app in `AppShell`; `(app)/settings/layout.tsx` renders the workspace (panel with brand, Close, search and sections; top bar; the section). Close goes to the last app page of the tab (`features/navigation/app-return.ts`, sessionStorage, through `safeRedirect`). Below 768px `/settings` is the list and each section its own screen (All settings goes up); from 768px the panel sits beside the section and `/settings` opens the first one. Focus moves only when a view replaced what was used (`features/navigation/route-focus.ts`; section headings take it via `heading-focus.ts`). **Progress:** `useActivityHeartbeat` (mounted once in `app/(app)/layout.tsx`) reports an active minute to `POST /v1/progress/activity` by the rule in `lib/activity.ts` and fires `padhai:activity` when one is credited; the Progress section refreshes on it. There is no made-up number anywhere: when progress can't be read, it isn't shown. **Streak and bell** (`features/streak/`, `features/notifications/`): the learning streak is the server's (India days, a real question fully answered, `GET /v1/progress/streak`); `useStreak` refetches after each finished reply and each practice answer (`padhai:learning`, fired by `chat.onReplyFinished` and `chat.onPracticeAnswered`), when the tab is shown again and at India midnight. The header shows `StreakBadge` ("–" when it can't be read, never 0; hidden by Appearance `showStreak`), `DayCountdown` (the only timer) and `NotificationBell` (fetched on mount, focus and `padhai:learning`; no polling; opening it reads nothing: choosing a notification marks that one read, and Read all / Clear all (`POST /v1/notifications/read`, `/clear`) are kept by the server, so they outlast a reload; a list fetched before a change is never shown; milestones get one toast per tab). `LearningActivityCalendar.tsx` is the only importer of `@goujon/react-calendar-heatmap` (d3), loaded with `next/dynamic` on Settings > Learning & Streak only. Appearance is applied as `data-*` attributes on `<html>` (`lib/appearance.ts`, tokens in `packages/ui/src/globals.css`), cached for a pre-paint script, and reconciled from the API by `AppearanceProvider`; next-themes stays the only theme system.

**My Learning** (`/learning`, `features/my-learning/`): the student's practice record from question-bank tests in the chat, all computed by the API on read (`GET /v1/progress/plan`, `mastery`, `revisions`, `mistakes`, `practice-tests`, `practice-topics`): today's plan, a subject → chapter → topic picker, revision due, the exam date (set in Settings > Learning Goals), mastery estimates, mistakes and recent tests. Each panel loads, fails ("Try again", never zeros) and retries on its own. Its buttons never send: `ask-in-chat.ts` puts the request in the new chat's draft the way the File Library's "Ask in chat" does (`freshDraftKey`, in memory, never in the URL, so a reload does not refill it), on a line after any unsent text. A sidebar place like the File Library, not a Learning Hub tool, and not study time (`isLearningView`). Every practice answer refreshes the streak through `chat.onPracticeAnswered` (a retried answer's response has no `learning`); the one that makes the day a learning day comes back with the assessment response's `learning` and is celebrated like a reply's `done.learning`.

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

**Sign-in (Better Auth, `lib/auth/`).** `config.ts` (pure `createAuth`; `server.ts` builds it lazily, so `next build` needs no secret), `routes.ts` (the exact allowlist of `/api/auth/*` routes and the token stripping, unit-tested), `guard.ts` (per-account limits, atomic), `password.ts` (argon2id via Node's `crypto.argon2`, the API's PHC format; Bun has no `crypto.argon2`, so `bun test` covers only the format), `events.ts` (fire-and-forget calls to the API's `/internal/auth/*`), `client.ts` (the browser client). `app/api/account/password` gives an account its first password (needs a sign-in in the last 15 minutes). `SessionKeeper` (in `(app)/layout.tsx`) asks for the session once per load so Better Auth refreshes the expiry and the cookie together.

**Routes.** The `(auth)` group holds `/login` and `/signup`; one `AuthForm` (steps: signIn, signUp, code, password, forgot, reset; Google when `GOOGLE_CLIENT_ID` is set) does all of it through `authClient`. In `(app)/(main)/(chat)/`, **the layout renders `ChatView`** and the two pages (`/`, `/c/[conversationId]`) return null. That way a new chat getting its URL on `meta` doesn't remount the view or stop its stream. `(app)/(main)/` holds every page inside the app shell; `/settings` is its own workspace beside it (see Settings); `/help` and `/about` are plain signed-in pages (`features/help/`). `/unsubscribe` (an email's link) is public (`PUBLIC_PAGES` in `lib/server/gate.ts`), has its own layout, and only unsubscribes when its button is pressed.

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
- Raw HTML is shown as text (no `rehype-raw`), links are limited to http, https and mailto, and images become captioned placeholders with a link (never loaded).
- The `components` map is the extension point for block types. The tutor's syntax (taught by `backend/app/chat/assistant.py`) is parsed by `remark-tutor.ts`: study cards `:::type[Title]` (note, important, warning, definition, example, steps, answer, takeaway, formula; GitHub `> [!NOTE]` alerts map to them), `::file{ref=F1}` / `::pdf{ref=F1 page=3}`, `[1]`/`[F1]` citations (chips plus a Sources list from `metadata.citations`), and a code fence's `filename="…"` (a Download button). Only block-level directives are parsed, never `:text` ones, so "a:b" stays prose. KaTeX has mhchem (`\ce`, `\pu`); `next.config.mjs` aliases every `katex` import to the one copy that has it.
- Fenced `mermaid`, `chart` (Chart.js), `mcq`, `quiz`, `flashcards`, `fill-blank`, `graph` (mathjs allowlist + Chart.js) and `diagram` (React Flow + dagre) blocks are drawn by `rich-block.tsx`: each widget is its own lazy chunk with its own Suspense and error boundary, a placeholder while the reply is still writing it, and the code block if it can't be drawn. `mcq`, `quiz` (tests) and `fill-blank` (exercises) are practice blocks the server keeps (`app/assessments`, docs/api-contract.md "Practice tests"): each card (`widgets/quiz.tsx`, `widgets/fill-blank.tsx`, bound by `useRecord`) draws only the reply's `metadata.assessments` record whose `locator` matches its block (`assessment.ts`), answers are final and go to `POST /v1/messages/{id}/assessment-responses` (an option index, or one text per blank), a typed letter, `skip` or `next` reaches only the chat's latest practice block when it is an unfinished test (`chat-store.ts` `testTarget`), and nothing is scored or kept in the browser; a block with no record shows its source and why. Flashcards, graphs and diagrams are not recorded (the tutor is told so). mermaid runs strict and is shown as an image. Colours come from tokens at draw time (`widgets/tokens.ts`: `--chart-1..6`, a validated categorical order; `--study-card-background` for every card). The PDF preview's worker is copied to `public/pdfjs/<version>/` by `scripts/copy-pdfjs.mjs` before `dev`/`build` (not a webpack asset; no WebAssembly under the CSP).
- UI code imports the lazy wrapper `lazy-message-content.tsx`: the renderer is a separate ~170 kB gzipped chunk, preloaded when the chat mounts. Unit tests import `message-content.tsx` directly.
- KaTeX and highlight CSS load in `(app)/layout.tsx`, which keeps the renderer testable.

**Styling.** Use the tokens in `packages/ui/src/globals.css` (contrast-checked, light and dark), not raw colours. **Type** is Noto Sans (self-hosted variable fonts, `src/lib/fonts.ts`; Devanagari loads only when shown) on one rem scale in `packages/ui/tailwind.config.ts`: body `text-base` 16/1.65, UI `text-sm` 14/1.45, captions `text-xs` 13/1.40, headings H3 `text-lg` 17, H2 `text-xl` 20, H1 `text-2xl` 24 (600); the reading width is `max-w-prose` (680px). **Motion** is one small system: the tokens `--motion-fast|base|slow` and `--ease-standard|enter|exit` in `packages/ui/src/globals.css` (Tailwind `duration-fast|base|slow`, `ease-standard|enter|exit`; a bare `transition` is fast + standard, and tailwindcss-animate reads the same scale). Enter decelerates, exit is fast and accelerates; only transform/opacity move (the sidebar width is the one exception); never `transition-all`, bounce or decorative loops. Deliberate exceptions are listed next to the tokens. Reduced motion (OS or Settings) is global; JS smooth scrolling must check it itself (`use-stick-to-bottom.ts`). `e2e/motion.e2e.ts` enforces it. The one typeface is Poppins, vendored (`src/fonts/poppins`, OFL) and loaded by `next/font/local` in `lib/fonts.ts` as `--font-poppins`; Tailwind's `sans` and `display` use it, so nothing fetches a font at build or run time. The CSP in `next.config.mjs` allows only `'self'`, with `'unsafe-eval'`/`ws:` in dev only.

**Preview UI.** The learning tools (Homework Helper, Summarizer), the leaderboard and similar sample-data UI render only with `PREVIEW_FEATURES=1`: a server env var read per request by `(app)/layout.tsx` (`lib/preview.ts`), never set in production. `e2e/gated.e2e.ts` and `e2e/preview.e2e.ts` check both states. Build the real versions on `/v1` APIs; `features/learning-hub/demo-data.ts` is a placeholder, not data. The My Courses, Course Creator and Flashcards previews were removed when My Learning replaced them (the chat's own `flashcards` block stays).

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
