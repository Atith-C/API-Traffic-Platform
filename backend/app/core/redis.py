"""Shared async Redis client.

Used for rate-limit counters, auth throttling, and ephemeral state. One connection pool per process.
"""

from __future__ import annotations

import redis.asyncio as redis

from app.core.config import get_settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """Return the process-wide async Redis client (lazy, pooled)."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None
