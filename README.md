# AI Tutor: chat application

A ChatGPT-style AI chat app with accounts, conversations and streamed replies, built to grow into an
AI tutor. **One repository, one commit, one release:** the web app and the API live here together
and are tested, deployed and rolled back together.

> **AI Tutor is released as one application. Frontend and backend are never independently
> deployed to production.**

```
Browser ──► Cloudflare ──► frontend/  Next.js web app + server-side proxy (BFF)   127.0.0.1:3000
                                 │  httpOnly session cookie → Authorization: Bearer
                                 ▼
                           backend/   FastAPI chat API                            127.0.0.1:4100 (prod)
                                 ├──► PostgreSQL 16 + pgvector (users, chats, RAG vectors)
                                 ├──► LangGraph turn graph + LangChain retriever
                                 └──► LLM (OpenAI-compatible) · email (SMTP or Ollastack)
```

| What | Where |
|---|---|
| Web app (Next.js 14, Bun + Turborepo) | [frontend/](frontend/) |
| API (FastAPI, SQLAlchemy async, Alembic) | [backend/](backend/) |
| The contract between them | [docs/openapi.json](docs/openapi.json), [docs/api-contract.md](docs/api-contract.md), [docs/frontend-integration.md](docs/frontend-integration.md) |
| Architecture and extension points | [docs/architecture.md](docs/architecture.md), [docs/rag.md](docs/rag.md) |
| Local development and tests | [docs/development.md](docs/development.md) |
| Deploying and rolling back | [docs/deployment.md](docs/deployment.md), [docs/rollback.md](docs/rollback.md), [deploy/](deploy/), [INFRASTRUCTURE.md](INFRASTRUCTURE.md) |

## Quick start

Needs Python 3.12, [Bun](https://bun.sh) 1.3.14 (`.bun-version`), Node 24 (`.node-version`, used by
the end-to-end tests and in production) and Docker.

```sh
bun run setup     # backend venv + dependencies, frontend dependencies
bun run dev       # database + migrations, API on :4000, web app on http://localhost:3000
bun run test      # backend + frontend tests, including the API contract
```

## Releasing

```sh
bun run verify    # the three CI jobs on the commit checked out, in a Linux container (docs/deployment.md)
bun run deploy -- --ref <commit>   # that verified commit, if it is on GitHub and contains main and what is live
bun run status    # which release production runs; both apps must report the same commit
bun run rollback  # both apps back to the previous release, together (docs/rollback.md)
```

Those are the only production commands (`verify` only reads).

## History

This repository started as the backend of an Ayurveda chatbot (preserved at the tag
`ayurveda-baseline`); nothing from that product is used any more. The web app was a separate
repository until it was imported, with its history, into `frontend/`. How production moved off the
old stack is described in [docs/production-migration.md](docs/production-migration.md).
