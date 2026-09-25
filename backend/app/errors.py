"""Typed application errors and the single JSON error envelope.

Every error response has the shape `{"error": {"code", "message", "requestId"}}`.
Internal details (SQL, provider responses, stack traces) are logged, never returned.
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import exc as sa_exc
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging import get_logger, request_id_var

log = get_logger("app.errors")


class AppError(Exception):
    status_code = 400
    code = "bad_request"
    message = "The request could not be processed."
    retryable = False

    def __init__(
        self, message: str | None = None, *, code: str | None = None, fields: list[dict] | None = None
    ) -> None:
        super().__init__(message or self.message)
        if message:
            self.message = message
        if code:
            self.code = code
        # Field paths and machine-readable reasons, like a request validation error: never values.
        self.fields = fields


class Unauthorized(AppError):
    status_code, code, message = 401, "unauthorized", "Authentication required."


class InvalidCredentials(AppError):
    status_code, code, message = 401, "invalid_credentials", "Invalid email or password."


class EmailNotVerified(AppError):
    status_code, code, message = 403, "email_not_verified", "Verify your email address first."


class InvalidCode(AppError):
    status_code, code, message = 400, "invalid_code", "The code is invalid or has expired."


class NotFound(AppError):
    status_code, code, message = 404, "not_found", "Not found."


class Conflict(AppError):
    status_code, code, message = 409, "conflict", "The request conflicts with the current state."


class VersionConflict(AppError):
    """A write named a version that is no longer current: someone (another tab or device)
    changed the resource first. The client reloads and re-applies its change."""

    status_code, code, message = 409, "version_conflict", "This was changed elsewhere. Reload and try again."

    def __init__(self, current: dict | None = None) -> None:
        super().__init__()
        # The resource as it is now (the same body a GET returns), so the client can rebase
        # its own pending changes without another request.
        self.current = current


class UnsupportedMediaType(AppError):
    status_code, code, message = 415, "unsupported_media_type", "This file type is not supported."


class RateLimited(AppError):
    status_code, code, message = 429, "rate_limited", "Too many requests. Please try again later."
    retryable = True


class PayloadTooLarge(AppError):
    status_code, code, message = 413, "payload_too_large", "The request body is too large."


class ValidationFailed(AppError):
    status_code, code, message = 422, "validation_error", "The request is invalid."


class ServiceUnavailable(AppError):
    status_code, code, message = 503, "service_unavailable", "The service is temporarily unavailable."
    retryable = True


# Exceptions that mean "the database could not be reached", as opposed to a bug.
DB_UNAVAILABLE = (
    sa_exc.OperationalError,
    sa_exc.InterfaceError,
    sa_exc.TimeoutError,
    ConnectionError,
    OSError,
    asyncio.TimeoutError,
)


def is_db_unavailable(error: BaseException) -> bool:
    if isinstance(error, sa_exc.DBAPIError) and error.connection_invalidated:
        return True
    return isinstance(error, DB_UNAVAILABLE)


def error_body(code: str, message: str, **extra) -> dict:
    return {"error": {"code": code, "message": message, "requestId": request_id_var.get(), **extra}}


def _response(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content=error_body(code, message, **extra))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, error: AppError) -> JSONResponse:
        extra: dict = {"fields": error.fields} if error.fields else {}
        if getattr(error, "current", None) is not None:
            extra["current"] = error.current
        return _response(error.status_code, error.code, error.message, **extra)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, error: RequestValidationError) -> JSONResponse:
        # Field paths and reasons only; never echo the submitted values back.
        fields = [
            {"field": ".".join(str(p) for p in e.get("loc", ())[1:]), "reason": e.get("type")} for e in error.errors()
        ]
        return _response(422, "validation_error", "The request is invalid.", fields=fields)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, error: StarletteHTTPException) -> JSONResponse:
        codes = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized"}
        return _response(error.status_code, codes.get(error.status_code, "http_error"), str(error.detail))

    async def _db_unavailable(_: Request, error: Exception) -> JSONResponse:
        log.error("database unavailable", extra={"error_type": type(error).__name__})
        return _response(503, "service_unavailable", ServiceUnavailable.message)

    # Registered per class (not only under `Exception`): Starlette treats these as
    # handled, whereas the catch-all 500 handler re-raises after responding.
    for exc_class in DB_UNAVAILABLE:
        app.add_exception_handler(exc_class, _db_unavailable)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, error: Exception) -> JSONResponse:
        if is_db_unavailable(error):
            return await _db_unavailable(request, error)
        log.exception("unhandled error", extra={"error_type": type(error).__name__})
        return _response(500, "internal_error", "Something went wrong. Please try again.")
