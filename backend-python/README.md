# Ayurveda & Yoga AI Backend (Python)

This is the **AI "brain"** of the Ayurveda & Yoga health chatbot.

It is a small **Python (FastAPI)** web service that:

1. receives a user's health problem + their profile + any uploaded document text,
2. asks smart follow-up questions until it has enough information,
3. finds the **root cause** and gives a complete solution using **only Ayurveda
   and Yoga** (changes to make, a **food chart**, and a **daily routine**),
4. and refuses to ever suggest medicines — if something looks serious, it tells
   the user to see a doctor.

It is designed to plug into your **Convex "convex-ready-template"** as the
"real backend" (the template is built exactly for this — see *How it connects*).

---

## 1. The big picture (how the two parts work together)

```
Browser  ─▶  Next.js dashboard   (from your Convex template)
                │  live queries / mutations
                ▼
           CONVEX  ← the required backend/API
                │    (login, users, health profile, chat history, "jobs")
                │  proxy: sends a consult job to us
                ▼
        THIS PYTHON AI BACKEND   ← replaces the template's "backend-echo"
        (FastAPI + LangGraph + LangChain + free Groq LLM + Ayurveda/Yoga search)
                │  webhook: sends the finished answer back
                ▲
           CONVEX  →  the dashboard updates live with the answer
```

- **Convex owns the platform** (login, users, storing data, live UI) — this is
  the compulsory API.
- **This Python service owns the AI logic** (understanding the problem and giving
  the Ayurveda/Yoga solution).

They talk using the template's built-in **jobs** system, so we barely have to
write any "plumbing" — it already exists.

---

## 2. What each FILE does (use case of everything)

| File | What it is for |
|---|---|
| `server.py` | The web service. Defines the endpoints Convex calls: `/jobs/run` (run a consult), `/extract` (read an uploaded report), `/whoami` (verify a Convex login token), `/health`. Also sends the answer back to Convex via a webhook. |
| `config.py` | The "control panel". Reads all settings/keys from the `.env` file so nothing secret is hard-coded. |
| `src/llm.py` | Gives one function `get_llm()` that returns the free AI model. Switch between Groq (cloud) and Ollama (local) by changing one line in `.env`. |
| `src/prompts.py` | All the instructions we give the AI, including the strict "only Ayurveda & Yoga, never medicines" rules and the exact answer format (root cause, food chart, routine, etc.). |
| `src/safety.py` | A quick safety check. If the user's message contains emergency words, we stop and tell them to see a doctor. |
| `src/knowledge.py` | The Ayurveda/Yoga **knowledge search** (the "RAG" part). Finds the most relevant trusted notes for the user's problem so the AI stays accurate and inside Ayurveda/Yoga. |
| `src/documents.py` | Reads text from uploaded medical reports — PDFs (pypdf/pdfplumber) and images (OCR). |
| `src/graph.py` | The **brain**, built with LangGraph. Runs the step-by-step flow: safety check → enough info? → search knowledge → write the full solution. |
| `scripts/ingest_knowledge.py` | Loads the Ayurveda/Yoga notes from `data/knowledge/` into the searchable database. Run it once at setup. |
| `data/knowledge/*.md` | The trusted Ayurveda/Yoga notes (digestion, sleep, stress to start). Add more `.md` files here to make the AI smarter. |
| `requirements.txt` | The list of free libraries to install. |
| `.env.example` | A template for your settings file. Copy it to `.env` and fill it in. |

---

## 3. What each LIBRARY does (use case of everything)

