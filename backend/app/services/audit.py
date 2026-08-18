"""Audit-logging service.

Records an administrative action as an ``audit_logs`` row plus an ``AuditLogEvent`` in the telemetry
outbox, atomically in the caller's session. Used for security-sensitive mutations (API key
create/revoke/rotate, membership changes, ...).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telemetry import AuditLog
from app.services.telemetry.emitter import TelemetryEmitter, get_emitter
from app.telemetry.events import AuditLogEvent


class AuditLogService:
    def __init__(self, session: AsyncSession, *, emitter: TelemetryEmitter | None = None) -> None:
        self.session = session
        self.emitter = emitter or get_emitter()

    async def record(
        self,
        *,
        action: str,
        resource_type: str,
        organization_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None,
        resource_id: uuid.UUID | None = None,
        ip: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        from datetime import UTC, datetime

        meta = metadata or {}
        self.session.add(
            AuditLog(
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                ip=ip,
                audit_metadata=meta,
            )
        )
        await self.emitter.emit(
            self.session,
            AuditLogEvent(
                occurred_at=datetime.now(UTC),
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                ip=ip,
                metadata=meta,
            ),
        )
