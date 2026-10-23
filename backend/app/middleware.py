"""Pure ASGI middleware: request id, access log and request body size limit.

Pure ASGI (not BaseHTTPMiddleware) so streaming responses and client-disconnect
cancellation pass through untouched.
"""

from __future__ import annotations

import json
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import error_body
from app.logging import get_logger, request_id_var, user_id_var

log = get_logger("app.access")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class _BodyTooLarge(Exception):
    pass


class RequestContextMiddleware:
    def __init__(
        self, app: ASGIApp, max_body_bytes: int, body_limits: dict[tuple[str, str], int] | None = None
    ) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        # (method, path) -> a larger limit for the few routes that take files. Everything else
        # keeps max_body_bytes.
        self.body_limits = body_limits or {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        incoming = headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex
        rid_token = request_id_var.set(request_id)
        uid_token = user_id_var.set("-")
        started = time.perf_counter()
        status = {"code": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], (b"x-request-id", request_id.encode())]
            await send(message)

        limit = self.body_limits.get((scope.get("method", ""), scope.get("path", "")), self.max_body_bytes)
        try:
            declared = headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > limit:
                await self._too_large(send_wrapper)
                return

            received = {"bytes": 0}

            async def limited_receive() -> Message:
                message = await receive()
                if message["type"] == "http.request":
                    received["bytes"] += len(message.get("body", b""))
                    if received["bytes"] > limit:
                        raise _BodyTooLarge
                return message

            try:
                await self.app(scope, limited_receive, send_wrapper)
            except _BodyTooLarge:
                await self._too_large(send_wrapper)
        finally:
            log.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status["code"],
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            user_id_var.reset(uid_token)
            request_id_var.reset(rid_token)

    @staticmethod
    async def _too_large(send: Send) -> None:
        body = json.dumps(error_body("payload_too_large", "The request body is too large.")).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})


class ClassifierWarmMiddleware:
    """Each signed-in request nudges Ollalink's classifier (IntentClassifier.nudge), which sends one small
    warm-up only after a quiet spell, so a student's next message isn't slow. Pure ASGI: streams and
    client disconnects pass through untouched. Nothing when there is no classifier."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            classifier = getattr(scope["app"].state, "classifier", None) if "app" in scope else None
            if classifier is not None and any(name == b"authorization" for name, _ in scope["headers"]):
                classifier.nudge()
        await self.app(scope, receive, send)
