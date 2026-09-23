"""Application factory.

    uvicorn app.main:create_app --factory --host 127.0.0.1 --port 4000

Tests call `create_app(settings, llm=..., email_sender=...)` to inject fakes.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.emails import EmailSender, build_email_sender
from app.auth.router import router as auth_router
from app.auth.security import Passwords
from app.chat.router import router as chat_router
from app.chat.service import ChatService
from app.chat.streams import ActiveGenerations
from app.conversations.router import router as conversations_router
from app.db.session import Database
from app.errors import install_error_handlers
from app.health import router as health_router
from app.llm.base import LLMProvider
from app.llm.factory import build_llm
from app.logging import configure_logging, get_logger
from app.middleware import RequestContextMiddleware
from app.settings import Settings, get_settings

log = get_logger("app")


def create_app(
    settings: Settings | None = None,
    *,
    llm: LLMProvider | None = None,
    email_sender: EmailSender | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    settings.validate_for_env()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db = Database(settings)
        app.state.chat = ChatService(app.state.db, settings, app.state.llm, app.state.generations)
        try:
            await app.state.chat.sweep_all_stale()
        except Exception as error:  # noqa: BLE001 - start anyway; /ready reports the database
            log.warning("startup sweep skipped", extra={"error_type": type(error).__name__})
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
    app.state.email_sender = email_sender or build_email_sender(settings)
    app.state.passwords = Passwords(settings)
    app.state.generations = ActiveGenerations()

    install_error_handlers(app)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        )
    app.add_middleware(RequestContextMiddleware, max_body_bytes=settings.max_body_bytes)

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(conversations_router)
    app.include_router(chat_router)
    return app
