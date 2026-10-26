"""Application factory.

    uvicorn app.main:create_app --factory --host 127.0.0.1 --port 4000

Tests call `create_app(settings, llm=..., email_sender=..., embeddings=..., intents=...)` to inject fakes.

This is the composition root: the only place that wires the LLM provider, the embeddings,
the knowledge store, the LangChain retriever and the LangGraph graph together.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.embeddings import Embeddings

from app.appearance.router import router as appearance_router
from app.auth.avatar import AVATAR_DECODES
from app.auth.emails import EmailSender, build_email_sender
from app.auth.internal import router as internal_auth_router
from app.auth.retention import purge_expired
from app.auth.router import router as auth_router
from app.auth.security import Passwords
from app.auth.service import utcnow
from app.chat.router import router as chat_router
from app.chat.service import ChatService
from app.chat.streams import ActiveGenerations
from app.conversations.router import router as conversations_router
from app.db.models import EMBEDDING_DIMENSIONS
from app.db.session import Database
from app.errors import install_error_handlers
from app.files.processing import FileWorker
from app.files.router import router as files_router
from app.files.service import MAX_UPLOAD_BYTES
from app.greetings.refresh import GreetingRefresh
from app.greetings.router import router as greetings_router
from app.health import router as health_router
from app.intents.classifier import IntentClassifier
from app.learning.router import router as learning_router
from app.llm.base import LLMProvider
from app.llm.factory import build_llm
from app.logging import configure_logging, get_logger
from app.middleware import ClassifierWarmMiddleware, RequestContextMiddleware
from app.notifications.router import router as notifications_router
from app.progress.router import router as progress_router
from app.rag.embeddings import build_embeddings, embedding_model_id, is_configured
from app.rag.graph import RagDependencies, build_rag_graph
from app.rag.ncert import NcertKnowledge, NcertRetriever
from app.rag.retriever import AttachedFiles, PgVectorRetriever
from app.rag.store import KnowledgeStore
from app.rag.types import AccessScope, RetrievalOptions
from app.ratelimit import SlidingWindowLimiter
from app.settings import Settings, get_settings
from app.study.router import router as study_router
from app.study.service import Chapters
from app.support.router import router as support_router
from app.voice.provider import VoiceProvider, build_voice
from app.voice.router import MAX_AUDIO_BYTES, InFlight, SpeechBudget
from app.voice.router import router as voice_router

log = get_logger("app")
# Auth retention (app/auth/retention.py): first run a few minutes after start, then hourly.
RETENTION_FIRST_RUN_S = 300
RETENTION_EVERY_S = 3600


def build_rag(
    settings: Settings, db: Database, llm: LLMProvider, embeddings: Embeddings, ncert: NcertKnowledge | None = None
):
    """Knowledge store + compiled LangGraph graph for one application instance. With `ncert`, the
    knowledge source is the NCERT Knowledge Service (app/rag/ncert.py) instead of pgvector; attached
    files always stay in pgvector."""
    store = KnowledgeStore(db, settings.rag_hnsw_ef_search)
    model = embedding_model_id(embeddings)

    def retriever_factory(scope: AccessScope, options: RetrievalOptions) -> PgVectorRetriever | NcertRetriever:
        if ncert is not None:
            k = options.k or settings.rag_top_k
            return NcertRetriever(knowledge=ncert, k=k, classes=options.classes, subjects=options.subjects)
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
        return ncert is not None or await store.has_chunks(scope, model)

    graph = build_rag_graph(
        RagDependencies(
            llm=llm,
            retriever_factory=retriever_factory,
            has_knowledge=has_knowledge,
            # The service embeds the query itself; ours are needed only for the pgvector knowledge base.
            embeddings_configured=ncert is not None or is_configured(embeddings),
            settings=settings,
            attached_files=AttachedFiles(store, embeddings).load,
        )
    )
    return store, graph


def create_app(
    settings: Settings | None = None,
    *,
    llm: LLMProvider | None = None,
    email_sender: EmailSender | None = None,
    embeddings: Embeddings | None = None,
    intents: IntentClassifier | None = None,
    voice: VoiceProvider | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    settings.validate_for_env()
    if settings.embedding_dimensions != EMBEDDING_DIMENSIONS:
        raise RuntimeError(
            f"EMBEDDING_DIMENSIONS={settings.embedding_dimensions} does not match the database column "
            f"vector({EMBEDDING_DIMENSIONS}); changing it needs a migration and a re-ingest"
        )
    configure_logging(settings.log_level)

    async def auth_retention() -> None:
        # Hourly, in this process: the jobs worker that also runs it is off in production.
        await asyncio.sleep(RETENTION_FIRST_RUN_S)
        while True:
            try:
                async with app.state.db.sessionmaker() as session:
                    purged = await purge_expired(session, utcnow())
                    await session.commit()
                log.info("auth retention", extra=purged)
            except Exception as error:  # noqa: BLE001 - try again next hour
                log.warning("auth retention failed", extra={"error_type": type(error).__name__})
            await asyncio.sleep(RETENTION_EVERY_S)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db = Database(settings)
        ncert = (
            NcertKnowledge(
                settings.ncert_kb_base_url, settings.ncert_kb_api_key.get_secret_value(), settings.ncert_kb_timeout_s
            )
            if settings.ncert_kb_enabled
            else None
        )
        app.state.study_chapters = Chapters(ncert)
        app.state.knowledge, app.state.rag_graph = build_rag(
            settings, app.state.db, app.state.llm, app.state.embeddings, ncert
        )
        # Ollalink's classifier (app/intents): only with INTENT_ROUTER or STUDY_SCOPE on or shadow, and a key.
        classifier = intents or (
            IntentClassifier(
                settings.ollalink_base_url,
                settings.ollalink_api_key.get_secret_value(),
                settings.intent_router_timeout_s,
                settings.intent_min_confidence,
                settings.intent_min_group_confidence,
                scope_min_redirect=settings.scope_min_redirect,
                scope_min_confidence=settings.scope_min_confidence,
                warm_after_s=settings.ollalink_warm_after_s,
            )
            if settings.intent_router_enabled or settings.study_scope_enabled
            else None
        )
        app.state.classifier = classifier  # nudged by signed-in requests (ClassifierWarmMiddleware)
        app.state.chat = ChatService(
            app.state.db,
            settings,
            app.state.rag_graph,
            app.state.generations,
            classifier,
            voice=app.state.voice,
            voice_budget=app.state.voice_budget,
        )
        # Files never delay startup or stop chat: the worker recovers and tests its sandbox in the
        # background, and files stay unavailable until that passes. Tests drive it directly.
        app.state.file_worker = FileWorker(app.state.db, settings, app.state.embeddings)
        if settings.app_env == "test":
            app.state.file_worker.available = app.state.file_worker.configured()
        else:
            await app.state.file_worker.start()
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
        log.info(
            "started",
            extra={
                "env": settings.app_env,
                "llm": app.state.llm.name,
                "knowledge": "ncert" if ncert else "pgvector",
                "intents": settings.intent_router,
                "scope": settings.study_scope,
                # Voice limits on calls at once are counted in this process (app/voice/router.py InFlight).
                "voice": settings.voice_mode if app.state.voice else "off",
                "voice_concurrency": "per process",
            },
        )
        retention = None if settings.app_env == "test" else asyncio.create_task(auth_retention())
        try:
            yield
        finally:
            if retention is not None:
                retention.cancel()
            await app.state.file_worker.stop()
            await app.state.greeting_refresh.stop()
            await app.state.generations.shutdown()
            if ncert is not None:
                await ncert.aclose()
            if classifier is not None:
                await classifier.aclose()
            if app.state.voice is not None:
                await app.state.voice.aclose()
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
    app.state.greeting_refresh = GreetingRefresh()
    app.state.avatar_decodes = asyncio.Semaphore(AVATAR_DECODES)
    app.state.tutor_preview_limiter = SlidingWindowLimiter(limit=60, window_s=60)
    # One active minute a minute is all a client reports; a little slack for retries.
    app.state.activity_limiter = SlidingWindowLimiter(limit=6, window_s=60)
    # Study time: a beat every 30 s per tab plus one at each change; start, pause, resume, end.
    app.state.study_beat_limiter = SlidingWindowLimiter(limit=30, window_s=60)
    app.state.study_action_limiter = SlidingWindowLimiter(limit=30, window_s=60)
    # Unsubscribe links need no sign-in: limited per client address instead.
    app.state.unsubscribe_limiter = SlidingWindowLimiter(limit=30, window_s=60)
    # Voice mode (app/voice): OllaLink's speech, only when VOICE_MODE is not off and it is configured.
    app.state.voice = voice if voice is not None else build_voice(settings)
    app.state.voice_calls = InFlight()
    app.state.voice_budget = SpeechBudget(settings.voice_speech_chars_per_message)

    install_error_handlers(app)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        )
    app.add_middleware(ClassifierWarmMiddleware)
    app.add_middleware(
        RequestContextMiddleware,
        max_body_bytes=settings.max_body_bytes,
        body_limits={
            ("PUT", "/v1/me/avatar"): settings.avatar_max_bytes,
            ("POST", "/v1/files"): MAX_UPLOAD_BYTES,
            ("POST", "/v1/voice/transcriptions"): MAX_AUDIO_BYTES,
        },
    )

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(internal_auth_router)
    app.include_router(conversations_router)
    app.include_router(chat_router)
    app.include_router(learning_router)
    app.include_router(progress_router)
    app.include_router(notifications_router)
    app.include_router(voice_router)
    app.include_router(support_router)
    app.include_router(appearance_router)
    app.include_router(greetings_router)
    app.include_router(files_router)
    app.include_router(study_router)
    return app
