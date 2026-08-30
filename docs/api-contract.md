# The consultation API contract

> **REVERSED — 2026-08-30.** The 2026-08-29 "thin proxy" design (GraphRAG
> writes the answer, backend is stateless, no memory) has been undone by
> explicit decision. The backend is a real orchestrator again: it runs
> intent routing, a prose intake, retrieval (GraphRAG + local knowledge +
> memory + uploaded reports), and a LOCAL LLM writes every final answer.
> GraphRAG is retrieval-only now (`/v1/search`) — it never writes prose.
>
> **What this means for the frontend, concretely:**
> - `context` is meaningful again. Send back exactly what you were given —
>   `phase` now drives real server-side behavior (see `problem` vs
>   `freeText` below), not an opaque echo.
> - `documents: [{filename, text}]` on `/api/consult` still works exactly as
>   it did yesterday (folded into the question), but it is now a
>   **supplement, not the only path** — an upload is also indexed
>   server-side, so a later question can retrieve just the relevant part of
>   a long report even if you stop sending this field. No frontend change is
>   required to keep working; sending it less is a later optimization, not a
>   requirement.
> - `POST /api/upload`'s response gained `indexed` back (chunk count) beside
>   yesterday's `text`/`truncated` — both are present, nothing removed.
> - `sources` can carry `graphrag:`, `knowledge:`, `report:` and `memory:`
>   prefixes again — see the table below.
> - `documentTruncated` (yesterday's field, about the per-query character
>   budget) is gone. It described a mechanism (folding raw text into one
>   GraphRAG query) that this reversal replaces with real retrieval.

Everything a frontend needs. **You do not need the Python source, a GraphRAG key,
Convex credentials or any backend `.env` to build against this.**

The Python side is the source of truth: `backend-python/src/consult/schema.py`.
`apps/app/src/lib/consult/types.ts` mirrors it by hand — if the two disagree,
Python wins and the TypeScript is the bug.

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

**`problem` vs `freeText` matters again.** Send `freeText` when
`context.phase` is one of `CONSULTING` (`gathering`, and the legacy
`collecting` / `choosing`, mapped on load); send `problem` otherwise.
Getting it backwards makes every follow-up look like a brand-new complaint.
The backend tolerates either field regardless of phase (it will not crash or
silently drop your message), but routing works correctly only when this
convention is followed — a lenient parser is not the same as a stateless one.

#### Several attachments

`documents` is how uploaded reports reach a question:

```jsonc
"documents": [
  { "filename": "blood-test.pdf", "text": "…the text /api/upload returned…" },
  { "filename": "prescription.pdf", "text": "…" }
]
```

This is still supported and still folded into the question exactly as
before. It is no longer the only way a report reaches an answer: `/api/upload`
now also indexes the document (per-user, embedded, isolated by a verified
`user_id` — never a client-supplied one), so `run_consult_turn`'s own
retrieval pipeline pulls the relevant chunk automatically on a later
question, whether or not you resend this field.

**The backend is stateful again — `context` carries real conversation
state.** Resend exactly what the previous response gave you. There IS
conversation memory now: earlier turns in this session (`context.chat_history`)
and, separately, earlier CONSULTATIONS by this signed-in user (Convex-backed,
see "Memory" below) both feed into the answer.

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
  ]
}
```

| `kind` | What it is | How to render |
|---|---|---|
| `chat` | a conversational reply, or a gathering question | a normal bubble |
| `answer` | the final plan, six sections in markdown | bubble + sources |
| `escalation` | a red flag was detected; see a doctor | prominent, not a normal bubble |
| `error` | the assistant could not run (quota, outage) | a warning, not a chat bubble |
| `intake` | **retired** | never sent; treat as `chat` if you see it |

### Sources

`source` is namespaced, and the namespaces mean different things. Do not flatten
them into one count — "based on 3 Ayurveda notes" is false if one of them is the
reader's own blood test.

| Prefix | Meaning |
|---|---|
| `knowledge:` | the shared curated Ayurveda corpus (local fallback) |
| `report:` | a document THIS user uploaded, retrieved by relevance |
| `graphrag:` | GraphRAG's own retrieved passage or extracted relationship |
| `memory:` | something they said in an earlier consultation |

Deduplicate by file: retrieval returns one entry per *chunk*, so one note can
appear four times.

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

Fall back to `POST /api/consult` if the stream cannot be opened or ends without a
`done`.

---

## `POST /api/upload`

`multipart/form-data`, one `file` field. Do **not** set `Content-Type` yourself —
the browser must set it so it can add the multipart boundary.

```jsonc
// /api/upload -> { "filename": "report.pdf", "chars": 4821, "text": "…", "truncated": false, "indexed": 12 }
```

**Extraction and indexing happen in the same request.** `indexed` is the
number of chunks embedded and stored, scoped to the verified signed-in
caller — an anonymous upload still gets `text` back (still useful for the
`documents` field above) but `indexed` stays `0`, since there is no user to
scope storage to.

`chars: 0` / `text: ""` means nothing could be read from the file - most
often a scanned PDF, which is rasterised and OCR'd rather than parsed.
`truncated: true` bounds only what round-trips in THIS response
(40,000 chars); indexing always uses the full extracted text regardless.

An indexing failure (bad or exhausted OpenRouter key, timeout) does not fail
the request — extraction already succeeded, so `text` still comes back;
`indexed` is `0` and the failure is logged server-side, not surfaced as an
error to the caller.

---

## Memory

Two distinct things, kept separate:

- **Conversation history** — `context.chat_history`, capped at the last 24
  turns, round-trips through the client like everything else in `context`.
  Short-term, this-conversation-only.
- **Long-term memory** — earlier CONSULTATIONS by this signed-in user,
  fetched server-side from Convex (`/backend/user-memory`), scoped to the
  verified `user_id` from the JWT — never a client-supplied one. Surfaces as
  `memory:` sources. There is no way to opt out per-request today; it is
  always consulted for a signed-in caller.

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
