"""Request-context middleware.

Assigns/propagates a ``request_id`` and ``correlation_id`` for every request, binds them into the
structlog contextvars so all logs in the request are traceable, and logs a structured access line
with the measured latency. The correlation id honours an inbound ``X-Correlation-ID`` header so a
trace can span multiple services (Project B relies on this).
"""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = structlog.get_logger("http.access")

REQUEST_ID_HEADER = b"x-request-id"
CORRELATION_ID_HEADER = b"x-correlation-id"


class RequestContextMiddleware:
    """Pure-ASGI middleware (cheap, runs before routing) for ids + access logging."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        request_id = str(uuid.uuid4())
        correlation_id = headers.get(CORRELATION_ID_HEADER, b"").decode() or request_id

        # Expose ids on scope.state so handlers / error envelope can read them.
        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id
        scope["state"]["correlation_id"] = correlation_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id, correlation_id=correlation_id)

        start = time.perf_counter()
        status_code_holder: dict[str, int] = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_code_holder["status"] = message["status"]
                raw_headers = message.setdefault("headers", [])
                raw_headers.append((b"x-request-id", request_id.encode()))
                raw_headers.append((b"x-correlation-id", correlation_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.info(
                "request",
                method=scope.get("method"),
                path=scope.get("path"),
                status=status_code_holder["status"],
                duration_ms=duration_ms,
            )
            structlog.contextvars.clear_contextvars()
