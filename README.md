# Ayurveda — frontend

The web app for an Ayurveda and Yoga consultation assistant. Next.js 14 (App
Router), React 18, TypeScript, Tailwind 3, shadcn/Radix.

This repository is the **frontend only**. The AI backend — prompts, retrieval,
safety rules — lives elsewhere and is reached over HTTP. You do not need it to
work on this.

---

## Run it

```bash
bun install
cp apps/app/.env.example apps/app/.env.local

cd packages/backend && npx convex dev    # creates YOUR own free Convex project
                                         # and prints NEXT_PUBLIC_CONVEX_URL

bun dev
```

**You do not need the Python backend.** The default
`NEXT_PUBLIC_CONSULT_PROVIDER=mock` serves a canned conversation in-process — a
greeting, a follow-up question, then a full six-section plan — with no API keys
and no network.

**You do need Convex.** It stores login, chat history and settings, and the build
fails without `NEXT_PUBLIC_CONVEX_URL`: it is validated in `src/env.mjs` and the
client is constructed at module load, so there is no blank-value path. Use your
own free project, never production.

```
NEXT_PUBLIC_CONSULT_PROVIDER=mock   # canned data, in-process   (default)
NEXT_PUBLIC_CONSULT_PROVIDER=local  # a real Python backend
```

Switching between them is that one variable. No UI code changes.

---

## The API contract

[`docs/api-contract.md`](docs/api-contract.md) is the interface between this app
and the backend. It is the only thing you should rely on.

The backend publishes what it actually promises to
`apps/app/src/content/consult-contract.json`, and `contract.test.ts` fails if the
TypeScript here stops matching it. If that test goes red, the backend changed —
talk to the backend team rather than editing types to make it pass.

---

## What you must not break

Each of these is load-bearing and each has already caused a real failure. None is
a style choice.

**1. `problem` vs `freeText`.** Send `freeText` when `context.phase` is one of
`CONSULTING`; send `problem` otherwise. Backwards, and every follow-up starts a
brand-new consultation instead of continuing.

**2. `context` must round-trip.** The backend is stateless. Whatever it returns,
send back next turn. Drop it and the assistant greets the user again on every
message.

**3. No cards, chips or option pickers in the chat.** The consultation used to be
a questionnaire; it is a conversation now, deliberately. Do not reintroduce a
button-based flow.

**4. Do not display per-answer citations.** The backend still returns `sources`
and the components still exist, but nothing renders them, by decision. If that
changes, the copy on the landing and login pages has to change with it — those
pages currently make no claim about showing sources, and they must not start
making one that is untrue.

**5. Keep `id="main"`, the skip link, and `lang` driven by the route.** Three
WCAG Level A failures were found by measurement and fixed. The dashboard sidebar
renders fourteen links before `<main>`, so the skip link is not decoration.

**6. Keep `form.w-72` and `w-64` on the auth forms.** The end-to-end tests use
those exact classes to tell the password form from the one-time-code form.

**7. Style through the design tokens** in `packages/ui/src/globals.css`, not raw
colours. Every foreground/background pair in that palette is contrast-checked and
clears 4.65:1. Hardcoded hex values silently break dark mode and accessibility.

---

## The Library

`/library` publishes the curated knowledge notes as public pages. They are read
from `apps/app/src/content/library.json`, which is **generated** in the backend
repository and committed here.

Treat it as read-only: editing it by hand will be overwritten, and the backend's
test fails if it stops matching the source notes. Content changes happen there.

These pages are Hinglish and carry `lang="hi-Latn"`. That is deliberate — it is
romanised Hindi, not English, and mislabelling it makes screen readers pronounce
it as gibberish and search engines rank it for the wrong queries.

---

## Tests

```bash
bun apps/app/src/lib/library.test.ts           # the published notes
bun apps/app/src/lib/consult/client.test.ts    # where requests go, bot_id, mock
bun apps/app/src/lib/consult/contract.test.ts  # TS still matches the backend
bun apps/app/src/lib/consult/central.test.ts   # the alternate provider's reader

cd apps/app && bun run typecheck && bun run lint
```

Browser suites live in the backend repository, because they need a running stack.

---

## Layout

```
apps/app/          the Next.js application
packages/ui/       shared components and the design tokens
packages/backend/  Convex schema and functions
tooling/           shared TypeScript configs
docs/              the API contract
```

---

## What is next

[`ROADMAP.md`](ROADMAP.md) is the deferred work for this repository. The AI
backend keeps its own; anything about retrieval, prompts or safety lives there.

---

## Deploys

Staging is yours. **Production is not** — promoting a build to the live site is
done by the backend team, gated on their regression suite. Merge freely here.
