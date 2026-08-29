# The consultation API contract

> **CHANGED — 2026-08-29.** The backend is now a thin proxy in front of
> GraphRAG. There is no local model, no local knowledge base, and no
> server-side conversation state. This is a coordinated two-repo change: the
> frontend needs updating alongside it, not after.
>
> **`POST /api/upload` is back — 2026-08-29, restored in a new, stateless
> shape.** It extracts text and returns it; it does not store or index
> anything. See its own section below — the response shape changed, and
> `POST /api/consult` gained a `documents` field to go with it.
>
> **`documents` is a LIST, not a single string — 2026-08-29 (same day,
> corrected).** It first shipped as one `documentText` string, which forced
> the frontend to hand-join multiple attachments and let the first one
> exhaust the whole truncation budget, silently starving every other
> attached file. `documentText` never reached production and is gone — see
> "Several attachments" below.

Everything a frontend needs. **You do not need the Python source, a GraphRAG key,
Convex credentials or any backend `.env` to build against this.**

The Python side is the source of truth: `backend-python/src/graphrag.py` and
`backend-python/server.py`. There is no `schema.py` any more — the response
shape below is now just the JSON `server.py` builds by hand.

---

## Where requests go

The browser talks only to **its own origin**. It never holds an API key and never
calls the Python backend directly.

```
browser ──POST /api/consult────────► Next.js route ──► Python backend :4000
        ──POST /api/consult/stream─►               ──►
        ──POST /api/upload─────────►               ──►
```

This is not a style choice. `@convex-dev/auth` refreshes a token only when
Convex's own client hits an auth error, so a hand-written `fetch` from the page to
another host can carry a token that expired an hour ago and nothing ever corrects
it. That produced a real, reported "AI service unavailable (401)". The Next.js
middleware refreshes the auth cookie on `/api/*`, so these routes always read a
live token — and a browser that holds no token cannot hold a stale one.

Auth is a cookie, handled for you. There is nothing to attach.

---

## `POST /api/consult`

One turn of a consultation.

### Request

```jsonc
{
  "bot_id": "ayurveda",        // which bot. Unknown -> 400. See "Bots" below.
  "conversationId": "abc123",  // groups turns; the same id `?c=` reopens
  "problem": "mujhe gas ho rahi hai",  // what they typed, OUTSIDE a consultation
  "freeText": "aaj se",        // what they typed DURING one — see below
  "context": { /* echoed back verbatim, opaque apart from `phase` */ },
  "profile": "",                // optional free-text user profile
  "documents": []               // optional — see "Several attachments" below
}
```

**`problem` and `freeText` are now equivalent.** Either is read as "what the
user just said"; send whichever you have. There is no `phase` to branch on any
more.

#### Several attachments

`documents` is how uploaded reports reach a question:

```jsonc
"documents": [
  { "filename": "blood-test.pdf", "text": "…the text /api/upload returned…" },
  { "filename": "prescription.pdf", "text": "…" }
]
```

The backend stores nothing, so YOU hold each `text` from its own
`/api/upload` call and resend the ones relevant to this turn — there is no
"currently attached" state on the backend to remember them for you.

**Send a LIST, one object per attachment — do not join them into one string
yourself.** This is deliberate, not a style preference: the backend owns
both the `--- filename ---` labelling and the per-file truncation budget, so
it can split that budget fairly across however many files are attached
instead of one large file exhausting it before a second file is ever
considered. A malformed `documents` (not a list, or entries missing `text`)
is silently ignored — the turn still answers the typed question, just
without any attachment.

**The shared budget, and what happens past it.** `documentTruncated` in the
response is `true` if EITHER: any single file's content had to be cut to
fit its share of the budget, OR more than 5 files were attached (files
beyond the 5th are dropped entirely, not just shrunk). With more files
attached, each one's slice gets smaller — there is no retrieval over any
document's content, just a shrinking excerpt, so a long report's later
pages (or a 6th file) are not seen by every question asked.

**The backend is stateless, and now genuinely so — `context` is not read.**
Send whatever you like in it; it is echoed back unchanged and carries no
meaning server-side. There is no conversation memory: every message is
answered on its own, with nothing carried over from earlier turns. A
follow-up like "explain that in English" is sent to GraphRAG exactly as
typed, with no prior answer attached, so it may not resolve the way it used
to.

### Response

```jsonc
{
  "kind": "chat" | "answer" | "escalation" | "error" | "intake",
  "condition": "Gas & Bloating",
  "message": "",
  "answer": "…",               // what to render
  "intake": null,              // always null — see "Retired" below
  "context": { /* send this back next turn */ },
  "sources": [
    { "section": "Trusted Ayurveda / Yoga knowledge",
      "source": "knowledge:gas-bloating.md",
      "score": 0.59 }
  ],
  "documentTruncated": false   // true if any attached document had to be cut (or dropped) to fit GraphRAG's query budget
}
```

