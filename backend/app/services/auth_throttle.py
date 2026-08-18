"""Simple fixed-window throttle for authentication endpoints (brute-force protection).

A minimal Redis counter keyed by client identity (IP + email). This is deliberately separate from
the pluggable gateway rate-limiter (Milestone 6): auth throttling is a fixed security policy, not a
per-customer configurable one.
"""

from __future__ import annotations

import redis.asyncio as redis

from app.core.config import get_settings
from app.core.errors import RateLimitedError

WINDOW_SECONDS = 60


class AuthThrottle:
    def __init__(self, client: redis.Redis) -> None:
        self._redis = client
        self._limit = get_settings().auth_rate_limit_per_minute

    async def check(self, identity: str) -> None:
        """Increment the window counter for ``identity``; raise if over the limit."""
        key = f"auth_throttle:{identity}"
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, WINDOW_SECONDS)
        if count > self._limit:
            ttl = await self._redis.ttl(key)
            raise RateLimitedError(
                "Too many authentication attempts. Try again later.",
                details={"retry_after": max(ttl, 1)},
            )
