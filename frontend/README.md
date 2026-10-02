# Assistant — web app

A ChatGPT-style chat app: sign in, chat with an AI assistant, keep your
conversations. Next.js 15 (App Router), React 19, TypeScript, Tailwind 3,
Radix.

This folder is the **frontend** of the application repository. Accounts,
conversations, messages and the model all live in the chat API next to it,
[`../backend`](../backend) (FastAPI + PostgreSQL). Both ship together in one
release. The browser never talks to the API directly: this app's own
`/api/v1/*` routes forward to it — see [`docs/frontend-api.md`](docs/frontend-api.md).

---

## Run it

You need [Bun](https://bun.sh) and the chat API running locally. From the
repository root, `bun run setup` and then `bun run dev` start both (with Mailpit
to catch sign-up and password-reset emails; see `../docs/development.md`). To run
only this app:

```bash
bun install
bun dev          # http://localhost:3000
```

Open **`http://localhost:3000`**, not `127.0.0.1:3000`. Next.js rewrites
127.0.0.1 to `localhost` in redirects, and the session cookie is per host name,
so a session started on 127.0.0.1 is lost at the first redirect.

With no configuration the app expects the API at `http://127.0.0.1:4000`. To
change anything, copy `apps/app/.env.example` to `apps/app/.env.local`:

| Variable | Default | What it is |
|---|---|---|
| `API_BASE_URL` | `http://127.0.0.1:4000` | Where the chat API listens. **Server-only** — never prefix it with `NEXT_PUBLIC_` |
| `NEXT_PUBLIC_SITE_URL` | `http://localhost:3000` | The app's public origin, for absolute URLs in metadata. Set it in production |
| `NEXT_PUBLIC_SENTRY_DSN` | empty | Error reporting. Sentry is only bundled when this is set |
| `NEXT_DIST_DIR` | `.next` | Build output directory (see below) |

---

## How it fits together

```
apps/app/src/
  app/                    routes: (auth) login/signup · (app) chat, /c/[id], settings · api/v1 (the BFF)
  lib/api/                the client: typed routes, errors, SSE parser, auth/conversation/chat calls
  lib/server/             server-only: the BFF proxy, session cookie, page gate, public origin
  features/chat/          chat store (per conversation), message list, composer, streaming
  features/conversations/ the sidebar's conversation list
  features/markdown/      the reply renderer (GFM, code highlighting, KaTeX, sanitised)
  components/             app shell, sidebar, auth form, settings
packages/ui/              shared components and the design tokens
docs/                     how the app uses the API; a copy of the API's OpenAPI schema
```

- **Sessions.** The API's session token is kept in an httpOnly cookie that the
  BFF sets and reads. Page JavaScript never sees it, and nothing about the
  session is stored in `localStorage` or `sessionStorage`.
- **History belongs to the API.** Sending a message posts only
  `{conversationId?, message}`; the API stores both sides of the conversation.
  The app keeps unsent drafts in memory, nothing else.
- **Streaming.** Replies arrive as server-sent events through the BFF. Each
  conversation streams independently, so switching chats never stops a reply,
  and a token re-renders only the message it belongs to.
- **Replies are rendered, never trusted.** The Markdown renderer shows raw HTML
  as text, allows only `http`, `https` and `mailto` links, turns images into
  links, and runs KaTeX with `trust: false`.

---

## Tests

```bash
cd apps/app
bun run test        # unit tests (bun test): API client, SSE parser, BFF proxy, chat store, renderer…
bun run typecheck
bun run lint
```

**End-to-end** (Playwright, Chromium): a production build of this app on :3100
against a **local** API on :4100 with the fake LLM, reading codes from Mailpit.
It never runs against a remote API — the setup refuses any non-loopback address.

```bash
cd apps/app
bunx playwright install chromium    # once
bun run test:e2e
```

The suite reuses an API already running on :4100, or starts one from this
repository's `backend/` (it needs `backend/.venv`; see
`apps/app/playwright.config.ts` for the environment it sets). Test accounts are
`e2e-…@example.com` and delete themselves.

---

## Building next to a running server

`next build` rewrites `.next` in place, which breaks a `next start` serving from
the same directory. To check that a change builds without touching it:

```bash
cd apps/app
NEXT_DIST_DIR=.next-verify bun run build
```

---

## What you must not break

- **No token in the browser.** Session tokens stay in the httpOnly cookie and
  the BFF. Do not add an endpoint or a hook that hands one to page code.
- **The BFF is an allowlist.** Add a route to `lib/api/routes.ts` only if it is
  in the backend's contract; `routes.test.ts` checks that against
  `docs/openapi.json` at the repository root.
- **Never send history, never re-send a message.** A failed or cut-off stream
  is shown as failed and re-read; generating again is the user's choice
  (Regenerate).
- **No raw HTML in replies.** Do not add `rehype-raw` or loosen the sanitise
  schema without a security review.
- **Keep `id="main"` and the skip link** on every page, and style through the
  design tokens in `packages/ui/src/globals.css` rather than raw colours.
