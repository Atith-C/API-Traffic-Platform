"""Gateway service — the real traffic-management path.

For each proxied call it: (1) authenticates the API key, (2) resolves the target API + version and
its upstream, (3) enforces the rate-limit rule and quotas, (4) forwards the request upstream while
measuring latency and sizes, and (5) returns a structured outcome the route serializes and the
logging layer (Milestone 7) records + emits as telemetry.

Kept framework-agnostic: the route passes primitives (method, path, headers, body), not a FastAPI
Request, so this is unit-testable and reusable.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
import redis.asyncio as redis
import structlog

from app.core.config import Settings, get_settings
from app.core.errors import (
    AuthenticationError,
    NotFoundError,
    QuotaExceededError,
    RateLimitedError,
    UpstreamError,
)
from app.core.security import hash_token
from app.models.api_key import ApiKey
from app.repositories.api import ApiVersionRepository, QuotaRepository, RateLimitRuleRepository
from app.repositories.api_key import ApiKeyRepository
from app.services.quota import QuotaEnforcer
from app.services.rate_limit import RateLimitSpec, get_limiter

logger = structlog.get_logger(__name__)

# Hop-by-hop headers must not be forwarded (RFC 7230), plus auth headers we terminate here.
_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
    "authorization",
    "x-api-key",
}


@dataclass(frozen=True)
class GatewayResponse:
    status_code: int
    headers: dict[str, str]
    content: bytes


@dataclass
class GatewayOutcome:
    """Everything about a proxied request — returned to the route and consumed by logging (M7)."""

    api_key_id: uuid.UUID
    api_id: uuid.UUID
    api_version_id: uuid.UUID
    organization_id: uuid.UUID
    method: str
    path: str
    status_code: int
    latency_ms: float
    request_bytes: int
    response_bytes: int
    client_ip: str
    upstream_url: str
    timestamp: datetime
    response: GatewayResponse
    rate_limit: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class IncomingRequest:
    method: str
    api_slug: str
    version: str
    upstream_path: str
    query_string: str
    headers: dict[str, str]
    body: bytes
    client_ip: str


class GatewayService:
    def __init__(
        self,
        *,
        api_keys: ApiKeyRepository,
        versions: ApiVersionRepository,
        rate_limits: RateLimitRuleRepository,
        quotas: QuotaRepository,
        redis_client: redis.Redis,
        http_client: httpx.AsyncClient,
        settings: Settings | None = None,
    ) -> None:
        self.api_keys = api_keys
        self.versions = versions
        self.rate_limits = rate_limits
        self.quotas = quotas
        self.redis = redis_client
        self.http = http_client
        self.settings = settings or get_settings()

    async def authenticate(self, presented_key: str | None) -> ApiKey:
        if not presented_key:
            raise AuthenticationError("Missing API key.", code="missing_api_key")
        key = await self.api_keys.get_by_hash(hash_token(presented_key))
        if key is None or not key.is_valid_at(datetime.now(UTC)):
            raise AuthenticationError("Invalid or expired API key.", code="invalid_api_key")
        if not key.api.is_active:
            raise AuthenticationError("The target API is disabled.", code="api_disabled")
        return key

    async def handle(self, req: IncomingRequest, presented_key: str | None) -> GatewayOutcome:
        key = await self.authenticate(presented_key)
        api = key.api

        if api.slug != req.api_slug:
            # The key is not for the API named in the path.
            raise AuthenticationError(
                "API key does not authorize this API.", code="key_api_mismatch"
            )

        version = await self.versions.get_active(api_id=api.id, version=req.version)
        if version is None or not version.is_active:
            raise NotFoundError(f"No active version '{req.version}' for this API.")

        rate_info = await self._enforce_rate_limit(api_id=api.id, api_key_id=key.id)
        consumed = await self._enforce_quota(api_id=api.id, api_key_id=key.id)

        try:
            response, request_bytes, latency_ms = await self._forward(
                version.upstream_base_url, req
            )
        except Exception:
            # Give back quota units for requests we never actually served upstream.
            await self._rollback_quota(api_key_id=key.id, consumed=consumed)
            raise

        return GatewayOutcome(
            api_key_id=key.id,
            api_id=api.id,
            api_version_id=version.id,
            organization_id=key.organization_id,
            method=req.method,
            path=req.upstream_path,
            status_code=response.status_code,
            latency_ms=latency_ms,
            request_bytes=request_bytes,
            response_bytes=len(response.content),
            client_ip=req.client_ip,
            upstream_url=version.upstream_base_url,
            timestamp=datetime.now(UTC),
            response=response,
            rate_limit=rate_info,
        )

    async def _enforce_rate_limit(
        self, *, api_id: uuid.UUID, api_key_id: uuid.UUID
    ) -> dict[str, int]:
        rule = await self.rate_limits.get_for_api(api_id)
        if rule is None:
            return {}
        limiter = get_limiter(rule.algorithm)
        result = await limiter.check(
            self.redis,
            key=f"{api_id}:{api_key_id}",
            spec=RateLimitSpec(
                requests=rule.requests, window_seconds=rule.window_seconds, burst=rule.burst
            ),
        )
        if not result.allowed:
            raise RateLimitedError(
                "Rate limit exceeded for this API key.",
                details={"retry_after": result.retry_after, "limit": result.limit},
            )
        return {"limit": result.limit, "remaining": result.remaining}

    async def _enforce_quota(self, *, api_id: uuid.UUID, api_key_id: uuid.UUID) -> list:
        enforcer = QuotaEnforcer(self.redis)
        consumed = []
        for quota in await self.quotas.list_for_api(api_id):
            check = await enforcer.consume(
                api_key_id=api_key_id, period=quota.period, limit=quota.max_requests
            )
            consumed.append(quota.period)
            if check.exceeded:
                await self._rollback_quota(api_key_id=api_key_id, consumed=consumed)
                raise QuotaExceededError(
                    f"{quota.period} quota of {quota.max_requests} requests exceeded.",
                    details={"period": str(quota.period), "limit": quota.max_requests},
                )
        return consumed

    async def _rollback_quota(self, *, api_key_id: uuid.UUID, consumed: list) -> None:
        enforcer = QuotaEnforcer(self.redis)
        for period in consumed:
            await enforcer.rollback(api_key_id=api_key_id, period=period)

    async def _forward(
        self, upstream_base_url: str, req: IncomingRequest
    ) -> tuple[GatewayResponse, int, float]:
        url = upstream_base_url.rstrip("/")
        if req.upstream_path:
            url = f"{url}/{req.upstream_path.lstrip('/')}"
        if req.query_string:
            url = f"{url}?{req.query_string}"

        forward_headers = {k: v for k, v in req.headers.items() if k.lower() not in _HOP_BY_HOP}
        request_bytes = len(req.body)

        start = time.perf_counter()
        try:
            upstream = await self.http.request(
                req.method, url, headers=forward_headers, content=req.body
            )
        except httpx.TimeoutException as exc:
            raise UpstreamError("Upstream request timed out.", code="upstream_timeout") from exc
        except httpx.HTTPError as exc:
            raise UpstreamError("Failed to reach the upstream service.") from exc
        latency_ms = round((time.perf_counter() - start) * 1000, 2)

        response_headers = {
            k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP
        }
        return (
            GatewayResponse(
                status_code=upstream.status_code,
                headers=response_headers,
                content=upstream.content,
            ),
            request_bytes,
            latency_ms,
        )
