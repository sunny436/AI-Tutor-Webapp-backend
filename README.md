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
        Browser — Next.js dashboard (SEPARATE REPO: ayurveda-frontend)
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

**The frontend is not in this repository.** It was split out to
`ayurveda-frontend` so an external team could own it. This repo keeps the AI
backend, the contract it publishes, the browser tests, the tunnel and the
supervisor — and the live site is served FROM that other repo, which is why
`scripts/production/start-all.ps1` points outside this tree.

```
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
ROADMAP.md             deferred work (backend only; the frontend has its own)
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

> `http://localhost:4000` serves a plain status page, not a chat UI. The standalone
> page that used to live there was removed when the backend was published at
> `ayur-api.namahos.com`: it was a fully working anonymous chatbot on the public
> internet, spending the AI balance. `/chat` now requires a signed-in caller, so
> the page could not have worked anyway.

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

# Against the LIVE site, in a real browser. Codes are read from a real inbox,
# so these prove mail actually leaves the building.
$env:E2E_BASE_URL = "https://ayur.namahos.com"
$env:E2E_API_URL  = "https://ayur-api.namahos.com"
$env:E2E_IMAP_USER = "…"; $env:E2E_IMAP_PASS = "…"   # Gmail app password
node auth-live.js      # all five sign-in paths
node prod-full.js      # chat, languages, isolation, headers, CORS, refresh
```

After editing anything in `backend-python/data/knowledge/`, rebuild the index:

```powershell
.\.venv\Scripts\python.exe scripts\ingest_knowledge.py
```

Re-running it is safe — it does not create duplicates.

Browser suites need **`node`**, not `bun` — under bun on Windows Playwright's
`--remote-debugging-pipe` handshake never completes and every launch hangs for the
full timeout with an error that blames the browser. See [e2e/README.md](e2e/README.md).

---

## Production

The application runs on the **company machine**. Cloudflare hosts nothing — it
supplies DNS, TLS, a firewall and a tunnel, so the machine can serve the internet
without opening a single inbound port.

```
User → Cloudflare (DNS · SSL · WAF) → Tunnel → this machine
                                                 ├── Next.js  127.0.0.1:3000
                                                 └── FastAPI  127.0.0.1:4000
                                                        ↓            ↓
                                                 Convex Cloud   Groq → OpenRouter
```

| Public hostname | Serves |
|---|---|
| `ayur.namahos.com` | the dashboard |
| `ayur-api.namahos.com` | the AI backend, which the browser calls directly |

Both processes bind **loopback only**, so nothing on the LAN can reach them. See
[cloudflare/README.md](cloudflare/README.md) for the tunnel setup and the token
permissions it needs.

### Starting and stopping

```powershell
# start everything (safe to re-run: it only starts what is not already up)
powershell -ExecutionPolicy Bypass -File .\scripts\production\start-all.ps1

# the same script runs at logon and every 5 minutes as a watchdog
Get-ScheduledTask -TaskName AyurvedaSite
Start-ScheduledTask -TaskName AyurvedaSite
```

Logs land in `logs/` (git-ignored): `backend-*.log`, `frontend-*.log`,
`tunnel-*.log`, and `supervisor.log` for the watchdog's own decisions.

### Deploying a change

```powershell
cd apps\app
bun run build          # REQUIRED after touching any NEXT_PUBLIC_* value —
                       # those are compiled into the bundle, not read at runtime
cd ..\..
Start-ScheduledTask -TaskName AyurvedaSite   # restarts whatever is down
```

Convex functions deploy separately:

```powershell
cd packages\backend
$env:CONVEX_DEPLOY_KEY = "…"
node ..\..\node_modules\convex\bin\main.js deploy -y
```

`npx convex dev --once` ignores `CONVEX_DEPLOY_KEY` and demands an interactive
login, so it cannot be used headlessly. Use `deploy -y`.

### Environment variables

Never committed. Each area keeps its own file, and every one has a committed
`.example` twin listing the keys with empty values:

| File | Purpose |
|---|---|
| `apps/app/.env.local` | dashboard. Everything `NEXT_PUBLIC_*` is **public** — visible in the browser bundle |
| `backend-python/.env` | AI backend, model keys, `HOST`, `ALLOWED_ORIGINS`, `REQUIRE_AUTH` |
| `cloudflare/.env` | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, zone and tunnel ids |
| Convex | not a file — set with `convex env set`; see `packages/backend/.env.example` |

`.gitignore` matches `.env` at any depth, so a new `<area>/.env` is protected the
moment it is created. Worth verifying anyway before a commit:

```powershell
git check-ignore -v cloudflare\.env
git status --short --untracked-files=all
```

### Uptime, honestly

Sleep and hibernate are disabled, and the watchdog restarts crashed processes —
verified by killing the tunnel and watching the site recover on its own. But the
scheduled task is triggered **at logon**, because registering a real Windows
service needs administrator rights this account does not have. After a reboot the
site stays down until someone logs in. Running
`cloudflared service install` once, elevated, would remove that gap.

---

## License

See [LICENSE.md](LICENSE.md).
