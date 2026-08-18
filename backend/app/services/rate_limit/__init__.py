"""Pluggable rate limiting.

Public surface: :func:`get_limiter` maps a :class:`RateLimitAlgorithm` to a strategy instance.
"""

from __future__ import annotations

from app.models.api import RateLimitAlgorithm
from app.services.rate_limit.base import RateLimiter, RateLimitResult, RateLimitSpec
from app.services.rate_limit.strategies import (
    FixedWindowLimiter,
    SlidingWindowLimiter,
    TokenBucketLimiter,
)

_LIMITERS: dict[RateLimitAlgorithm, RateLimiter] = {
    RateLimitAlgorithm.FIXED_WINDOW: FixedWindowLimiter(),
    RateLimitAlgorithm.SLIDING_WINDOW: SlidingWindowLimiter(),
    RateLimitAlgorithm.TOKEN_BUCKET: TokenBucketLimiter(),
}


def get_limiter(algorithm: RateLimitAlgorithm) -> RateLimiter:
    return _LIMITERS[algorithm]


__all__ = [
    "RateLimitResult",
    "RateLimitSpec",
    "RateLimiter",
    "get_limiter",
]
