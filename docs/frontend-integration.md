# Integrating a web app (for the frontend repository)

The frontend lives in a separate repository. This is what it needs from this API; the
full contract is [api-contract.md](api-contract.md) / [openapi.json](openapi.json).

## 1. Call the API only from the web app's server

The API binds to `127.0.0.1:4000` (development) or `127.0.0.1:4100` (production, set through `API_BASE_URL`) and has no public hostname. The web app exposes its own
same-origin routes (for example `/api/v1/*`) that forward to `API_BASE_URL`:

- Read the session token from an **httpOnly, Secure, SameSite=Lax** cookie and send it as
  `Authorization: Bearer <token>`. The browser never sees the token.
- Forward `X-Request-ID` (generate one if absent) and set `X-Forwarded-For` to the client IP
  (the API trusts it when `TRUST_FORWARDED_FOR=true`).
- Reject cross-site mutations: accept JSON only and check the `Origin` header on POST/PATCH/PUT/DELETE.
- Pass SSE responses through **unbuffered** (`new Response(upstream.body)`), and pass the
  browser's abort signal to the upstream fetch.

## 2. Sessions

| After | Do |
|---|---|
| `verify-email`, `login`, `password/reset` → `{user, session:{token, expiresAt}}` | set the cookie from `session.token` (Max-Age from `expiresAt`), strip the token from the body you return to the browser |
| `logout`, `DELETE /v1/me`, any 401 from the API | clear the cookie and send the user to sign-in |

Sign-up flow: `signup` (202) → user types the 6-digit code from email → `verify-email`.
Unverified login returns 403 `email_not_verified` → offer `resend-code` and the code form.
Forgot password: `password/forgot` (202) → code + new password → `password/reset`.

## 3. Chat screen

- **New chat:** don't create anything up front. Send the first message to `POST /v1/chat/stream`
  without `conversationId`; the `meta` event returns the new conversation (id + title). Add it to the
  sidebar and navigate to it.
- **Existing chat:** `GET /v1/conversations/{id}/messages` (oldest first; `nextCursor` loads older),
  then send with `conversationId`.
- **Streaming:** parse SSE frames (`event:` / `data:` lines, frames separated by a blank line;
  ignore lines starting with `:`). Show `meta.userMessage` immediately, append `token.text` to the
  reply, and replace it with `done.message` at the end (it is authoritative). On `error`, show
  `message` (safe for users) and, if `retryable`, a retry button that calls regenerate.
- **Stop:** `POST /v1/messages/{assistantMessageId}/cancel` (from `meta`), then abort the fetch.
- **Regenerate** (last reply only): `POST /v1/conversations/{id}/regenerate/stream`; drop the message
  whose id is `meta.replacesMessageId`.
- **Copy:** copy `message.content` (raw Markdown).
- **Feedback:** `PUT /v1/messages/{id}/feedback` with `up`/`down`; `DELETE` to clear.
- **Sidebar:** `GET /v1/conversations` (cursor pagination), rename with `PATCH`, delete with `DELETE`.
- **409 `conflict`** on send: a reply is still generating in that conversation (e.g. another tab).
- **429 `rate_limited`**: show the message; the user may retry later.

## 4. Rendering

`content` is raw Markdown exactly as the model produced it: headings, lists, links, emphasis,
blockquotes, fenced code blocks with language tags, GFM tables and LaTeX (`$...$`, `$$...$$`).
Render it with a sanitising Markdown renderer (for example react-markdown + remark-gfm +
remark-math + rehype-katex + rehype-sanitize) and keep the renderer's component map extensible so
future content types (citations, diagrams, chemistry) can be added without rewriting it.

## 5. Things the frontend must not do

- Send `userId`, history or conversation state (the API rejects unknown fields).
- Write messages anywhere; the API persists both sides of every turn.
- Call the API from the browser, or store the session token in `localStorage`.
