# Ayurveda & Yoga Wellness Assistant

*by Ollasoftware*

An Ayurveda and Yoga consultation assistant. A user describes a health problem in
English, Hindi or Hinglish; the assistant asks a short round of intake questions, searches
a curated Ayurveda knowledge base, and returns a structured plan — root cause, food chart,
yoga, daily routine, and when to see a real doctor.

Built on the [Convex v1 starter](https://github.com/get-convex/v1), heavily extended.

---

## Architecture

Two backends, deliberately split:

```
                    Browser — Next.js dashboard (apps/app)
                       │                      │
              login, data, jobs         consultations
                       │                      │
                       ▼                      ▼
         ┌──────────────────────┐  ┌──────────────────────────┐
         │ CONVEX               │  │ PYTHON AI BACKEND        │
         │ (platform plane)     │  │ (domain plane)           │
         │ auth · database ·    │  │ FastAPI + LangGraph      │
         │ workspaces · RBAC ·  │  │   router → planner →     │
         │ jobs · files · audit │  │   responder              │
         │ cloud, always on     │  │   LLM   → Groq           │
         └──────────────────────┘  │   search→ ChromaDB (local)│
                                   └──────────────────────────┘
```

**Convex** owns identity and application data. **Python** owns the consultation itself.
They share nothing but a service key and a webhook secret, so either can be replaced
without touching the other.

---

## Layout

```
apps/app/              Next.js 14 dashboard — the product
  src/app/[locale]/    App Router. Folder path IS the URL; do not rearrange.
    (dashboard)/       authenticated area — consult, jobs, files, platform, settings
    (public)/          login
packages/
  backend/convex/      Convex functions + schema. Filename IS the API path
                       (audit.ts → api.audit.*); do not rename casually.
  ui/                  shared shadcn components
  email/ logger/ analytics/
backend-python/        FastAPI AI backend
  src/consult/         the live engine: router → planner → responder
  src/graph.py         LEGACY single-shot flow, serves frontend/index.html only
  data/knowledge/      29 curated Ayurveda notes — the RAG source of truth
  data/vector_store/   generated ChromaDB index (gitignored)
e2e/                   browser test suites (node scripts, need servers running)
self-hosted/           optional Docker stacks: self-hosted Convex, Mailpit, GlitchTip
docs/
  START.md             day-to-day run instructions
  TECH_STACK.md        what every technology is and why it is here
  MODELS.md            model evaluation notes
  history/deploy/      one-time VM provisioning scripts, kept for reference.
                       Hardcoded to a specific VM — not runnable as-is.
ROADMAP.md             deferred work, ordered by priority
```

---

## Running it

Two terminals. See [docs/START.md](docs/START.md) for the full version.

```powershell
# Terminal 1 — dashboard
cd apps\app
npx next dev -p 3000

# Terminal 2 — AI backend
cd backend-python
.\.venv\Scripts\python.exe server.py
```

Then open **http://localhost:3000** and go to **Consult**.

> `http://localhost:4000` also serves a standalone chat page, but it posts to the
> **legacy** `/chat` endpoint, which has no conversation memory and will repeat itself.
> It is kept for quick backend-only checks. The real product is the dashboard.

Convex needs nothing running locally — it lives in the cloud.

---

## Configuration

Neither file is committed.

**`apps/app/.env.local`**

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_CONVEX_URL` | Convex deployment URL. **Baked in at build time** — changing it needs a rebuild, not just a restart. |
| `NEXT_PUBLIC_AI_BACKEND_URL` | Python backend, default `http://localhost:4000` |
| `NEXT_PUBLIC_BACKEND_URL` | Same server, for the direct JWT path |
| `NEXT_PUBLIC_GOOGLE_AUTH_ENABLED` | Hides the Google button unless `true` |

**`backend-python/.env`**

| Variable | Purpose |
|---|---|
| `LLM_PROVIDER` | Default provider for unprefixed model names: `groq`, `openrouter` or `ollama` |
| `GROQ_API_KEY` | Free key from [console.groq.com](https://console.groq.com) |
| `OPENROUTER_API_KEY` | Free key from [openrouter.ai](https://openrouter.ai) — a **second** budget |
| `MODEL_CHAIN` | Tried in order on rate limits. Entries may name a provider (`groq:…`, `openrouter:…`), so one chain spans both |
| `ROUTER_MODEL` | Intent classifier — see the warning below |
| `EMBEDDING_MODEL` | `BAAI/bge-m3`. Multilingual; changing it invalidates `MIN_RELEVANCE` |
| `DEBUG_RAG` | `1` enables the service-key-guarded `GET /debug/retrieve` |
| `SERVICE_KEY` | Must match Convex `BACKEND_SERVICE_KEY` |
| `CONVEX_SITE_URL` | `.convex.site` URL; JWKS lives at `/.well-known/jwks.json` |

### Three things that will bite you

**Never add a model to `MODEL_CHAIN` without running `scripts/eval_chain_models.py`.**
The bar is: valid router JSON, correct intent on a plain complaint, and ≥4 intake
questions. Models that fail it do not degrade gracefully — they fail *confidently*.
Measured: `llama-3.1-8b-instant` INVERTED intents (a complaint became small talk while
a greeting opened a consultation about a non-existent condition), and produced 2 vague
questions where capable models produce 5. Every health check stayed green throughout.
An honest "daily limit reached" is a better failure than a fabricated consultation.

Also rejected by that script, so don't re-add them: `groq:openai/gpt-oss-20b` and
`groq:qwen/qwen3.6-27b` hard-fail JSON mode (400); `openrouter:nvidia/nemotron-3-nano-30b-a3b:free`
and `openrouter:openai/gpt-oss-20b:free` spend the token cap on reasoning and return no
parseable JSON.

**Capacity comes from providers, not models.** Groq meters tokens-per-day *per model*,
so once its capable models are spent, adding more Groq models does not help. That is why
the chain spans Groq (fast, ~4s) and OpenRouter (correct but ~58s on free models).

**Voice is OpenRouter-only.** `transcribe()` and `speak()` in `src/llm.py` call OpenRouter
directly and cannot use Groq or Ollama. The mic reports unavailable without
`OPENROUTER_API_KEY`; TTS additionally needs `TTS_MODEL` and is a paid model.

---

## Tests

```powershell
# Convex — in-process, no deployment or network needed
cd packages\backend
bun run test

# Python — no backend, no API key needed
cd backend-python
.\.venv\Scripts\python.exe tests\test_repair.py           # JSON repair
.\.venv\Scripts\python.exe tests\test_retrieval.py        # RAG quality, 84 labelled cases
.\.venv\Scripts\python.exe tests\test_safety.py           # emergency + serious-condition rules
.\.venv\Scripts\python.exe tests\test_provider_split.py   # cross-provider model naming
.\.venv\Scripts\python.exe tests\test_memory.py           # long-term memory + user isolation

# Python — needs the backend running and a working model
.\.venv\Scripts\python.exe tests\test_e2e.py              # every response type, 3 scripts
.\.venv\Scripts\python.exe tests\test_persona.py          # no medicines, no doctor claim, language
.\.venv\Scripts\python.exe tests\test_conversation.py

# Browser end-to-end — needs both servers up
cd e2e
node consult-local.js
node auth-local.js
```

After editing anything in `backend-python/data/knowledge/`, rebuild the index:

```powershell
.\.venv\Scripts\python.exe scripts\ingest_knowledge.py
```

Re-running it is safe — it does not create duplicates.

---

## License

See [LICENSE.md](LICENSE.md).
