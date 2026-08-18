"""Analytics service — thin orchestration over the analytics repository.

Translates a caller-facing ``window_days`` into concrete time bounds and assembles the summary.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from app.repositories.analytics import AnalyticsRepository


class AnalyticsService:
    def __init__(self, repo: AnalyticsRepository) -> None:
        self.repo = repo

    @staticmethod
    def _since(days: int) -> datetime:
        return datetime.now(UTC) - timedelta(days=days)

    async def summary(
        self, *, organization_id: uuid.UUID, api_id: uuid.UUID | None, days: int
    ) -> dict:
        since = self._since(days)
        summary = await self.repo.summary(
            organization_id=organization_id, api_id=api_id, since=since
        )
        active = await self.repo.active_keys(
            organization_id=organization_id, api_id=api_id, since=since
        )
        return {
            "request_count": summary.request_count,
            "error_count": summary.error_count,
            "error_rate": round(summary.error_rate, 4),
            "avg_latency_ms": summary.avg_latency_ms,
            "p95_latency_ms": summary.p95_latency_ms,
            "active_keys": active,
            "window_days": days,
        }

    async def top_endpoints(
        self, *, organization_id: uuid.UUID, api_id: uuid.UUID | None, days: int, limit: int
    ) -> list[dict]:
        return await self.repo.top_endpoints(
            organization_id=organization_id, api_id=api_id, since=self._since(days), limit=limit
        )

    async def status_breakdown(
        self, *, organization_id: uuid.UUID, api_id: uuid.UUID | None, days: int
    ) -> dict[str, int]:
        return await self.repo.status_breakdown(
            organization_id=organization_id, api_id=api_id, since=self._since(days)
        )

    async def timeseries(
        self, *, organization_id: uuid.UUID, api_id: uuid.UUID | None, days: int
    ) -> list[dict]:
        since_date: date = (datetime.now(UTC) - timedelta(days=days)).date()
        return await self.repo.daily_series(
            organization_id=organization_id, api_id=api_id, since_date=since_date
        )

    async def top_keys(self, *, organization_id: uuid.UUID, days: int, limit: int) -> list[dict]:
        since_date: date = (datetime.now(UTC) - timedelta(days=days)).date()
        return await self.repo.top_keys(
            organization_id=organization_id, since_date=since_date, limit=limit
        )
