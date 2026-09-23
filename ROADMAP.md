# Roadmap

1. **Generic chatbot backend (this phase, done on `generic-chat-foundation`):** PostgreSQL + pgvector,
   accounts, conversations, streaming chat, stop/regenerate/feedback, provider abstraction, tests, CI.
2. **Frontend migration (frontend repository):** replace the old client with the chat UI described in
   [docs/frontend-integration.md](docs/frontend-integration.md) (Markdown/code/tables/math rendering,
   stop, regenerate, copy, feedback, conversation sidebar).
3. **Production cutover (requires approval):** [docs/production-migration.md](docs/production-migration.md).
4. **AI tutor (next product phase):** learner profile tables, curriculum retrieval as a
   `ContextProvider`, embeddings in pgvector, tutor-specific `AssistantConfig`, citations event.
   See the extension points in [docs/architecture.md](docs/architecture.md).

Technical follow-ups: LLM-generated conversation titles; staging environment; off-host backup copy;
backend error reporting (Sentry/GlitchTip); a valid fallback LLM key.