| Library | Why we use it |
|---|---|
| **fastapi** | Builds the web API (the endpoints Convex calls). |
| **uvicorn** | Runs the FastAPI app (the actual server). |
| **httpx** | Sends the "here is the answer" webhook back to Convex. |
| **pyjwt[crypto]** | Verifies the Convex login token (JWT) using public keys, for the direct path. |
| **langgraph** | Builds our multi-step conversation flow (with the follow-up loop and safety branch). |
| **langchain / langchain-core / langchain-community** | Core building blocks: prompts, model calls, document tools. |
| **langchain-text-splitters** | Splits long knowledge notes into small searchable chunks. |
| **langchain-groq** | Talks to the **free Groq cloud LLM** (our default AI). |
| **langchain-ollama** | Optional: talks to a **free local LLM** via Ollama. |
| **langchain-huggingface + sentence-transformers** | Turn text into "embeddings" so we can search by meaning (free, local). |
| **langchain-chroma + chromadb** | The free local **vector database** that stores the Ayurveda/Yoga knowledge. |
| **pypdf / pdfplumber** | Read text from PDF medical reports. |
| **pytesseract / pillow** | Read text from images/photos of reports (OCR). Needs the free Tesseract program installed. |
| **python-dotenv** | Loads settings from the `.env` file. |
| **pydantic** | Validates data shapes across the app. |

---

## 4. Setup & run (step by step)

> You need **Python 3.11+** installed.

**Step 1 — Open a terminal in this folder and create a virtual environment.**

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Mac/Linux:
source .venv/bin/activate
```

**Step 2 — Install the libraries.**

```bash
pip install -r requirements.txt
```

**Step 3 — Create your settings file.**

Copy `.env.example` to `.env`, then fill in:
- `GROQ_API_KEY` — get a **free** key at https://console.groq.com
- `SERVICE_KEY` and `WEBHOOK_SECRET` — make up two long random strings (you will
  give the same values to Convex in the next section).
- `CONVEX_SITE_URL` — your Convex "site" URL (see the template's setup).

**Step 4 — Load the Ayurveda/Yoga knowledge into the search database.**

```bash
python scripts/ingest_knowledge.py
```

**Step 5 — Start the backend.**

```bash
python server.py
```

You should see it running on `http://localhost:4000`. Test it:

```bash
curl http://localhost:4000/health
```

---

## 5. How it connects to the Convex template

The template already knows how to call an external backend. You only need to
point it at this one and use the matching secrets.

**On the Convex side, set these environment variables** (from the template
folder):

```bash
npx convex env set BACKEND_BASE_URL     http://localhost:4000
npx convex env set BACKEND_SERVICE_KEY  <same value as SERVICE_KEY in .env>
```

(Use the same `WEBHOOK_SECRET` the template expects for its `/backend/webhook`.)

Then, to run an Ayurveda/Yoga consult, the dashboard creates a **job** of kind
`"ayurveda_consult"` with this input shape:

```json
{
  "problem": "I have had a gas problem for 5 days",
  "profile": "Age 29, vegetarian, sleeps late, low water intake ...",
  "history": "Ate fried food last night; some bloating; stress high",
  "followups": 0,
  "document_text": "(optional text read from an uploaded report)"
}
```

The template's `jobs` pipeline sends this to our `/jobs/run`, we process it, and
we webhook the result back. The result looks like:

```json
{
  "kind": "answer",          // or "followup" or "escalation"
  "answer": "**Root Cause** ... **Food Chart** ... **Daily Routine** ...",
  "knowledge_used": "the Ayurveda/Yoga notes the AI used"
}
```

- `kind: "followup"` → show the `answer` as the next question and send the user's
  reply back (add it to `history`, increase `followups`).
- `kind: "escalation"` → show the "please see a doctor" message.
- `kind: "answer"` → show the full solution.

> **Next step (once your VS Code folder is connected):** I will add a small
> Convex `profiles` table + functions and a simple **Consult / Chat page** in the
> dashboard so users can chat, upload a report, and see the answer live. The
> Python backend above is already ready for it.

---

## 6. The strict safety promise

This product **only** gives Ayurveda and Yoga guidance. It never gives medicines,
drugs, or dosages, and never claims to diagnose disease. Whenever a message looks
serious or like an emergency, it stops and tells the user to see a doctor. These
rules are enforced in `src/prompts.py` (instructions) and `src/safety.py`
(emergency check).
