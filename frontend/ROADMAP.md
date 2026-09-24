# Roadmap — web app

Deferred work for this repository. The chat API keeps its own roadmap; anything
about models, retrieval, prompts or the database belongs there.

## Waiting on the API

Each needs a change to the API contract first (details in
[`docs/frontend-api.md`](docs/frontend-api.md#known-gaps-in-the-contract)).

- **Show saved 👍/👎 after a reload.** Ratings save, but messages do not carry
  them back. Needs `feedback` on each message in `GET …/messages`.
- **A list of signed-in devices** in Settings, with sign-out per device. Today
  there is only "Sign out other devices". Needs a sessions list endpoint.
- **Search all conversations.** The sidebar filters the chats already loaded.
  Needs a search parameter on `GET /v1/conversations`.

## In this app

- **Bundle size.** The reply renderer (react-markdown, KaTeX, highlight.js,
  ~170 kB gzipped) already loads as its own chunk after the chat is
  interactive. If it grows further, the next step is loading KaTeX and the
  highlighter only for replies that contain maths or code.
- **Next.js 15.** The app is on the latest 14.2 patch. A major upgrade (and
  nonce-based CSP, which would drop `'unsafe-inline'` for scripts) is a separate
  piece of work.
- **Browsers.** The end-to-end suite runs Chromium only. Add WebKit and Firefox
  projects once they are installed on the CI machine.
- **Extension points, not features yet.** The renderer's component map
  (`features/markdown/message-content.tsx`) is where citations, diagrams or other
  rich blocks would plug in.

## Notes

- `bun install` is run with Bun 1.3, but `package.json` still pins
  `packageManager: bun@1.1.26`. Align them when CI is set up.
- Production promotion is done by the backend team; nothing here deploys.
