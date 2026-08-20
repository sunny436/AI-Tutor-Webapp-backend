> **SUPERSEDED — 2026-08-20**
>
> The technology choices are still accurate; the directory map and `C:\ayurveda` paths are not.
>
> Production moved to the Ubuntu VM `10.1.30.37` on 19 Aug 2026.
> The authoritative description is [INFRASTRUCTURE.md](../INFRASTRUCTURE.md).
> Everything below is kept for history and may be wrong.

# Ayurveda & Yoga Chatbot — Complete Tech Stack (Detailed)

**By Ollasoftware**

This document explains **every technology** used in this project — in simple
language — what it is, **why** we use it, and **where** it lives in the code.

---

## 1. The Big Picture

This project has **two languages** and **two databases**, split into clear parts:

```
┌─────────────────────────────────────────────────────────────┐
│  BROWSER  (what the user sees)                               │
│  Next.js + React + TypeScript + Tailwind CSS                 │
└───────────────┬───────────────────────┬─────────────────────┘
                │ login / data           │ AI answer
                ▼                        ▼
      ┌───────────────────┐   ┌──────────────────────────────┐
      │  CONVEX            │   │  PYTHON AI BACKEND           │
      │  (platform plane)  │   │  (domain / brain plane)      │
      │  auth, users,      │   │  FastAPI + LangGraph +       │
      │  database,         │   │  LangChain                   │
      │  dashboard state   │   │      │ model → GROQ (LLM)    │
      │                    │   │      │ search → ChromaDB      │
      └───────────────────┘   └──────────────────────────────┘
```

- **TypeScript** powers the website (Next.js) and the Convex backend.
- **Python** powers the AI brain (the chatbot logic).
- **Convex** stores app data (users, chats). **ChromaDB** stores Ayurveda knowledge.

---

## 2. Frontend — What The User Sees

Location: `apps/app/` (the dashboard) — this is the website you open at
`http://localhost:3000`.

### Next.js (v14)
- **What:** A framework for building websites with React. It handles pages,
  navigation (routing), and rendering.
- **Why:** It gives us a fast, modern, production-ready website structure without
  building everything from scratch.
- **Where:** `apps/app/src/app/…` — each folder is a page. For example, our
  chatbot page is `apps/app/src/app/[locale]/(dashboard)/consult/page.tsx`.

### React (v18)
- **What:** The library for building user interfaces out of reusable pieces
  called **components** (buttons, chat bubbles, forms).
- **Why:** It lets the UI update automatically when data changes (e.g., a new chat
  message appears without reloading).
- **Where:** Everything in `.tsx` files. Our Consult page is one big React
  component.

### TypeScript
- **What:** JavaScript with **type checking** — it catches many mistakes before
  the code even runs.
- **Why:** Safer, more reliable code; easier to maintain.
- **Where:** All `.ts` / `.tsx` files.

### Tailwind CSS
- **What:** A styling system where you add design directly with small class names
  (e.g., `rounded-xl bg-emerald-500`).
- **Why:** Fast, consistent design without writing separate CSS files.
- **Where:** The `className="…"` values throughout the UI. Our Consult page uses
  Tailwind for the gradients, cards, and colors.

### Supporting UI libraries
- **@v1/ui** — the template's shared component kit (buttons, etc.) in
  `packages/ui/`.
- **lucide-react** — clean icons (the leaf 🌿, send arrow, section icons).
- **sonner** — small popup "toast" messages (e.g., error notices).
- **next-themes** — light / dark mode switching.

---

## 3. Platform — Convex (Login, Database, Dashboard)

Location: `packages/backend/convex/`

### Convex
- **What:** An all-in-one **backend + database + real-time engine** that runs in
  the cloud. You write small functions (queries/mutations) and Convex stores the
  data and keeps every screen in sync live.
- **Why:** We don't have to build or manage a separate server or database. It
  gives us login, data storage, and live updates out of the box.
- **Where:**
  - `schema.ts` — the shape of the database tables (users, jobs, files, etc.).
  - `jobs.ts`, `backend.ts`, `http.ts` — server functions.
  - Your live deployment URL: `https://kindred-sockeye-79.convex.cloud`.

