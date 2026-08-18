"""Rate-limiter strategy interface and shared result type.

Strategies are pluggable (Strategy pattern) and all backed by atomic Redis Lua scripts so the
check-and-increment is race-free across processes. A new algorithm only needs to implement
:class:`RateLimiter`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import redis.asyncio as redis


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int  # seconds until the caller may retry (0 when allowed)


@dataclass(frozen=True)
class RateLimitSpec:
    """Normalized rate-limit parameters passed to a strategy."""

    requests: int
    window_seconds: int
    burst: int | None = None


class RateLimiter(Protocol):
    async def check(self, client: redis.Redis, *, key: str, spec: RateLimitSpec) -> RateLimitResult:
        """Atomically account for one request against ``key`` and report whether it is allowed."""
        ...
