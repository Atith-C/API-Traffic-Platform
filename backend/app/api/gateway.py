"""The gateway entrypoint: ``/gw/{api_slug}/{version}/{upstream_path}``.

Authenticates by API key (``Authorization: Bearer <key>`` or ``X-API-Key``), enforces rate limits +
quotas, forwards to the configured upstream, and returns the upstream response verbatim (status,
safe headers, body) with rate-limit headers added. A structured log records each proxied request;
durable request logs + telemetry are added in Milestone 7 via the same :class:`GatewayOutcome`.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request, Response

from app.api.deps import GatewayServiceDep, SessionDep, client_ip
from app.services.gateway import IncomingRequest
from app.services.request_log import RequestLogService

router = APIRouter(prefix="/gw", tags=["gateway"])
logger = structlog.get_logger("gateway")

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


def _extract_api_key(request: Request) -> str | None:
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-api-key")


@router.api_route("/{api_slug}/{version}/{upstream_path:path}", methods=_METHODS)
async def proxy(
    api_slug: str,
    version: str,
    upstream_path: str,
    request: Request,
    service: GatewayServiceDep,
    session: SessionDep,
) -> Response:
    body = await request.body()
    incoming = IncomingRequest(
        method=request.method,
        api_slug=api_slug,
        version=version,
        upstream_path=upstream_path,
        query_string=request.url.query,
        headers=dict(request.headers),
        body=body,
        client_ip=client_ip(request),
    )
    outcome = await service.handle(incoming, _extract_api_key(request))

    # Persist the request log + per-key usage + telemetry event in this request's transaction.
    await RequestLogService(session).record(outcome)

    logger.info(
        "gateway_request",
        api_id=str(outcome.api_id),
        status=outcome.status_code,
        latency_ms=outcome.latency_ms,
        method=outcome.method,
        path=outcome.path,
    )

    headers = dict(outcome.response.headers)
    if outcome.rate_limit:
        headers["X-RateLimit-Limit"] = str(outcome.rate_limit.get("limit", ""))
        headers["X-RateLimit-Remaining"] = str(outcome.rate_limit.get("remaining", ""))
    headers["X-Gateway-Latency-Ms"] = str(outcome.latency_ms)

    return Response(
        content=outcome.response.content,
        status_code=outcome.status_code,
        headers=headers,
    )
