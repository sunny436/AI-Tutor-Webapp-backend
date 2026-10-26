# Roadmap

1. **Generic chatbot backend (done, on `generic-chat-foundation`):** PostgreSQL + pgvector,
   accounts, conversations, streaming chat, stop/regenerate/feedback, provider abstraction, tests, CI.
2. **Frontend migration (done; now in `frontend/` of this repository):** replace the old client with the chat UI described in
   [docs/frontend-integration.md](docs/frontend-integration.md) (Markdown/code/tables/math rendering,
   stop, regenerate, copy, feedback, conversation sidebar).
3. **Production cutover (done):** production serves only this repository's checkout; the owner removed the old
   stack on 2026-09-29 ([docs/production-migration.md](docs/production-migration.md)).
4. **AI tutor (the current phase):** learner profile tables, curriculum retrieval as a
   `ContextProvider`, embeddings in pgvector, tutor-specific `AssistantConfig`, citations event.
   See the extension points in [docs/architecture.md](docs/architecture.md). What is live is listed in
   [docs/features.md](docs/features.md), and the verified gaps in [docs/known-limitations.md](docs/known-limitations.md).

RAG foundation (done on `rag-langgraph-pgvector`): LangGraph turn graph, LangChain retriever over
pgvector, ingestion CLI, global/private knowledge sources — see [docs/rag.md](docs/rag.md).
RAG follow-ups: a real embedding key + `eval_retrieval.py` calibration of `RAG_MIN_SCORE`; citations in
the public API; PDF/DOCX parsing; pruning of removed files; query rewriting/reranking; project scoping.

Technical follow-ups: conversation titles (done, deliberately without a model: `backend/app/chat/titles.py`);
staging environment; off-host backup copy;
backend error reporting (Sentry/GlitchTip); a valid fallback LLM key.
