# API contract (v1)

Machine-readable: [openapi.json](openapi.json) (generated from the code; a test fails if it drifts).
Base URL: the API listens on `127.0.0.1:4000` in development and `127.0.0.1:4100` in production, and is called by the web app's server, not by browsers.

## Conventions

- JSON bodies, **camelCase** fields. Unknown request fields are rejected (422).
- Auth: `Authorization: Bearer <session token>` on everything except `/health`, `/ready` and the
  sign-up/login/verify/reset endpoints.
- Optional `X-Request-ID` (`[A-Za-z0-9._-]{1,64}`); echoed back, otherwise generated.
- Request bodies are limited to 64 KB (413 `payload_too_large`), except the profile photo upload
  (`PUT /v1/me/avatar`: a raw image of at most `AVATAR_MAX_BYTES`, 5 MB by default).
- Resources owned by another user return **404**, exactly like missing ones.
- Errors: `{"error": {"code": "...", "message": "...", "requestId": "..."}}`, plus `fields` on 422
  and `current` on 409 `version_conflict`.

| HTTP | code | meaning |
|---|---|---|
| 401 | `unauthorized` | missing/invalid/expired session |
| 401 | `invalid_credentials` | wrong email or password |
| 403 | `email_not_verified` | log in after verifying the email code |
| 400 | `invalid_code` | wrong, expired or over-used email code |
| 404 | `not_found` | missing, or not yours |
| 409 | `conflict` | a reply is already generating in this conversation; nothing to regenerate |
| 409 | `version_conflict` | a versioned edit named an old `version`; `current` holds the resource as it is now |
| 409 | `current_session` | revoking the session in use (sign out instead) |
| 409 | `email_unavailable` | the new email address was taken before the change was confirmed |
| 413 | `payload_too_large` | body over 64 KB (the photo upload: over its own limit) |
| 415 | `unsupported_media_type` | a photo that is not JPEG, PNG or WebP |
| 400 | `invalid_token` | an unsubscribe link that this server did not sign |
| 429 | `too_many_open_requests` | 30 support requests are still open |
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
| GET | `/v1/auth/sessions` | – | `{items: [{id, current, device, ipMasked, createdAt, lastSeenAt, expiresAt}]}`, most recently used first |
| DELETE | `/v1/auth/sessions/{id}` | – | 204 — signs that device out; 409 `current_session` for your own, 404 if not yours |
| GET | `/v1/me` | – | the user (below) |
| PATCH | `/v1/me/profile` | `{version, set: {displayName?, timezone?}, reset: [...]}` ([versioned edits](#versioned-edits)) | the user |
| PATCH | `/v1/me` | `{displayName}` | the user. **Deprecated**: use `/v1/me/profile`. It moves `profileVersion` on too |
| PUT | `/v1/me/avatar` | the raw image; `Content-Type: image/jpeg\|png\|webp` | the user, with a new `avatar.url` |
| DELETE | `/v1/me/avatar` | – | the user, `avatar: null` (idempotent) |
| GET | `/v1/me/avatar?v=<hash>` | – | `image/webp`, cacheable forever; 404 (never cached) unless `v` is the current photo |
| POST | `/v1/me/email/change` | `{newEmail, password}` | 202 (always, [below](#changing-the-email-address)) |
| POST | `/v1/me/email/confirm` | `{newEmail, code}` | the user, with the new email; other sessions revoked |
| DELETE | `/v1/me` | `{password}` | 204 — deletes the account and all its data |
| GET / PATCH | `/v1/me/appearance` | PATCH [versioned](#versioned-edits): `theme` (system\|light\|dark), `fontSize` (small\|medium\|large\|x_large), `highContrast`, `reduceMotion`, `readingComfort`, `showStreak` | the appearance, the same on every device |
| GET / PATCH | `/v1/me/settings` | PATCH `{preferences: {...}}` (merged; `null` removes a key; ≤ 4 KB) | `{preferences, updatedAt}`. Unused by the web app; appearance is `/v1/me/appearance` |
| GET | `/v1/greetings/current` | – | `{text, weekOf}`: this week's study greeting, the same for every user (404 when none is live; the web app then shows its own fallback). Weeks start Monday in `DEFAULT_TIMEZONE`; retire a greeting from a future Monday, never delete one |

The user: `{id, email, displayName, emailVerified, createdAt, profileVersion, timezone, avatar: {url} | null,
passwordChangedAt}`. `timezone` is an IANA name (`Asia/Kolkata`) or null. `passwordChangedAt` is null
until the password is first changed or reset.

**Signed-in devices** show a label parsed from the user agent ("Chrome on Windows", or "Unknown device")
and the network only (`203.0.113.x`, or an IPv6 /48). The raw IP address and user agent never leave the
server.

**Profile photo.** The server checks that the bytes are the declared type, refuses images over 40
megapixels before decoding them, turns the photo upright, crops it square and stores a new 256 px
WebP (at most 64 KB). Nothing of the original file is kept, including its EXIF data and GPS position.
`avatar.url` contains the photo's hash, so a browser may cache it forever; a replaced or removed
photo gets a new URL, and its old one answers 404. 10 uploads per 15 minutes; a changed photo does
not change `profileVersion`.

### Changing the email address

1. `POST /v1/me/email/change {newEmail, password}` needs the current password (a wrong one counts as
   a failed sign-in). It always answers 202: if the address is free, a code goes to it; if another
   account has it, that address gets a notice instead, so the caller cannot tell which. A new request
   cancels the previous one. 3 requests per 15 minutes; the same address as now is 422.
2. `POST /v1/me/email/confirm {newEmail, code}` with a code sent for **this** account (15 minutes, 5
   attempts). The email changes and counts as verified, every other session is signed out, every
   pending code for the old and the new address is deleted, and the old address is told (with the
   new one masked). If someone registered the address in the meantime: 409 `email_unavailable`.

### Versioned edits

A resource that can be edited from two places at once (two tabs, two devices) has an integer
version, and every edit sends the version it read. One shape, for every such resource:

```json
{"version": 3, "set": {"displayName": "Asha"}, "reset": ["timezone"]}
```

- `set` replaces the listed fields (a list replaces the whole list). A field not listed is unchanged.
- `reset` returns the listed fields to their defaults (empty, or `auto` for a learning preference).
- 422 for an unknown field, `null` inside `set` (use `reset`), a field in both, or a field twice.
- An edit that changes nothing (`set` and `reset` empty) answers 200 and keeps the version.
- Otherwise the version must be current: the edit applies and the version goes up by one, or it is
  refused whole with 409 `version_conflict`, whose `current` is the resource as it is now. The client
  applies its own pending change to `current` and sends it again, or asks the person.
- The answer is always the whole resource.

## Learning: what the tutor knows about the student

| Method | Path | Body | Success |
|---|---|---|---|
| GET | `/v1/catalog/academic` | – | the catalog (below). **No session needed**; `ETag`, `If-None-Match` → 304 |
| GET / PATCH | `/v1/learning/profile` | PATCH [versioned](#versioned-edits) | the learner profile |
| GET / PUT | `/v1/learning/subjects` | PUT `{version, items: [{code, isPriority, needsImprovement}]}` (≤ 15, replaces the list; order = display order) | `{version, items}` |
| GET / PATCH | `/v1/learning/preferences` | PATCH [versioned](#versioned-edits) | the preferences |
| POST | `/v1/learning/tutor-preview` | `{profile?, subjects?, preferences?}`: unsaved edits over what is stored | `{instructions, maxChars}`; nothing is saved; 60 per minute |

- **Learner profile:** `{version, grade, board, boardState, medium, academicYear, mainGoal, targetExam (≤ 80),
  targetScorePercent (0–100), weakTopics (≤ 10 × 60), dailyActiveMinutesGoal (0–720),
  weeklyActiveMinutesGoal (0–5040), preferredStudyTime ("HH:MM"), shortTermGoal (≤ 280), longTermGoal (≤ 280),
  updatedAt}`. Nothing else about the student (no date of birth, gender, phone, school or country) is asked for.
  - `grade`, `board`, `boardState`, `medium` and `academicYear` are catalog codes: an unknown code is 422
    `unknown_code`. `boardState` needs `board: "state"` (422 `requires_state_board`).
  - Free text is stored on one line: runs of whitespace become one space; control characters are removed.
- **Preferences:** `language`, `explanationLevel`, `pace`, `difficulty`, `realWorldExamples`, `visualExplanations`,
  `personality`, `responseLength`, `answerMode`, `stepByStep`, `askBeforeAnswer`, `practiceQuestions`,
  `mistakeCorrection`, `highlightKeyConcepts`. Each is an enum whose default, `auto`, tells the tutor nothing.
- **The catalog** `{version, grades, boards, boardStates, mediums, academicYears, subjects}` lists
  `{code, name, deprecated}`. Codes are permanent. A `deprecated` code is still listed and still accepted while
  a profile keeps it, but can't be chosen anew (422 `deprecated`). Every content change bumps `version` and the
  ETag; clients refetch when the version they hold is older.
- **What the tutor is told** (`app/learning/tutor.py`): the frozen system prompt, plus a block that describes the
  student (catalog names; their own text only in quotes, as information, never as instructions) and lists one fixed
  sentence per preference that isn't `auto`. A student with nothing set, or everything on `auto`, gets exactly the
  tutor everyone got before. The block is capped at `maxChars` (6,000 characters, far above the worst case);
  nothing that identifies the student (name, email, photo) is ever included. The preview returns this block,
  computed by the same function the chat uses.

## Progress: active time in PadhAI

| Method | Path | Body | Success |
|---|---|---|---|
| POST | `/v1/progress/activity` | – | `{credited, date}`: one active minute; 6 reports per minute at most |
| GET | `/v1/progress?days=14` | – (`days` 7–90) | `{timezone, timezoneIsDefault, today, thisWeek, streak, goals, days}` |

- **What is measured:** time active in PadhAI, not study time. A client reports a minute while PadhAI is open and
  visible and the student interacted with it (or a reply was streaming) within the last two minutes. The server
  credits at most one minute per UTC minute per user: other tabs and devices reporting the same minute get
  `credited: false`. A student can inflate their own number; it is never compared with anyone else's.
- **Questions** are counted when the chat accepts a message; regenerating a reply is not a new question.
- **Days** are the student's: their `timezone` (`PATCH /v1/me/profile`), or the server's `DEFAULT_TIMEZONE`
  (`Asia/Kolkata`) until they choose one (`timezoneIsDefault: true`). A change of time zone doesn't rewrite
  past days. Weeks start on Monday.
- **Streak:** a day is active with at least one minute or one question. `currentDays` counts active days up to
  today, or up to yesterday while today has none yet; `longestDays` is the best run so far. Streaks start at
  the release that introduced them (no backfill).
- **Goals** are the daily and weekly active-minute goals from the learner profile; `dailyMet`/`weeklyMet` are
  null without a goal.
- `today`/`days[]`: `{date, activeMinutes, questions}`; `days` lists the last `days` days, oldest first,
  including days without activity.

## Notifications

| Method | Path | Body | Success |
|---|---|---|---|
| GET / PATCH | `/v1/notifications/preferences` | PATCH [versioned](#versioned-edits): `dailyReminder`, `streakWarning`, `weeklySummary`, `securityAlerts` | `{version, dailyReminder, streakWarning, weeklySummary, securityAlerts, remindersNeedTimezone, delivery, updatedAt}`; `delivery` is `paused` while this server sends no notification email to the user (its rollout), `active` otherwise |
| POST | `/v1/notifications/unsubscribe` | `{token}` from an email's link. **No session needed** | `{kind, unsubscribed: true}`; using it again changes nothing |

- **Emails:** all are plain text, and none contains an IP address.
  - Reminders are off until chosen: a daily reminder at the learner profile's `preferredStudyTime` (or 18:00), a
    streak warning at 20:00–22:00, and a weekly summary on Monday mornings. All three need a confirmed `timezone`,
    and each is sent at most once per period.
  - Sign-in alerts (on by default) are sent for a sign-in from a device the account has no live session on.
  - A password change or reset is always reported, and has no unsubscribe link.
- **Delivery:** emails are sent by the jobs worker, only as its rollout allows (`NOTIFICATIONS_MODE`,
  [deployment.md](deployment.md#jobs-worker)), at most once, and never later than a day for alerts.
- **Unsubscribe tokens** name one user and one kind of email, signed with the server's key. They don't expire.

## Support

| Method | Path | Body | Success |
|---|---|---|---|
| POST | `/v1/support/requests` | `{requestId (uuid, chosen by the client), kind: question\|bug\|feedback\|account, subject (≤ 120), message (10–4000), page?}` | 201 `{id, requestId, kind, subject, status, createdAt}`; the same `requestId` again → 200, the same request |

- **Limits:** 5 per hour and 20 per day, and at most 30 open (`too_many_open_requests`).
- **Text:** the subject loses line breaks and control characters; the message keeps line breaks. At most 5 links.
- **Forwarding:** requests are forwarded to the team's address through the outbox, and kept until the account is
  deleted.

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

## Compatibility and versioning

Today the only client (the web app) ships in the same release as the API, so it is always current.
Write every change as if it were not: a native client will keep running older versions for months.

- **Additive within v1:** new endpoints, new optional request fields, new response fields, new enum
  values and new SSE event types. Clients ignore unknown fields and events, and treat an unknown enum
  value as "something newer" rather than an error.
- **Breaking:** removing, renaming or retyping a path, field or enum value; making a field required;
  changing a status code, an error code or what a field means. A breaking change gets a new endpoint
  or a `/v2` path, and the old one keeps working while any supported client still uses it. Never
  repurpose an existing field.
- **The contract file** is regenerated from the code (`bun run contract`); CI fails if it is stale,
  and fails if a route or request field the web app proxies disappears. CI does not detect breaking
  changes yet: read the `docs/openapi.json` diff of every PR with the rules above.
- **Resources, not screens:** responses describe conversations, messages, users and settings, not
  what one page shows. A screen composes resources; an endpoint is not added for one layout.

## Client obligations

What every client (the web app today) must do, so no client re-implements a rule differently:

- Send only `{conversationId?, message}`: never history, never a user id (identity comes from the session).
- Never re-send a message after an interrupted stream. Re-read `GET /v1/conversations/{id}/messages`:
  the server either finished the reply or recorded how it ended.
- Stop a reply with `POST /v1/messages/{id}/cancel`. Closing the stream connection also stops it
  (see "Clients" in [architecture.md](architecture.md)).
- Ignore unknown SSE events and unknown fields.
- Decide on the error `code`; show your own text, with `message` only as a safe fallback.
