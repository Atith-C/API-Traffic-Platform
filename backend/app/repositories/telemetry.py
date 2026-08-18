"""Repositories for telemetry & audit tables."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.telemetry import ApiKeyUsage, AuditLog, RequestLog
from app.repositories.base import BaseRepository


class RequestLogRepository(BaseRepository[RequestLog]):
    model = RequestLog

    async def search(
        self,
        *,
        organization_id: uuid.UUID,
        api_id: uuid.UUID | None = None,
        method: str | None = None,
        status_min: int | None = None,
        status_max: int | None = None,
        path_contains: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[RequestLog], int]:
        """Structured, filterable search over request logs (time-range + status + path + method)."""
        conditions = [RequestLog.organization_id == organization_id]
        if api_id is not None:
            conditions.append(RequestLog.api_id == api_id)
        if method is not None:
            conditions.append(RequestLog.method == method.upper())
        if status_min is not None:
            conditions.append(RequestLog.status_code >= status_min)
        if status_max is not None:
            conditions.append(RequestLog.status_code <= status_max)
        if path_contains:
            conditions.append(RequestLog.path.ilike(f"%{path_contains}%"))
        if since is not None:
            conditions.append(RequestLog.created_at >= since)
        if until is not None:
            conditions.append(RequestLog.created_at <= until)

        total = await self.session.scalar(
            select(func.count()).select_from(RequestLog).where(*conditions)
        )
        result = await self.session.execute(
            select(RequestLog)
            .where(*conditions)
            .order_by(RequestLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)


class AuditLogRepository(BaseRepository[AuditLog]):
    model = AuditLog

    async def list_for_org(
        self, *, organization_id: uuid.UUID, limit: int, offset: int
    ) -> list[AuditLog]:
        result = await self.session.execute(
            select(AuditLog)
            .where(AuditLog.organization_id == organization_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())


class ApiKeyUsageRepository(BaseRepository[ApiKeyUsage]):
    model = ApiKeyUsage

    async def increment(
        self,
        *,
        api_key_id: uuid.UUID,
        api_id: uuid.UUID,
        usage_date: date,
        is_error: bool,
    ) -> None:
        """Atomic per-key/day upsert-and-increment (Postgres ON CONFLICT DO UPDATE)."""
        stmt = pg_insert(ApiKeyUsage).values(
            api_key_id=api_key_id,
            api_id=api_id,
            usage_date=usage_date,
            request_count=1,
            error_count=1 if is_error else 0,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_api_key_usage_key_date",
            set_={
                "request_count": ApiKeyUsage.request_count + 1,
                "error_count": ApiKeyUsage.error_count + (1 if is_error else 0),
            },
        )
        await self.session.execute(stmt)
