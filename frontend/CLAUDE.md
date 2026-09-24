# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The web app for "Assistant", a ChatGPT-style chat product: Next.js 14 App Router, React 18, TypeScript, Tailwind, Radix, in a Bun + Turborepo monorepo (`apps/app` is the app, `packages/ui` the design system). **Frontend only.** Accounts, conversations, messages and the LLM all live in the chat API: FastAPI + PostgreSQL/pgvector, in a separate repo (locally `../AI Tutor- Backend`). The app was converted from an Ayurveda chatbot that ran on Convex. No Convex, i18n or Ayurveda code remains, apart from a `/consult` → `/` legacy redirect.

Git: push to the `tutor` remote (`sunny436/AI-Tutor-Webapp-frontend`). `origin` (akshat948) is the retired original. `ollastack.txt` and `ollima.txt` in the repo root hold tokens and are gitignored. Never add them.

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

Adding an endpoint means adding it to `ROUTES`. `routes.test.ts` fails unless the route and its request-body fields exist in the repository's `docs/openapi.json`, which the backend generates. The API contract is the backend's, and both live in this repository. `docs/frontend-api.md` lists the BFF behaviour and the known contract gaps: feedback isn't returned with messages, there's no sessions list, and there's no server-side search.

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

**Routes.** The `(auth)` group holds `/login` and `/signup`; one `AuthForm` handles sign-in, sign-up, verify, forgot and reset. In `(app)/(chat)/`, **the layout renders `ChatView`** and the two pages (`/`, `/c/[conversationId]`) return null. That way a new chat getting its URL on `meta` doesn't remount the view or stop its stream. `/settings` is separate.

**Chat state (`features/chat/chat-store.ts`).** An external store read through `useSyncExternalStore`, created once in `ChatProvider`:
- **Keys:** entries are keyed by conversation id. An unsent new chat gets a `draft:n` key, aliased to the real id when `meta` arrives.
- **Subscriptions:** the message list subscribes to `order` and each message to its own id, and tokens are batched (~50 ms). A token therefore re-renders only the streaming message, which an E2E test checks with a `MutationObserver`.
- **Stream ownership:** the store owns streams, not pages, so switching chats never stops a reply.
- **Rules that must hold:**
  - send only `{conversationId?, message}` and never send history;
  - never re-send on a failed or cut-off stream; re-read the conversation instead;
  - Stop means `POST cancel`, then read until `done` (≤3 s), then abort.
- **Drafts** live in a silent map, so typing doesn't notify subscribers.
- **Sidebar:** `features/conversations/conversations-store.ts` backs the sidebar list.

**Reply renderer (`features/markdown/`).** `message-content.tsx` runs react-markdown + GFM + math, with rehype-sanitize **first**, then KaTeX (`trust:false`) and highlight.
- Raw HTML is shown as text (no `rehype-raw`), links are limited to http, https and mailto, and images become links.
- The `components` map is the extension point for future block types.
- UI code imports the lazy wrapper `lazy-message-content.tsx`: the renderer is a separate ~170 kB gzipped chunk, preloaded when the chat mounts. Unit tests import `message-content.tsx` directly.
- KaTeX and highlight CSS load in `(app)/layout.tsx`, which keeps the renderer testable.

**Styling.** Use the tokens in `packages/ui/src/globals.css` (contrast-checked, light and dark), not raw colours. The CSP in `next.config.mjs` allows only `'self'`, with `'unsafe-eval'`/`ws:` in dev only.

## Production

This app ships in the same release as the API (one commit, one deploy; see the root `CLAUDE.md`,
`docs/deployment.md` and `docs/rollback.md`). A single Ubuntu VM behind a Cloudflare Tunnel:
- **Web app:** `ayur.namahos.com` → `aichat-web.service` on 127.0.0.1:3000 (`bun run start` in
  `/opt/aichat/current/frontend/apps/app`, env `/etc/aichat/web.env`).
- **API:** `aichat-api` on 127.0.0.1:4100, from the same release directory. `API_BASE_URL` in
  `web.env` must stay `http://127.0.0.1:4100`.
- **Builds:** each release is built in its own directory (`/opt/aichat/releases/<commit>`), never in
  place under the running app. `NEXT_PUBLIC_*` values are baked in at build time from `web.env`.
- **Legacy stack:** the old Ayurveda stack (`ayurveda-*`, `convex`) is still installed there for rollback.
