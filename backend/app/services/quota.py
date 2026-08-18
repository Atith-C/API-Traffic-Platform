"""Request-quota enforcement.

Quotas cap total requests per API key over a calendar period (daily/monthly). Counters live in
Redis keyed by ``{api_key_id}:{period}:{bucket}`` where the bucket is the current day or month, with
a TTL that lets the key expire naturally after the period ends. Incrementing is atomic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import redis.asyncio as redis

from app.models.api import QuotaPeriod


@dataclass(frozen=True)
class QuotaCheck:
    period: QuotaPeriod
    limit: int
    used: int

    @property
    def exceeded(self) -> bool:
        return self.used > self.limit


def _bucket_and_ttl(period: QuotaPeriod, now: datetime) -> tuple[str, int]:
    if period == QuotaPeriod.DAILY:
        bucket = now.strftime("%Y-%m-%d")
        end = now.replace(hour=23, minute=59, second=59, microsecond=0)
    else:  # MONTHLY
        bucket = now.strftime("%Y-%m")
        # First day of next month.
        year, month = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
        end = now.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)
    ttl = max(1, int((end - now).total_seconds()))
    return bucket, ttl


class QuotaEnforcer:
    def __init__(self, client: redis.Redis) -> None:
        self._redis = client

    async def consume(
        self,
        *,
        api_key_id: uuid.UUID,
        period: QuotaPeriod,
        limit: int,
        now: datetime | None = None,
    ) -> QuotaCheck:
        """Atomically increment and return usage. Caller decides what to do when ``exceeded``."""
        now = now or datetime.now(UTC)
        bucket, ttl = _bucket_and_ttl(period, now)
        key = f"quota:{api_key_id}:{period}:{bucket}"
        used = await self._redis.incr(key)
        if used == 1:
            await self._redis.expire(key, ttl)
        return QuotaCheck(period=period, limit=limit, used=int(used))

    async def rollback(
        self,
        *,
        api_key_id: uuid.UUID,
        period: QuotaPeriod,
        now: datetime | None = None,
    ) -> None:
        """Give back a consumed unit (used when a later check in the same request rejects it)."""
        now = now or datetime.now(UTC)
        bucket, _ = _bucket_and_ttl(period, now)
        key = f"quota:{api_key_id}:{period}:{bucket}"
        await self._redis.decr(key)
