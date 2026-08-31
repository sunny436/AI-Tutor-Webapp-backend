# The consultation API contract

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
  "profile": "",               // optional free-text user profile
  "documents": [               // every report the user attached — see below
    { "filename": "report.pdf", "text": "…" }
  ]
}
```

**`documents` is the one the client has to remember.** `/api/upload` no longer
stores anything, so the text it returned is held by the browser and sent back on
every turn. Omit it and the assistant simply cannot see the reports — it does not
remember the upload, because there is nothing on the server to remember.

Send it on **every** turn, not only on turns that look like they are about a
report. The client cannot tell which those are: "aur isme sugar kitna hai?" is a
question about an attached blood test and reads like small talk. Guessing wrong
fails silently — the model just answers without the document.

**Send the entries raw.** Do not join them into one string and do not add
`--- filename ---` headers: the backend labels each entry from its `filename`
and splits the retrieval budget across them. Hand-rolled headers are now
duplicate labelling inside text that is already labelled.

**`problem` vs `freeText` is the one thing that is easy to get wrong.**
Send `freeText` when `context.phase` is one of `CONSULTING`
(`gathering`, `asking_focus`, and the retired `collecting` / `choosing`); send
`problem` otherwise. Getting it backwards makes every follow-up look like a brand-new
complaint, and the consultation restarts instead of continuing.

**The backend is stateless.** Whatever `context` it returns must be sent back on
the next turn. It carries the conversation state; without it every message looks
like the first one.

### Response

```jsonc
{
  "kind": "chat" | "answer" | "escalation" | "error" | "intake",
  "condition": "Gas & Bloating",
  "message": "",
  "answer": "…",               // what to render
  "intake": null,              // always null — see "Retired" below
  "context": { /* send this back next turn */ },
  "documentTruncated": false,  // were the `documents` cut before retrieval?
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

`documentTruncated: true` means at least one of the `documents` you sent was too
long and only part of it reached retrieval — so the plan was written from part of
the report. Show it. A plan built from a full blood test and one built from its
first page are different things, and the reader is entitled to tell them apart.
Absent (from an older backend) means "no claim", never `false`.

### Sources

`source` is namespaced, and the namespaces mean different things. Do not flatten
them into one count — "based on 3 Ayurveda notes" is false if one of them is the
reader's own blood test.

| Prefix | Meaning |
|---|---|
| `knowledge:` | the shared curated Ayurveda corpus |
| `report:` | a document THIS user uploaded |
| `graphrag:` | an external reference document |
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
// /api/upload -> {
//   "filename":  "report.pdf",
//   "chars":     4821,        // characters recovered. 0 = nothing could be read
//   "text":      "…",         // THE EXTRACTED TEXT. The only copy. Keep it.
//   "truncated": false        // true = the file was too long to extract whole
// }
```

**THE BACKEND STORES NOTHING.** This used to return `indexed: <chunks>` and
embed the file into a private per-user collection, so a report survived a reload
and the assistant could find it again on its own. That is gone. The endpoint now
extracts text, hands it back, and forgets it.

So `text` is state the **client** owns:

- Hold it (component state, or storage if you accept the trade below).
- Send it back inside `documents` on every `/api/consult` turn.
- Lose it and the report is gone for good — there is nothing to re-fetch.

`chars: 0` means nothing could be read from the file — most often a scanned
PDF, which is rasterised and OCR'd rather than parsed. **Use `chars`, not the
retired `indexed`, as the success check.** A client still testing
`indexed > 0` evaluates `undefined > 0`, which is always false, and reports
every successful upload as unreadable.

`truncated: true` is about EXTRACTION — the file was too long to read whole, so
`text` is a prefix. It is a different flag from `documentTruncated` on the
consult response, which is about the text being cut on the way into retrieval.
Either can happen without the other.

### A note on where the client keeps it

These are medical reports. In `localStorage` they outlive the tab, the session
and the sign-out, on whatever machine the reader happened to use. This app keeps
them in component state instead and accepts that a reload loses the attachment —
a real regression from the indexed era, recorded here rather than hidden.

### The two caps, and why a client must not pre-trim

There are two, in series, and both are the backend's to apply:

| Where | Cap | Sets |
|---|---|---|
| `/api/upload` extraction | **40,000 chars** | `truncated` on the upload reply |
| `/api/consult` retrieval | **~1,200 chars total**, split across `documents` | `documentTruncated` on the turn |

**Do not trim on the client.** Send the whole thing every turn and let the
backend cut it. A client that pre-trims is guessing at a number it does not own,
and would silently drop text the backend was going to keep.

Note what the second cap implies: ~1,200 characters is roughly two hundred words,
so `documentTruncated: true` is the NORMAL case for any real report, not an edge
case. Treat it as "how much of this reached retrieval", not as an error.

### Several attachments: send them all

`documents` is a list and the backend budgets each entry itself, so attaching
three reports puts all three in play. There is no picking, no ordering trick and
no client-side arrangement to get right.

**Send the entries raw.** Two things the client must NOT do:

- **Do not join them into one string.** That was the old `documentText` field. It
  carried a single ~1,200-character retrieval budget for the whole string, so the
  second and third attachments were silently dropped — and this app had to make
  the reader select one active report to avoid promising otherwise. The list is
  what replaced that, and rebuilding the string by hand rebuilds the bug.
- **Do not add `--- filename ---` headers.** The backend labels each entry from
  its own `filename`. Hand-rolled headers are duplicate labelling inside text
  that is already labelled, and they spend budget saying what the field already
  says.

Nothing is trimmed client-side either — see the caps above.

#### The budget is SHARED, and that is the catch

One budget, divided by how many entries you send:

```python
budget = MAX_DOCUMENT_CHARS_IN_QUERY // len(documents)   # 1200 // n
```

So it does not multiply with the list — it splits:

| Attachments | Read from each |
|---|---|
| 1 | ~1,200 chars (~200 words) |
| 2 | ~600 chars (~100 words) |
| 3 | ~400 chars (~65 words) |
| 4 | ~300 chars (~50 words) |

At three, ~65 words of a blood test is the patient name and the date. So the
list fixed the *silent dropping* — every report now contributes something — but
it did not buy more room overall.

**A client must therefore say so.** This app puts the live per-report figure
under the composer as soon as a second report is attached, and says which way to
fix it: attach fewer for more of each. A UI that lists four reports and invites
questions about all four is promising something the split will break.

The number is mirrored in `RETRIEVAL_BUDGET_CHARS` in the consult page, for
DISPLAY ONLY — nothing is trimmed client-side. If the backend changes the
constant the sentence goes stale and nothing breaks, but update both.

### Payload size is deliberate

Every attached report rides along with every message in the conversation, and
that is the intended design. The obvious optimisation — a document id the backend
caches — is **rejected**: it reintroduces the server-side storage that was
removed for privacy. The wire cost is the price of the backend holding nothing.

### Losing the report on reload is intended

Component state, no persistence, gone on refresh. This matches the backend's
design rather than working around it, and needs no fix.

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


---

## Machine-readable summary

`contract.test.ts` parses the JSON below and asserts that `types.ts` still
agrees with it. **This block IS the contract** — there is no generated file any
more. `consult-contract.json` was produced by the backend's
`export_contract.py` from Pydantic models that the GraphRAG migration deleted;
it is not coming back, so this hand-written block replaced it.

Edit this when the wire changes, in the same commit as the prose above. If the
two disagree, the prose is what a human reads and the block is what the test
reads, so they must not be allowed to drift.

```json contract
{
  "enums": {
    "kind": ["chat", "intake", "answer", "escalation", "error"],
    "phase": ["idle", "greeted", "casual", "gathering", "asking_focus", "collecting", "choosing", "completed"]
  },
  "phase_groups": {
    "consulting": ["gathering", "asking_focus", "collecting", "choosing"],
    "legacy": ["collecting", "choosing"]
  },
  "source_namespaces": ["knowledge", "report", "graphrag", "memory"],
  "request_fields": [
    "problem",
    "context",
    "answers",
    "freeText",
    "profile",
    "conversationId",
    "documents",
    "bot_id"
  ],
  "result_fields": [
    "kind",
    "condition",
    "message",
    "answer",
    "intake",
    "context",
    "sources",
    "documentTruncated"
  ],
  "context_fields": ["phase", "chat_history", "language", "condition", "symptoms"],
  "upload_fields": ["filename", "chars", "text", "truncated"],
  "caps": {
    "upload_extract_chars": 40000,
    "consult_retrieval_chars_per_query": 1200,
    "retrieval_cap_applies_to": "1200 total, divided by documents.length — SHARED, not per entry"
  }
}
```