### Convex Auth
- **What:** The login system built into Convex.
- **Why:** Secure sign-in without building our own auth.
- **Where:** `auth.ts`, `ResendOTP.ts`. We use the **email one-time code (OTP)**
  method — the code appears in the `convex dev` terminal during development.

### Polar (billing) — *included, not used*
- **What:** A payments/subscription tool the template ships with.
- **Why not now:** We're not charging users, so it's inactive.
- **Where:** `subscriptions.ts`.

---

## 4. AI Backend — Python (The Chatbot's Brain)

Location: `backend-python/` — runs at `http://localhost:4000`.

### Python
- **What:** The programming language for our AI logic.
- **Why:** It has the best, easiest AI libraries (LangChain, LangGraph).
- **Where:** All files in `backend-python/`.

### FastAPI
- **What:** A Python tool for building a web API (the "doors" other apps call).
- **Why:** Fast, simple, and modern. It serves our `/chat`, `/upload`, `/health`
  endpoints.
- **Where:** `backend-python/server.py`.

### Uvicorn
- **What:** The web server that runs the FastAPI app.
- **Why:** It's the standard, high-performance way to run FastAPI.
- **Where:** Started by `run_backend.bat` → `python server.py`.

### LangGraph
- **What:** A tool to build the chatbot's **step-by-step flow** as a small graph.
- **Why:** Our chatbot isn't a single question→answer. It: (1) checks for
  emergencies, (2) decides if it needs more info and asks follow-ups, (3) searches
  the knowledge, (4) writes the full solution. LangGraph organizes these steps.
- **Where:** `backend-python/src/graph.py`.

### LangChain
- **What:** A toolbox for working with AI models — prompts, model calls, document
  loaders, embeddings, and connecting to a vector database.
- **Why:** It provides ready-made building blocks so we don't hand-code each piece.
- **Where:** Used across `src/llm.py`, `src/knowledge.py`, `src/graph.py`.

### Groq (the LLM)
- **What:** The actual **AI model** (Llama 3.3, 70B) that generates the answers.
  Groq hosts it and gives very fast responses via a **free** API.
- **Why:** Free, fast, and good quality. Swappable with a local model (Ollama) by
  changing one setting.
- **Where:** `src/llm.py` (`get_llm()`), configured in `backend-python/.env`.

### ChromaDB (vector database)
- **What:** A local database that stores the Ayurveda/Yoga notes as **vectors**
  (numbers representing meaning) so we can search by meaning, not exact words.
- **Why:** This is the "RAG" step — it keeps the AI's advice **inside Ayurveda &
  Yoga** and accurate.
- **Where:** `backend-python/data/vector_store/` (auto-created), used via
  `src/knowledge.py`.

### sentence-transformers / HuggingFace embeddings
- **What:** A free, local model (`all-MiniLM-L6-v2`) that turns text into those
  vectors.
- **Why:** No API key needed, runs on your machine, powers the knowledge search.
- **Where:** `src/knowledge.py` (`get_embeddings()`).

### Document reading — pypdf, pdfplumber, pytesseract, Pillow
- **What:** Tools to read text from uploaded reports: PDFs (pypdf/pdfplumber) and
  images via OCR (pytesseract + Pillow).
- **Why:** So users can attach a medical report and the AI can use it.
- **Where:** `src/documents.py`, endpoint `/upload` in `server.py`.

### PyJWT
- **What:** Verifies a Convex login token (JWT) using public keys.
- **Why:** For the "production" mode where Convex calls the Python backend
  securely.
- **Where:** `server.py` (`/whoami`).

