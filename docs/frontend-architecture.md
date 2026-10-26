# Frontend architecture

> Verified at commit `0e33ec0` (2026-10-26) against `frontend/apps/app/src/` (pages, layouts, `features/`, `lib/`),
> `frontend/packages/ui/`, `next.config.mjs` and the Playwright configs. Agents working in `frontend/` also get
> [`frontend/CLAUDE.md`](../frontend/CLAUDE.md); this page is the human-oriented map.

The web app is **Next.js 15 (App Router) with React 19 and TypeScript**, in a Bun + Turborepo workspace in
`frontend/`:
- `apps/app` is the application;
- `packages/ui` is the design system (Tailwind 3.4 tokens and Radix components);
- `tooling/typescript` holds shared TypeScript configs.

The app is the API's **first client**: durable data and rules live in the API, and the browser keeps UI state only.

## Contents

- [The three rules](#the-three-rules)
- [Pages and layouts](#pages-and-layouts)
- [Sign-in and the session](#sign-in-and-the-session)
- [Talking to the API](#talking-to-the-api)
- [State](#state)
- [The chat screen](#the-chat-screen)
- [Rendering replies](#rendering-replies)
- [Settings](#settings)
- [Learning, progress, study time and the bell](#learning-progress-study-time-and-the-bell)
- [Voice mode](#voice-mode)
- [Styling, motion and accessibility](#styling-motion-and-accessibility)
- [Errors and loading](#errors-and-loading)
- [Preview UI](#preview-ui)
- [Tests](#tests)
- [Where to find things](#where-to-find-things)

## The three rules

1. **The browser never calls the API.** It calls its own origin, `/api/v1/*`, and the web app's server forwards
   allowlisted routes. Server components call the API directly with `lib/server/backend.ts`.
2. **The browser never holds a session token.** The session lives in an httpOnly cookie, and every `/api/auth/*`
   JSON answer has its `token` removed.
3. **The server owns the data.** The app sends only `{conversationId?, message, attachmentIds?}` for a chat turn,
   never history; settings save as versioned resources; numbers on screen come from the API, and when a number
   can't be read, it isn't shown.

## Pages and layouts

| URL | Route file (`src/app/`) | What it is |
|---|---|---|
| `/login`, `/signup` | `(auth)/login`, `(auth)/signup` | One `AuthForm` with steps: sign in, sign up, code, password, forgot, reset; Google when configured |
| `/` | `(app)/(main)/(chat)/page.tsx` | A new chat |
| `/c/<id>` | `(app)/(main)/(chat)/c/[conversationId]/page.tsx` | An existing chat. Both chat pages render nothing themselves: the `(chat)` layout renders `ChatView`, so a new chat getting its URL never remounts the view or stops its stream |
| `/learning` | `(app)/(main)/learning` | My Learning: today's plan, a practice picker, revisions, mastery, mistakes, recent tests |
| `/study` | `(app)/(main)/study` | Study Activity |
| `/library` | `(app)/(main)/library` | The File Library |
| `/help`, `/about` | `(app)/(main)/help`, `about` | Help and About |
| `/settings`, `/settings/<section>` | `(app)/settings/` | The Settings workspace: 13 sections |
| `/homework`, `/summarizer` | `(app)/(main)/homework`, `summarizer` | **Preview only** (`PREVIEW_FEATURES=1`), otherwise 404 |
| `/unsubscribe` | `unsubscribe/` | Public: an email's unsubscribe link, which acts only when its button is pressed |

**Layouts:**
- `app/layout.tsx`: fonts, viewport, and a pre-paint script that applies the last appearance before the first paint.
- `(app)/layout.tsx`: checks the session with `GET /v1/me`, holds every provider, and mounts the activity and
  study heartbeats, `SessionKeeper` and the navigation guard, once.
- `(app)/(main)/layout.tsx`: the app shell (sidebar and header).
- `(app)/settings/layout.tsx`: the Settings workspace, outside the shell.

`middleware.ts` with `lib/server/gate.ts` only checks that a cookie is present (signed-out visitors go to `/login`,
and `/api` is never redirected). The real check is the layout's `GET /v1/me`.

## Sign-in and the session

- **Better Auth** runs inside the web app's server: `lib/auth/config.ts` (pure `createAuth`, built lazily by
  `server.ts` so `next build` needs no secret), with the route allowlist and token removal in `routes.ts`.
- **Per-account limits:** `guard.ts`, in the database's `auth_attempts`, under an advisory lock.
- **Password hashing:** `password.ts`, argon2id in the API's own format.
- **Notices:** `events.ts` asks the API's `/internal/auth/*` to email codes and security notices.
- **The browser client:** `client.ts`.
- **The cookie:** `__Host-padhai_session` over HTTPS, `padhai_session` on local HTTP. `lib/server/cookies.ts`
  verifies its HMAC before a token goes anywhere.
- **Keeping the session alive:** `SessionKeeper` asks for the session once per page load, so Better Auth extends
  the expiry and the cookie together.
- **An expired session:** a 401 from the API sends the page to `/api/session/expired`, which asks again and clears
  the cookie only when the session really is over. An unreachable API shows `ServiceUnavailable`, never a
  sign-out.

## Talking to the API

| Module | Role |
|---|---|
| `lib/api/routes.ts` | **The allowlist**: one table read by the typed client, the proxy, and the contract test (`routes.test.ts` checks every entry against `docs/openapi.json`). Adding an endpoint for the browser means adding it here |
| `lib/api/http.ts` | `callRoute(key, …)`: the only way the browser calls the API, same-origin, through `/api` |
| `lib/api/sse.ts` | A WHATWG-style SSE parser: LF, CRLF or CR line endings, split chunks, multi-line data |
| `lib/api/chat.ts` | Sending a message and reading the stream: outcomes `done`, `error`, `interrupted`, `aborted` |
| `lib/api/errors.ts` | Every API error code mapped to the app's own words and one recovery action. The API's message text is never shown |
| `lib/api/contract.gen.ts` | Enums and limits generated from `docs/openapi.json` (`bun run contract`), so a new API value is a compile error until it is named |
| `lib/server/proxy-core.ts` | The proxy's logic: allowlist, `Origin`, JSON only, 64 KB, upload classes (photo, files, voice), cookie handling, unbuffered SSE, aborting upstream when the browser leaves |
| `lib/server/backend.ts`, `session.ts` | Server components' direct reads (`/v1/me`, `/v1/greetings`) |

Server-only code is split into pure, unit-tested cores (`proxy-core.ts`, `gate.ts`, `cookies.ts`,
`public-origin.ts`, `expired.ts`) and thin `server-only` modules, because `server-only` throws outside Next.

## State

| Store | Where | Holds |
|---|---|---|
| Chat store | `features/chat/chat-store.ts` | Every open conversation, keyed by id (`draft:n` until `meta`). It owns the streams, not the pages, so switching chats never stops a reply. Each message subscribes to itself, and tokens are batched (about 50 ms), so a token re-renders only the streaming message |
| Conversations store | `features/conversations/conversations-store.ts` | The sidebar list, newest first, paged by cursor |
| Attachment store | `features/files/attachment-store.ts` | A draft's files on their way to ready, so uploads survive navigation |
| Streak store | `features/streak/streak-store.ts` | The server's streak, refetched after replies and practice answers, when the tab is shown again, and at India midnight |
| Study store | `features/study/study-store.ts` | This tab's view of the study session; every second shown comes from the server |
| AutoSaver | `features/settings/auto-saver.ts` | Toggle-style settings saved as they change: batched, rolled back on failure, rebased once on 409 |

All the stores are read through `useSyncExternalStore`. Drafts sit in a silent map, so typing doesn't notify
anyone. Browser storage holds UI state only: where Close goes, the last appearance, and the theme (next-themes).

## The chat screen

- **Composer:** `features/chat/composer.tsx`.
  - Enter sends and Shift+Enter makes a new line; input-method composition is respected (`keyboard.ts`).
  - Dictation uses the browser's own speech recognition (`dictation.ts`): the text is appended to the draft, never
    sent by itself.
  - Attachments wait until ready.
- **Messages:** `message-list.tsx` (stick-to-bottom scrolling that respects reduced motion) and `message.tsx`.
  - Replies are revealed at an even pace (`smooth-text.ts`).
  - A screen reader hears the moments that matter, not every token (`announcer.tsx`).
- **Stop** sends `POST cancel`, reads until `done` (at most about 3 s), then aborts.
- **Never re-send:** after a cut-off stream, the app re-reads the conversation.
- **Errors** show the app's own text and one action per code (`error-message.tsx`).

## Rendering replies

`features/markdown/message-content.tsx` runs this pipeline:
- react-markdown with GFM and maths;
- **rehype-sanitize first**, then KaTeX (`trust: false`, with mhchem) and syntax highlighting.

Safety rules:
- raw HTML is shown as text;
- links are limited to `http`, `https` and `mailto`;
- images become captioned placeholders and are never loaded.

The tutor's own syntax is parsed by `remark-tutor.ts`:
- study cards (`:::note`, `:::definition`, …);
- file previews (`::file{ref=F1}`, `::pdf{…}`);
- citation chips (`[1]`, `[F1]`) with a Sources list.

Fenced `mermaid`, `chart`, `graph`, `diagram`, `flashcards`, `mcq`, `quiz` and `fill-blank` blocks are drawn by
lazy widgets (`rich-block.tsx`), each with its own error boundary. Practice cards draw only the server's record of
the test and post answers to `POST /v1/messages/{id}/assessment-responses`; nothing is scored in the browser.

The renderer is a separate lazy chunk (`lazy-message-content.tsx`), preloaded when the chat mounts.

## Settings

`/settings/<section>` is its own workspace: a panel (brand, Close, search, sections), a top bar and the section.
- **Small screens:** below 768 px, `/settings` is the list and each section is its own screen.
- **Larger screens:** the panel sits beside the section.

**The 13 sections** (`features/settings/sections.ts`): Profile, Academic Profile, Learning Goals, Learning
Preferences, AI Tutor, Subjects & Study, Progress & Goals, Study Tracking, Learning & Streak, Notifications,
Appearance & Accessibility, Privacy & Security, and Help & Support.

**How they save:**
- Each section is one or more versioned API resources (`{version, set, reset}`).
- Toggles save as they change.
- Forms save on submit, keep the edit on a conflict, and warn before leaving with unsaved changes. One guard,
  `features/navigation/navigation-guard.ts`, covers links, Close, search, sign-out, reload and Back/Forward.

## Learning, progress, study time and the bell

- **My Learning** (`features/my-learning/`): every panel loads, fails ("Try again") and retries on its own. Its
  buttons never send anything: they put a request into a new chat's draft (`ask-in-chat.ts`).
- **Active time** (`features/progress/use-activity-heartbeat.ts`): one report a minute while PadhAI is open and
  used (`lib/activity.ts` has the rule).
- **Study time** (`features/study/`): sessions the student starts; beats every 30 s per tab; the server credits
  every second.
- **Streak and bell:**
  - the header shows the streak badge (hidden by an Appearance setting), the India day countdown and the bell;
  - the bell is fetched on mount, on focus and after learning events, with no polling;
  - opening it marks nothing read.

## Voice mode

`features/voice/`:
- `availability.ts` asks `GET /v1/voice` once per page;
- `voice-mode.tsx` is the screen over the chat: only the face, a state line, any notice, and three controls (back
  to the chat, the microphone, end). What was said is in the chat underneath, as ordinary messages;
- `vad.ts` detects speech from the microphone level, and a 0.6 s pause (`END_MS`) ends the question;
- `voice-session.ts` and `use-voice-session.ts` run the session, and play a soft chime when a question is sent;
- `speech-text.ts` and `latex.ts` turn a reply into spoken text, with maths read aloud;
- `scheduler.ts` plays the audio in order, with the next sentence prepared ahead;
- `tutor-face.tsx` draws the face (listening, thinking, speaking, plus the `expression` manner);
- `audio-unlock.ts` lets Safari play sound.

The server side is in [ai-architecture.md, "Voice mode"](ai-architecture.md#voice-mode).

## Styling, motion and accessibility

- **Tokens:** `packages/ui/src/globals.css` (contrast-checked, light and dark) through Tailwind
  (`packages/ui/tailwind.config.ts`). Use tokens, never raw colours.
- **Type:** Noto Sans (self-hosted, `src/lib/fonts.ts`; Devanagari loads only when shown) on one rem scale. Body
  `text-base` is 16 px; the reading width is `max-w-prose`.
- **Appearance settings** are applied as `data-*` attributes on `<html>` (`lib/appearance.ts`), cached for the
  pre-paint script, and reconciled from the API. next-themes is the one theme system.
- **Motion:**
  - the tokens are `--motion-fast`, `--motion-base` and `--motion-slow`, with standard, enter and exit easing;
  - only transform and opacity move;
  - reduced motion (from the device or Settings) is global, and `e2e/motion.e2e.ts` enforces it.
- **Touch screens:** text fields are at least 16 px, so iOS doesn't zoom in, and actions that a pointer reveals on
  hover are always visible.
- **Accessibility:** the end-to-end tests run axe. Focus moves only when a whole view is replaced
  (`features/navigation/route-focus.ts`).

## Errors and loading

| Situation | What renders |
|---|---|
| A page failed | `app/error.tsx`: a way forward, with no stack or code |
| The root layout failed | `app/global-error.tsx`, which replaces the whole document |
| An unknown URL | `app/not-found.tsx` |
| A settings section failed or is loading | `settings/[section]/error.tsx` or `loading.tsx`, inside the workspace, so the panel and Close still work |
| The API is unreachable | `ServiceUnavailable`, never a sign-out |
| A panel's data failed | "Try again" in that panel; never made-up zeros |

## Preview UI

The Homework Helper and Summarizer pages render only with `PREVIEW_FEATURES=1`, a server variable read per request
(`lib/preview.ts`), never set in production. Their sample data lives only in `features/learning-hub/demo-data.ts`.
`e2e/gated.e2e.ts` and `e2e/preview.e2e.ts` check both states.

## Tests

| Kind | Command (in `frontend/`) | What |
|---|---|---|
| Typecheck | `bun run typecheck` | `tsc --noEmit` for the app and `packages/ui` |
| Lint | `bun run lint` | Biome. `packages/ui` also enforces formatting with `biome check .` |
| Unit | `bun run test` (or, in `apps/app`, `bun test ./src`) | Pure logic, including the contract tests `routes.test.ts` and `contract.gen.test.ts` |
| End-to-end | in `apps/app`: `bun run test:e2e` | 25 Playwright specs with axe, against a production build on :3100 and a **local** API on :4100 with the fake LLM ([testing.md](testing.md)) |
| Production smoke | from the repository root: `bun run smoke` | The live site as the QA account ([deployment.md](deployment.md)) |

**Build:**
- `bun run build` (Next production build); `NEXT_DIST_DIR=.next-verify bun run build` checks a build without
  touching `.next`.
- `next build` may rewrite `apps/app/tsconfig.json`. Revert that file, never commit it.
- Open `http://localhost:3000`, not `127.0.0.1`: the session cookie is per host name.

## Where to find things

| You want to change… | Start here |
|---|---|
| What a page shows | `src/app/<route>/page.tsx` and the matching `src/features/<area>/` |
| How a reply looks | `src/features/markdown/` |
| The chat's behaviour | `src/features/chat/chat-store.ts`, `chat-view.tsx`, `composer.tsx` |
| Which API routes the browser may use | `src/lib/api/routes.ts` (then `bun run contract`) |
| Sign-in | `src/lib/auth/` and `src/components/auth-form.tsx` |
| Colours, type, motion | `frontend/packages/ui/src/globals.css`, `packages/ui/tailwind.config.ts` |
| Security headers or CSP | `frontend/apps/app/next.config.mjs` |

A one-line description of every file is in [codebase-map.md](codebase-map.md).
