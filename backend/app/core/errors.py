"""Centralized error handling.

Every error leaves the API as a consistent JSON envelope::

    {"error": {"code": "not_found", "message": "...", "details": {...}, "request_id": "..."}}

Domain code raises :class:`AppError` subclasses; route handlers never build error responses by hand.
Stack traces are never exposed to clients (OWASP). Unexpected exceptions become a generic 500.
"""

from __future__ import annotations

from typing import Any

import orjson
import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException

HTTP_422 = status.HTTP_422_UNPROCESSABLE_CONTENT


class _ORJSONResponse(Response):
    """Minimal orjson JSON response (FastAPI deprecated its built-in ORJSONResponse)."""

    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return orjson.dumps(content)


logger = structlog.get_logger(__name__)


class AppError(Exception):
    """Base class for all expected, client-facing application errors."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "bad_request"
    message: str = "Bad request."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details or {}
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "Resource not found."


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "Resource already exists."


class ValidationAppError(AppError):
    status_code = HTTP_422
    code = "validation_error"
    message = "Validation failed."


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthenticated"
    message = "Authentication required."


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"
    message = "You do not have permission to perform this action."


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"
    message = "Rate limit exceeded."


class QuotaExceededError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "quota_exceeded"
    message = "Quota exceeded."


class UpstreamError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "upstream_error"
    message = "Upstream service returned an error or is unreachable."


def _safe_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Return JSON-serializable validation errors.

    Pydantic's ``errors()`` can embed exception instances (e.g. in ``ctx``) that aren't JSON
    serializable, so we keep only safe fields and stringify the rest.
    """
    safe: list[dict[str, Any]] = []
    for err in exc.errors():
        item: dict[str, Any] = {
            "type": err.get("type"),
            "loc": [str(part) for part in err.get("loc", ())],
            "msg": err.get("msg"),
        }
        if (ctx := err.get("ctx")) is not None:
            item["ctx"] = {k: str(v) for k, v in ctx.items()}
        safe.append(item)
    return safe


def _envelope(
    *, code: str, message: str, details: dict[str, Any], request_id: str | None
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id,
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    """Attach handlers that render every error as the standard envelope."""

    def _request_id(request: Request) -> str | None:
        return getattr(request.state, "request_id", None)

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> _ORJSONResponse:
        response = _ORJSONResponse(
            status_code=exc.status_code,
            content=_envelope(
                code=exc.code,
                message=exc.message,
                details=exc.details,
                request_id=_request_id(request),
            ),
        )
        # 429s advertise Retry-After when the domain provides one.
        if retry_after := exc.details.get("retry_after"):
            response.headers["Retry-After"] = str(retry_after)
        return response

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(request: Request, exc: RequestValidationError) -> _ORJSONResponse:
        return _ORJSONResponse(
            status_code=HTTP_422,
            content=_envelope(
                code="validation_error",
                message="Request validation failed.",
                details={"errors": _safe_validation_errors(exc)},
                request_id=_request_id(request),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(request: Request, exc: StarletteHTTPException) -> _ORJSONResponse:
        return _ORJSONResponse(
            status_code=exc.status_code,
            content=_envelope(
                code="http_error",
                message=str(exc.detail),
                details={},
                request_id=_request_id(request),
            ),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> _ORJSONResponse:
        # Log the full detail server-side; never leak internals to the client.
        logger.error(
            "unhandled_exception",
            exc_info=exc,
            path=request.url.path,
            request_id=_request_id(request),
        )
        return _ORJSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope(
                code="internal_error",
                message="An internal error occurred.",
                details={},
                request_id=_request_id(request),
            ),
        )