### The AI flow, file by file
| File | Role |
|---|---|
| `server.py` | Web API — serves endpoints + (in local mode) the chat page |
| `config.py` | Reads settings from `.env` |
| `src/llm.py` | Picks & caches the AI model (Groq/Ollama) |
| `src/prompts.py` | The rules: only Ayurveda/Yoga, no medicines, answer format |
| `src/safety.py` | Emergency keyword check → "see a doctor" |
| `src/knowledge.py` | Ayurveda/Yoga search (ChromaDB + embeddings), cached |
| `src/documents.py` | Reads PDFs/images |
| `src/graph.py` | The LangGraph brain (the whole flow) |
| `scripts/ingest_knowledge.py` | Loads notes into the vector DB |
| `data/knowledge/*.md` | The trusted Ayurveda/Yoga notes |

---

## 5. Tools Used In Development

### Bun
- **What:** A fast package manager and JavaScript runtime (like npm, but faster).
- **Why:** The template uses it to install and run the frontend.
- **Where:** `bun install`, `bun dev:app`.

### Turborepo (turbo)
- **What:** A tool to manage a **monorepo** — one project holding several apps and
  shared packages together.
- **Why:** The template keeps `apps/app`, `apps/web`, and `packages/*` in one repo;
  turbo builds/runs them efficiently.
- **Where:** `turbo.json`, root `package.json` scripts (`dev:app`, `build`).

### Node.js ecosystem
- **What:** The world of JavaScript packages that Next.js, React, etc. build on.

### VS Code & Git
- **VS Code** — the code editor you're using.
- **Git** — version control (optional; not set up yet, recommended later).

---

## 6. Databases (Summary)

| Database | Where it runs | What it stores |
|---|---|---|
| **Convex** | Cloud | Users, accounts, chat/jobs, files — the app's data |
| **ChromaDB** | Your machine (in `backend-python`) | Ayurveda/Yoga knowledge for AI search |

---

## 7. How A Consult Works (End To End)

1. You type a problem on the **Consult** page (Next.js + React).
2. The page sends it to the **Python backend** (`POST /chat`).
3. **LangGraph** runs the flow:
   - **safety** check (emergency words?) → if serious, "see a doctor".
   - **gather**: is there enough info? If not, asks one follow-up question.
   - **retrieve**: **ChromaDB** finds the most relevant Ayurveda/Yoga notes.
   - **answer**: **Groq (LLM)** writes the full solution (root cause, food chart,
     yoga, daily routine, when to see a doctor).
4. The answer returns to the page and is shown as nice, colored section cards.
5. **Convex** handled your login and powers the whole dashboard around it.

---

## 8. How To Run Everything (3 terminals)

**Terminal 1 — Convex (login/data)**
```
cd C:\ayurveda\packages\backend
bunx convex dev
```

**Terminal 2 — Python AI (the brain)**
```
cd C:\ayurveda\backend-python
.\run_backend.bat
```

**Terminal 3 — Dashboard (website)**
```
cd C:\ayurveda
bun dev:app
```
Then open **http://localhost:3000**.

> For the fastest experience, build once and start:
> `bunx turbo build --filter=@v1/app` then `bun start:app`.

---

## 9. Project Structure (Map)

```
C:\ayurveda\
├── apps/
│   ├── app/                  ← the dashboard website (Next.js) — YOU LOGIN HERE
│   │   └── src/app/[locale]/(dashboard)/consult/page.tsx  ← the chatbot page
│   └── web/                  ← marketing site (from template, optional)
├── packages/
│   ├── backend/convex/       ← Convex functions + schema (login, data, jobs)
│   └── ui/                   ← shared UI components
├── backend-python/           ← THE AI BRAIN (Python)
│   ├── server.py             ← FastAPI web API
│   ├── src/                  ← llm, prompts, safety, knowledge, documents, graph
│   ├── data/knowledge/       ← Ayurveda/Yoga notes
│   ├── run_backend.bat       ← one-click start
│   └── .env                  ← your keys/settings
└── PROJECT_TECH_STACK.md     ← this file
```

---

## 10. Two Languages, One Product

- **TypeScript** → the website + Convex backend (login, data, dashboard).
- **Python** → the AI brain (understanding + Ayurveda/Yoga answers).

Convex is the **platform**; Python is the **intelligence**; the Next.js dashboard
is the **face**. Together they make the Ayurveda & Yoga chatbot.

*— Ayurveda, by Ollasoftware*