| `kind` | What it is | How to render |
|---|---|---|
| `chat` | a supportive-care reply for a serious diagnosed condition (cancer, dialysis, TB, ...) — caught locally, before GraphRAG | a normal bubble |
| `answer` | GraphRAG's own reply, verbatim | bubble + sources |
| `escalation` | a red flag was detected locally; see a doctor | prominent, not a normal bubble |
| `error` | GraphRAG could not be reached, or is not configured | a warning, not a chat bubble |
| `intake` | **retired** | never sent; treat as `chat` if you see it |

`condition` and `message` are always `""` now — nothing classifies the
complaint or writes a separate message any more. Render `answer`.

### Sources

Only one namespace is possible now:

| Prefix | Meaning |
|---|---|
| `graphrag:` | GraphRAG's own citation for its answer |

`knowledge:`, `report:` and `memory:` are gone along with the local knowledge
base, the report-upload feature, and long-term memory. `sources` is often `[]`
— GraphRAG does not always cite.

### Errors

| Status | Meaning | `reason` |
|---|---|---|
| 400 | malformed body, or an unknown `bot_id` | — |
| 401 | session expired or ended | `stale_token` \| `signed_out` |
| 502 | the backend is unreachable or replied unusably | — |
| 503 | the service is not configured | — |

`signed_out` means both auth cookies are gone — send them to sign in. Anything
else 401 means a reload is enough. The distinction matters: telling someone to
refresh a dead session just lands them on the login page without explaining why.

---

## `POST /api/consult/stream`

The same turn, as Server-Sent Events. Identical request body.

```
event: token      data: {"text":"…"}          zero or more, as it is written
event: done       data: {…ConsultResult}      exactly one, and it is authoritative
event: error      data: "…"
```

**Tokens are a preview; `done` is the truth.** A client that ignored every token
would still end up with exactly the right transcript. Store `done`, never the
accumulated tokens — tokens can stop arriving and the stored conversation must not
depend on having received them all.

`done`'s payload carries `documentTruncated` too, same meaning as in
`POST /api/consult` above.

Fall back to `POST /api/consult` if the stream cannot be opened or ends without a
`done`.

---

## `POST /api/upload`

`multipart/form-data`, one `file` field. Do **not** set `Content-Type` yourself —
the browser must set it so it can add the multipart boundary.

```jsonc
// /api/upload    -> { "filename": "report.pdf", "chars": 4821, "text": "…", "truncated": false }
```

**Nothing is stored.** There is no per-user document store any more — the
backend extracts the text and hands it straight back in this response, then
forgets the file completely. This is deliberate: GraphRAG's own document
upload API stores files in a corpus shared across the whole project, not
privately per user, which would leak one person's report into another
person's ordinary answers — see `docs/graphrag-api.md` for that API, and do
not route uploads through it.

**Hold `filename` and `text` client-side and send them back as one entry in
`documents` on a later `POST /api/consult` call to ask about it** — see
"Several attachments" above. There is no session that remembers an
"attached" file for you.

`chars: 0` / `text: ""` means nothing could be read from the file — most
often a scanned PDF, which is rasterised and OCR'd rather than parsed.
`truncated: true` means the extracted text was longer than the backend's own
per-file cap and was cut before being returned (independent of, and
unrelated to, `documentTruncated` on `/api/consult` — that one is about how
much of `documents` made it into one GraphRAG query, not how much
`/api/upload` extracted in the first place).

**Known limitation:** OCR asks for English *and* Hindi, but the production
host may only have the English language pack installed. If so, a scanned
Devanagari report returns `200` with plausible English text and silently
drops the Hindi — there is no error to catch. Worth verifying before relying
on this for a Hindi-script report.

---

## Bots

One backend serves several frontends. `bot_id` selects the knowledge base.

- Registered ids live in `backend-python/src/bots/registry.py`. Today: `ayurveda`.
- **An unknown `bot_id` is a 400** — never a silent fallback to another bot's
  corpus.
- Omitting it currently defaults to `ayurveda` and logs a warning. That is
  transitional, for browser tabs open across a deploy; it will become a 400.
- Set it with `NEXT_PUBLIC_BOT_ID`.

---

## Building without a backend

```bash
NEXT_PUBLIC_CONSULT_PROVIDER=mock
```

Returns canned `ConsultResult`s covering the states worth designing against — a
greeting, a gathering question, and a final plan with two citations. No Python,
no Convex, no keys. Switching to the real backend is that one env var; no UI code
changes, which is the point of the seam existing.

| Value | Talks to |
|---|---|
| `local` *(default)* | the Python backend |
| `mock` | canned data, in-process |
| `central` | an external service. Off, and unrelated to the Python backend despite the name. |

---

## Retired

`kind: "intake"` and the `intake` object are no longer produced. The consultation
used to answer a complaint with a card questionnaire and then a second card
screen asking which parts of the plan you wanted; both are gone and the flow is
a conversation. The fields remain in the schema so conversations saved before the
change still load. `ConsultPhase` keeps `collecting` and `choosing` for the same
reason — the backend maps them to `gathering` on load.
