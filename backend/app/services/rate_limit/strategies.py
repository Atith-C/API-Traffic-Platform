"""Concrete rate-limiting strategies, each backed by an atomic Redis Lua script.

- **Fixed window**: one counter per fixed time bucket. Cheap; allows bursts at window edges.
- **Sliding window (log)**: a sorted set of request timestamps; accurate but more memory.
- **Token bucket**: smooth rate with burst capacity; the most flexible.

All scripts return ``{allowed(0|1), remaining, retry_after_ms}`` so the accounting is race-free.
"""

from __future__ import annotations

import time

import redis.asyncio as redis

from app.services.rate_limit.base import RateLimiter, RateLimitResult, RateLimitSpec

# ---------------------------------------------------------------------------
# Fixed window
# ---------------------------------------------------------------------------
_FIXED_WINDOW_LUA = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local current = redis.call('INCR', key)
if current == 1 then
  redis.call('PEXPIRE', key, window * 1000)
end
local ttl = redis.call('PTTL', key)
if current > limit then
  return {0, 0, ttl}
end
return {1, limit - current, 0}
"""


# ---------------------------------------------------------------------------
# Sliding window log
# ---------------------------------------------------------------------------
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now_ms - window_ms)
local count = redis.call('ZCARD', key)
if count < limit then
  redis.call('ZADD', key, now_ms, member)
  redis.call('PEXPIRE', key, window_ms)
  return {1, limit - count - 1, 0}
end
-- Blocked: retry when the oldest entry falls out of the window.
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local retry = window_ms
if oldest[2] then
  retry = (tonumber(oldest[2]) + window_ms) - now_ms
end
return {0, 0, retry}
"""


# ---------------------------------------------------------------------------
# Token bucket
# ---------------------------------------------------------------------------
_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])  -- tokens per second
local now = tonumber(ARGV[3])          -- seconds (float)
local ttl_ms = tonumber(ARGV[4])
local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then
  tokens = capacity
  ts = now
end
local delta = math.max(0, now - ts)
tokens = math.min(capacity, tokens + delta * refill_rate)
local allowed = 0
local retry = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  retry = math.ceil(((1 - tokens) / refill_rate) * 1000)
end
redis.call('HSET', key, 'tokens', tokens, 'ts', now)
redis.call('PEXPIRE', key, ttl_ms)
return {allowed, math.floor(tokens), retry}
"""


def _ms_to_seconds_ceil(ms: int) -> int:
    return max(0, -(-int(ms) // 1000))  # ceil division


class FixedWindowLimiter(RateLimiter):
    async def check(self, client: redis.Redis, *, key: str, spec: RateLimitSpec) -> RateLimitResult:
        allowed, remaining, retry_ms = await client.eval(
            _FIXED_WINDOW_LUA, 1, f"rl:fw:{key}", spec.requests, spec.window_seconds
        )
        return RateLimitResult(
            allowed=bool(allowed),
            limit=spec.requests,
            remaining=int(remaining),
            retry_after=_ms_to_seconds_ceil(retry_ms),
        )


class SlidingWindowLimiter(RateLimiter):
    async def check(self, client: redis.Redis, *, key: str, spec: RateLimitSpec) -> RateLimitResult:
        now_ms = int(time.time() * 1000)
        member = f"{now_ms}-{time.perf_counter_ns()}"
        allowed, remaining, retry_ms = await client.eval(
            _SLIDING_WINDOW_LUA,
            1,
            f"rl:sw:{key}",
            spec.requests,
            spec.window_seconds * 1000,
            now_ms,
            member,
        )
        return RateLimitResult(
            allowed=bool(allowed),
            limit=spec.requests,
            remaining=max(0, int(remaining)),
            retry_after=_ms_to_seconds_ceil(retry_ms),
        )


class TokenBucketLimiter(RateLimiter):
    async def check(self, client: redis.Redis, *, key: str, spec: RateLimitSpec) -> RateLimitResult:
        capacity = spec.burst or spec.requests
        refill_rate = spec.requests / spec.window_seconds
        now = time.time()
        # Keep the bucket alive long enough to fully refill from empty.
        ttl_ms = int((capacity / refill_rate) * 1000) + 1000
        allowed, remaining, retry_ms = await client.eval(
            _TOKEN_BUCKET_LUA, 1, f"rl:tb:{key}", capacity, refill_rate, now, ttl_ms
        )
        return RateLimitResult(
            allowed=bool(allowed),
            limit=capacity,
            remaining=int(remaining),
            retry_after=_ms_to_seconds_ceil(retry_ms),
        )
