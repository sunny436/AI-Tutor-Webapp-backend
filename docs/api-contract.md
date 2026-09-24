# API contract (v1)

Machine-readable: [openapi.json](openapi.json) (generated from the code; a test fails if it drifts).
Base URL: the API listens on `127.0.0.1:4000` in development and `127.0.0.1:4100` in production, and is called by the web app's server, not by browsers.

## Conventions

- JSON bodies, **camelCase** fields. Unknown request fields are rejected (422).
- Auth: `Authorization: Bearer <session token>` on everything except `/health`, `/ready` and the
  sign-up/login/verify/reset endpoints.
- Optional `X-Request-ID` (`[A-Za-z0-9._-]{1,64}`); echoed back, otherwise generated.
- Request bodies are limited to 64 KB (413 `payload_too_large`).
- Resources owned by another user return **404**, exactly like missing ones.
- Errors: `{"error": {"code": "...", "message": "...", "requestId": "..."}}` (+ `fields` on 422).

| HTTP | code | meaning |
|---|---|---|
| 401 | `unauthorized` | missing/invalid/expired session |
| 401 | `invalid_credentials` | wrong email or password |
| 403 | `email_not_verified` | log in after verifying the email code |
| 400 | `invalid_code` | wrong, expired or over-used email code |
| 404 | `not_found` | missing, or not yours |
| 409 | `conflict` | a reply is already generating in this conversation; nothing to regenerate |
| 413 | `payload_too_large` | body over 64 KB |
| 422 | `validation_error` | invalid body/query (`fields: [{field, reason}]`, values never echoed) |
| 429 | `rate_limited` | auth throttling or the per-user generation quota |
| 503 | `service_unavailable` | database or email temporarily unavailable |
| 500 | `internal_error` | unexpected; report the `requestId` |

## Auth and account

| Method | Path | Body | Success |
|---|---|---|---|
| POST | `/v1/auth/signup` | `{email, password (8-128), displayName?}` | 202 — a 6-digit code is emailed (always 202) |
| POST | `/v1/auth/verify-email` | `{email, code}` | 200 `{user, session:{token, expiresAt}}` |
| POST | `/v1/auth/login` | `{email, password}` | 200 `{user, session}` |
| POST | `/v1/auth/resend-code` | `{email, purpose: verify_email\|reset_password}` | 202 (always) |
| POST | `/v1/auth/password/forgot` | `{email}` | 202 (always) |
| POST | `/v1/auth/password/reset` | `{email, code, newPassword}` | 200 `{user, session}`; all other sessions revoked |
| POST | `/v1/auth/password/change` | `{currentPassword, newPassword}` | 204; other sessions revoked |
| POST | `/v1/auth/logout` | – | 204 (this session) |
| POST | `/v1/auth/sessions/revoke-others` | – | 204 |
| GET / PATCH | `/v1/me` | PATCH `{displayName}` | `{id, email, displayName, emailVerified, createdAt}` |
| DELETE | `/v1/me` | `{password}` | 204 — deletes the account and all its data |
| GET / PATCH | `/v1/me/settings` | PATCH `{preferences: {...}}` (merged; `null` removes a key; ≤ 4 KB) | `{preferences, updatedAt}` |

## Conversations

| Method | Path | Notes |
|---|---|---|
| GET | `/v1/conversations?limit=30&cursor=` | newest activity first → `{items:[{id,title,createdAt,updatedAt}], nextCursor}` |
| POST | `/v1/conversations` | `{title?}` → 201 (title defaults to "New chat"; retitled from the first message) |
| GET | `/v1/conversations/{id}` | |
| PATCH | `/v1/conversations/{id}` | `{title}` (1-120 chars) — rename |
| DELETE | `/v1/conversations/{id}` | 204; messages and feedback are deleted with it |
| GET | `/v1/conversations/{id}/messages?limit=50&before=` | oldest-first page; `nextCursor` loads older messages |

Message: `{id, conversationId, role: user|assistant, content, status, createdAt, metadata: {model?, errorCode?, finishReason?}}`.
`status`: `complete`, `streaming`, `cancelled` (stopped, partial text kept), `error` (partial text kept).
`content` is stored exactly as produced (Markdown, code fences, tables, `$math$`).

## Chat

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/v1/chat/stream` | `{conversationId?, message (1-16000)}` | `text/event-stream` (below). No `conversationId` → a new conversation |
| POST | `/v1/chat` | same | 200 `{conversation, userMessage, message}`; LLM errors → 502/504/422 with the error envelope |
| POST | `/v1/conversations/{id}/regenerate/stream` | – | SSE; the last reply becomes `superseded` and a new one streams |
| POST | `/v1/messages/{id}/cancel` | – | `{status}` — stops a `streaming` reply (idempotent) |
| PUT | `/v1/messages/{id}/feedback` | `{rating: up\|down, comment?}` | `{messageId, rating, comment}` (assistant messages only; upsert) |
| GET / DELETE | `/v1/messages/{id}/feedback` | – | read / remove your feedback |

### Server-Sent Events

```
: open
event: meta
data: {"conversationId","conversation":{...},"userMessage":{...}|null,"assistantMessageId","replacesMessageId"|null}

event: token
data: {"text":"partial text"}            (repeated)

: keepalive                              (every 15 s without output)

event: done
data: {"message":{...final assistant message...},"conversation":{...}}
  — or —
event: error
data: {"code":"llm_unavailable|llm_timeout|llm_bad_request|service_unavailable|internal_error",
       "message":"safe, user-facing text","retryable":true|false,"messageId","requestId"}
```

- Concatenated `token.text` equals `done.message.content`.
- Stopping: call `POST /v1/messages/{assistantMessageId}/cancel`; the stream then ends with `done`
  whose message has `status: "cancelled"`. Closing the connection also stops the reply (same result).
- Unknown event types may be added later (e.g. citations) and must be ignored by clients.

## Health

`GET /health` → `{"status":"ok"}` · `GET /ready` → `{"status","database"}` (503 when the database is down).
Interactive docs at `/docs` exist only when `APP_ENV=development`.
