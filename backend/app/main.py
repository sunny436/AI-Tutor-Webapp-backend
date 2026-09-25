"""Application factory.

    uvicorn app.main:create_app --factory --host 127.0.0.1 --port 4000

Tests call `create_app(settings, llm=..., email_sender=..., embeddings=...)` to inject fakes.

This is the composition root: the only place that wires the LLM provider, the embeddings,
the knowledge store, the LangChain retriever and the LangGraph graph together.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.embeddings import Embeddings

from app.auth.avatar import AVATAR_DECODES
from app.auth.emails import EmailSender, build_email_sender
from app.auth.router import router as auth_router
from app.auth.security import Passwords
from app.chat.router import router as chat_router
from app.chat.service import ChatService
from app.chat.streams import ActiveGenerations
from app.conversations.router import router as conversations_router
from app.db.models import EMBEDDING_DIMENSIONS
from app.db.session import Database
from app.errors import install_error_handlers
from app.health import router as health_router
from app.learning.router import router as learning_router
from app.llm.base import LLMProvider
from app.llm.factory import build_llm
from app.logging import configure_logging, get_logger
from app.middleware import RequestContextMiddleware
from app.rag.embeddings import build_embeddings, embedding_model_id, is_configured
from app.rag.graph import RagDependencies, build_rag_graph
from app.rag.retriever import PgVectorRetriever
from app.rag.store import KnowledgeStore
from app.rag.types import AccessScope, RetrievalOptions
from app.ratelimit import SlidingWindowLimiter
from app.settings import Settings, get_settings

log = get_logger("app")


def build_rag(settings: Settings, db: Database, llm: LLMProvider, embeddings: Embeddings):
    """Knowledge store + compiled LangGraph graph for one application instance."""
    store = KnowledgeStore(db, settings.rag_hnsw_ef_search)
    model = embedding_model_id(embeddings)

    def retriever_factory(scope: AccessScope, options: RetrievalOptions) -> PgVectorRetriever:
        return PgVectorRetriever(
            store=store,
            embeddings=embeddings,
            scope=scope,
            k=options.k or settings.rag_top_k,
            min_score=settings.rag_min_score if options.min_score is None else options.min_score,
            source_names=list(options.source_names) if options.source_names else None,
            metadata_filter=options.metadata_filter,
        )

    async def has_knowledge(scope: AccessScope) -> bool:
        return await store.has_chunks(scope, model)

    graph = build_rag_graph(
        RagDependencies(
            llm=llm,
            retriever_factory=retriever_factory,
            has_knowledge=has_knowledge,
            embeddings_configured=is_configured(embeddings),
            settings=settings,
        )
    )
    return store, graph


def create_app(
    settings: Settings | None = None,
    *,
    llm: LLMProvider | None = None,
    email_sender: EmailSender | None = None,
    embeddings: Embeddings | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    settings.validate_for_env()
    if settings.embedding_dimensions != EMBEDDING_DIMENSIONS:
        raise RuntimeError(
            f"EMBEDDING_DIMENSIONS={settings.embedding_dimensions} does not match the database column "
            f"vector({EMBEDDING_DIMENSIONS}); changing it needs a migration and a re-ingest"
        )
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db = Database(settings)
        app.state.knowledge, app.state.rag_graph = build_rag(
            settings, app.state.db, app.state.llm, app.state.embeddings
        )
        app.state.chat = ChatService(app.state.db, settings, app.state.rag_graph, app.state.generations)
        try:
            await app.state.chat.sweep_all_stale()
            ignored = await app.state.knowledge.count_other_model_chunks(embedding_model_id(app.state.embeddings))
            if ignored:
                log.warning(
                    "knowledge chunks from another embedding model are ignored; re-ingest to use them",
                    extra={"chunks": ignored},
                )
        except Exception as error:  # noqa: BLE001 - start anyway; /ready reports the database
            log.warning("startup checks skipped", extra={"error_type": type(error).__name__})
        log.info("started", extra={"env": settings.app_env, "llm": app.state.llm.name})
        try:
            yield
        finally:
            await app.state.generations.shutdown()
            await app.state.db.dispose()

    docs = settings.app_env != "production"
    app = FastAPI(
        title=f"{settings.app_name} API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.llm = llm or build_llm(settings)
    app.state.embeddings = embeddings or build_embeddings(settings)
    dimensions = getattr(app.state.embeddings, "dimensions", EMBEDDING_DIMENSIONS)
    if dimensions != EMBEDDING_DIMENSIONS:
        raise RuntimeError(f"embeddings produce {dimensions} dimensions; the database stores {EMBEDDING_DIMENSIONS}")
    app.state.email_sender = email_sender or build_email_sender(settings)
    app.state.passwords = Passwords(settings)
    app.state.generations = ActiveGenerations()
    app.state.avatar_decodes = asyncio.Semaphore(AVATAR_DECODES)
    app.state.tutor_preview_limiter = SlidingWindowLimiter(limit=60, window_s=60)

    install_error_handlers(app)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        )
    app.add_middleware(
        RequestContextMiddleware,
        max_body_bytes=settings.max_body_bytes,
        body_limits={("PUT", "/v1/me/avatar"): settings.avatar_max_bytes},
    )

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(conversations_router)
    app.include_router(chat_router)
    app.include_router(learning_router)
    return app
