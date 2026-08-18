"""Request-logging service.

Persists a gateway request as (1) a raw ``request_logs`` row, (2) a per-key/day ``api_key_usage``
increment, and (3) a ``RequestLogEvent`` in the telemetry outbox — all in the caller's session, so
they commit atomically with each other. Project B consumes the outbox stream (or the raw table).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telemetry import RequestLog
from app.repositories.telemetry import ApiKeyUsageRepository
from app.services.gateway import GatewayOutcome
from app.services.telemetry.emitter import TelemetryEmitter, get_emitter
from app.telemetry.events import RequestLogEvent


class RequestLogService:
    def __init__(self, session: AsyncSession, *, emitter: TelemetryEmitter | None = None) -> None:
        self.session = session
        self.emitter = emitter or get_emitter()

    async def record(self, outcome: GatewayOutcome) -> None:
        self.session.add(
            RequestLog(
                organization_id=outcome.organization_id,
                api_id=outcome.api_id,
                api_version_id=outcome.api_version_id,
                api_key_id=outcome.api_key_id,
                method=outcome.method,
                path=outcome.path,
                status_code=outcome.status_code,
                latency_ms=outcome.latency_ms,
                request_bytes=outcome.request_bytes,
                response_bytes=outcome.response_bytes,
                client_ip=outcome.client_ip,
                upstream_url=outcome.upstream_url,
            )
        )
        await ApiKeyUsageRepository(self.session).increment(
            api_key_id=outcome.api_key_id,
            api_id=outcome.api_id,
            usage_date=outcome.timestamp.date(),
            is_error=outcome.status_code >= 500,
        )
        await self.emitter.emit(
            self.session,
            RequestLogEvent(
                occurred_at=outcome.timestamp,
                organization_id=outcome.organization_id,
                api_id=outcome.api_id,
                api_version_id=outcome.api_version_id,
                api_key_id=outcome.api_key_id,
                method=outcome.method,
                path=outcome.path,
                status_code=outcome.status_code,
                latency_ms=outcome.latency_ms,
                request_bytes=outcome.request_bytes,
                response_bytes=outcome.response_bytes,
                client_ip=outcome.client_ip,
                upstream_url=outcome.upstream_url,
            ),
        )
