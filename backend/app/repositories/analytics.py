"""Analytics queries and the daily rollup.

Summary / top-endpoint / status queries read the raw ``request_logs`` (fast via the
``(api_id, created_at)`` / ``(organization_id, created_at)`` indexes). The time-series query reads
the pre-aggregated ``daily_usage`` rollup. ``rollup_daily`` (re)builds a day idempotently.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from sqlalchemy import and_, case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics import DailyUsage
from app.models.telemetry import ApiKeyUsage, RequestLog


@dataclass(frozen=True)
class Summary:
    request_count: int
    error_count: int
    error_rate: float
    avg_latency_ms: float
    p95_latency_ms: float


class AnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _scope(self, organization_id: uuid.UUID, api_id: uuid.UUID | None, since: datetime):
        conditions = [
            RequestLog.organization_id == organization_id,
            RequestLog.created_at >= since,
        ]
        if api_id is not None:
            conditions.append(RequestLog.api_id == api_id)
        return and_(*conditions)

    async def summary(
        self, *, organization_id: uuid.UUID, api_id: uuid.UUID | None, since: datetime
    ) -> Summary:
        scope = self._scope(organization_id, api_id, since)
        errors = func.count().filter(RequestLog.status_code >= 500)
        row = (
            await self.session.execute(
                select(
                    func.count().label("total"),
                    errors.label("errors"),
                    func.coalesce(func.avg(RequestLog.latency_ms), 0.0).label("avg"),
                    func.coalesce(
                        func.percentile_cont(0.95).within_group(RequestLog.latency_ms), 0.0
                    ).label("p95"),
                ).where(scope)
            )
        ).one()
        total = int(row.total)
        errs = int(row.errors)
        return Summary(
            request_count=total,
            error_count=errs,
            error_rate=(errs / total) if total else 0.0,
            avg_latency_ms=round(float(row.avg), 2),
            p95_latency_ms=round(float(row.p95), 2),
        )

    async def top_endpoints(
        self,
        *,
        organization_id: uuid.UUID,
        api_id: uuid.UUID | None,
        since: datetime,
        limit: int,
    ) -> list[dict]:
        scope = self._scope(organization_id, api_id, since)
        rows = (
            await self.session.execute(
                select(
                    RequestLog.path,
                    func.count().label("cnt"),
                    func.coalesce(func.avg(RequestLog.latency_ms), 0.0).label("avg"),
                )
                .where(scope)
                .group_by(RequestLog.path)
                .order_by(func.count().desc())
                .limit(limit)
            )
        ).all()
        return [
            {
                "path": r.path,
                "request_count": int(r.cnt),
                "avg_latency_ms": round(float(r.avg), 2),
            }
            for r in rows
        ]

    async def status_breakdown(
        self, *, organization_id: uuid.UUID, api_id: uuid.UUID | None, since: datetime
    ) -> dict[str, int]:
        scope = self._scope(organization_id, api_id, since)
        klass = case(
            (RequestLog.status_code < 200, "1xx"),
            (RequestLog.status_code < 300, "2xx"),
            (RequestLog.status_code < 400, "3xx"),
            (RequestLog.status_code < 500, "4xx"),
            else_="5xx",
        ).label("klass")
        rows = (
            await self.session.execute(select(klass, func.count()).where(scope).group_by(klass))
        ).all()
        return {r[0]: int(r[1]) for r in rows}

    async def active_keys(
        self, *, organization_id: uuid.UUID, api_id: uuid.UUID | None, since: datetime
    ) -> int:
        scope = self._scope(organization_id, api_id, since)
        return int(
            await self.session.scalar(
                select(func.count(func.distinct(RequestLog.api_key_id))).where(scope)
            )
            or 0
        )

    async def daily_series(
        self,
        *,
        organization_id: uuid.UUID,
        api_id: uuid.UUID | None,
        since_date: date,
    ) -> list[dict]:
        conditions = [
            DailyUsage.organization_id == organization_id,
            DailyUsage.usage_date >= since_date,
        ]
        if api_id is not None:
            conditions.append(DailyUsage.api_id == api_id)
        rows = (
            await self.session.execute(
                select(
                    DailyUsage.usage_date,
                    func.sum(DailyUsage.request_count).label("requests"),
                    func.sum(DailyUsage.error_count).label("errors"),
                    func.sum(DailyUsage.total_latency_ms).label("latency"),
                )
                .where(and_(*conditions))
                .group_by(DailyUsage.usage_date)
                .order_by(DailyUsage.usage_date.asc())
            )
        ).all()
        series = []
        for r in rows:
            requests = int(r.requests or 0)
            series.append(
                {
                    "date": r.usage_date.isoformat(),
                    "request_count": requests,
                    "error_count": int(r.errors or 0),
                    "avg_latency_ms": round(float(r.latency or 0) / requests, 2)
                    if requests
                    else 0.0,
                }
            )
        return series

    async def top_keys(
        self, *, organization_id: uuid.UUID, since_date: date, limit: int
    ) -> list[dict]:
        rows = (
            await self.session.execute(
                select(
                    ApiKeyUsage.api_key_id,
                    func.sum(ApiKeyUsage.request_count).label("requests"),
                    func.sum(ApiKeyUsage.error_count).label("errors"),
                )
                .where(ApiKeyUsage.usage_date >= since_date)
                .group_by(ApiKeyUsage.api_key_id)
                .order_by(func.sum(ApiKeyUsage.request_count).desc())
                .limit(limit)
            )
        ).all()
        return [
            {
                "api_key_id": str(r.api_key_id),
                "request_count": int(r.requests or 0),
                "error_count": int(r.errors or 0),
            }
            for r in rows
        ]

    async def rollup_daily(self, target_date: date) -> int:
        """Idempotently rebuild ``daily_usage`` for ``target_date`` from ``request_logs``."""
        # ``created_at`` is timezone-aware (UTC); bound the day in UTC so the comparison matches.
        start = datetime.combine(target_date, time.min, tzinfo=UTC)
        end = datetime.combine(target_date, time.max, tzinfo=UTC)

        # Recompute this day from scratch (delete + insert) so the rollup is idempotent.
        await self.session.execute(delete(DailyUsage).where(DailyUsage.usage_date == target_date))
        rows = (
            await self.session.execute(
                select(
                    RequestLog.organization_id,
                    RequestLog.api_id,
                    func.count().label("requests"),
                    func.count().filter(RequestLog.status_code >= 500).label("errors"),
                    func.coalesce(func.sum(RequestLog.latency_ms), 0.0).label("latency"),
                    func.coalesce(func.sum(RequestLog.request_bytes), 0).label("req_bytes"),
                    func.coalesce(func.sum(RequestLog.response_bytes), 0).label("resp_bytes"),
                )
                .where(and_(RequestLog.created_at >= start, RequestLog.created_at <= end))
                .group_by(RequestLog.organization_id, RequestLog.api_id)
            )
        ).all()
        for r in rows:
            self.session.add(
                DailyUsage(
                    organization_id=r.organization_id,
                    api_id=r.api_id,
                    usage_date=target_date,
                    request_count=int(r.requests),
                    error_count=int(r.errors),
                    total_latency_ms=float(r.latency),
                    total_request_bytes=int(r.req_bytes),
                    total_response_bytes=int(r.resp_bytes),
                )
            )
        await self.session.flush()
        return len(rows)
