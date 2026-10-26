# Glossary

Plain-language meanings of the words used in this repository. Each entry says where the idea lives in the code,
when that helps.

## General terms

| Term | Meaning |
|---|---|
| **Frontend** | The part people see and click: here, the web app in `frontend/` (Next.js and React), which runs in the browser and on its own small server |
| **Backend** | The part that holds the data and the rules: here, the API in `backend/` (FastAPI, Python) |
| **API** | Application Programming Interface: the list of requests a program accepts and what it answers. PadhAI's is `/v1/...`, described in [api-contract.md](api-contract.md) |
| **Endpoint / route** | One entry of an API, such as `POST /v1/chat/stream` |
| **BFF** | Backend For Frontend: the web app's own server routes (`/api/v1/*`) that pass allowlisted requests to the API and keep the session token away from the browser (`lib/server/proxy-core.ts`) |
| **Database** | Where data is kept for good. PadhAI uses one PostgreSQL 16 database |
| **Migration** | A versioned script that changes the database's structure (`backend/alembic/versions/`), applied with `alembic upgrade head` |
| **Environment variable** | A named setting read when a program starts (see [environment-variables.md](environment-variables.md)) |
| **Session** | Proof that you signed in: a random token, kept in an httpOnly cookie that page code can't read. The API stores only its SHA-256 |
| **SSE** | Server-Sent Events: one HTTP response that keeps sending small events, which is how a reply appears word by word |
| **Token (two meanings)** | A *session token* proves who you are. A model *token* is a small piece of text the AI produces (roughly 4 characters of English) |
| **LLM** | Large language model: the AI that writes answers. PadhAI calls one through an OpenAI-compatible API (Ollima first, OpenRouter as fallback) |
| **Prompt** | Everything sent to the model for one answer: instructions, context, history and the question |
| **Embedding** | A list of 1,536 numbers that captures what a text is about, so similar texts can be found ("vector search") |
| **pgvector** | The PostgreSQL extension that stores embeddings and searches them (HNSW index) |
| **RAG** | Retrieval-augmented generation: search for relevant passages first, then let the model answer with them |
| **Chunk** | A piece of a document or file, small enough to embed and give to the model |
| **CI** | Continuous integration: tests that run on GitHub for every push (`.github/workflows/ci.yml`); advisory here |
| **e2e** | End-to-end tests: a real browser driving the real app (Playwright) |
| **Smoke test** | A quick check that the live site works after a deploy (`bun run smoke`) |
| **Deploy** | Moving a commit of `main` to production (`bun run deploy`) |
| **MATCH** | `bun run status` and the deploy's verdict: production runs exactly GitHub `main` |
| **Rollback** | Going back to an earlier commit the same way (`bun run rollback`) |

## PadhAI terms

| Term | Meaning |
|---|---|
| **PadhAI** | The product: an AI tutor for school students (Classes 6–12, CBSE/NCERT focus), built on a chat |
| **QA account** | The owner's test account that the production smoke signs in as |
| **JEV** | The owner's name for the two quick classifications before an answer: the **intent router** (what kind of help a message asks for, 46 intents) and the **study scope filter** (whether it's study at all). Both run on Ollalink's classification model (`app/intents/`) |
| **Intent** | One of the 46 kinds of help (`explain_concept`, `solve_numerical`, `generate_mcq`, …) in 8 groups (`app/intents/taxonomy.py`) |
| **Scope decision** | `ALLOW_STUDY`, `ALLOW_SUPPORT`, `CLARIFY`, `PARTIAL_ALLOW` or `REDIRECT` (`app/intents/scope.py`) |
| **Ollalink / OllaLink** | The outside AI service PadhAI uses for classification (JEV) and for speech (voice mode) |
| **Ollima** | The primary LLM gateway (OpenAI-compatible) |
| **Ollastack** | An email-sending service (Agent Mail API), one of the two email backends |
| **NCERT Knowledge Service** | A separate service, from another repository, that searches the NCERT textbooks for Classes 6–12. PadhAI calls it only through its HTTP API |
| **Knowledge base** | PadhAI's own pgvector collection of documents (`knowledge_sources`, `documents`, `document_chunks`), used when the NCERT service isn't configured |
| **File Library** | A student's uploaded files (PDF, Office, images, text), 100 MB each student, which can be attached to chats |
| **Extractor** | The sandboxed program that reads text out of an uploaded file (`python -m app.files.extract`) |
| **Question bank** | Stored CBSE-pattern multiple-choice questions for Classes 6–12 (`app/qbank`, `qbank/`). Tests serve approved questions and those awaiting review, never drafts or rejected ones |
| **Bank test** | A test in the chat whose questions come from the question bank, never from the model |
| **Adaptive test** | A bank test that chooses each next question from the previous answer |
| **Practice ledger / record** | Every answer to a bank test, and what it says: mastery, revision dates, mistakes. The record is shown on My Learning |
| **Mastery (BKT)** | Bayesian knowledge tracing: an estimate of how well a concept is known, from the answers |
| **Learning day** | An India-time day with a meaningful, fully answered question, or 5 answers to bank tests (`app/progress/learning.py`) |
| **Streak** | Consecutive learning days, shown in the header |
| **Active time** | Minutes PadhAI was open and used (Progress & Goals), different from study time |
| **Study time / study session** | Time inside sessions the student starts on Study Activity, credited by the server from the page's beats |
| **Beat** | A tab's report, every 30 seconds, of what it observed (studying, idle, hidden) |
| **Greeting** | The short study line above a new chat's composer, from a weekly pool the LLM refreshes |
| **Study card** | A highlighted block the tutor can write (`:::note`, `:::definition`, …) |
| **Citation** | A `[1]` (a textbook or knowledge passage) or `[F1]` (an attached file) marker in an answer, with a Sources list |
| **Versioned edit** | How settings are saved: `{version, set, reset}`; an old version gets 409 `version_conflict` |
| **Preview features** | Sample-data pages (Homework Helper, Summarizer) shown only with `PREVIEW_FEATURES=1`, never in production |
| **Voice mode** | Talking with the tutor: speech in, the answer read aloud (English only) |
| **Expression** | The voice tutor face's manner for a turn (neutral, happy, explaining, focused, thinking, encouraging) |
| **Release** | The commit a process started from: `RELEASE` file on the host, shown by `/health` |
