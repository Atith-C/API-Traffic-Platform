"""Integration tests for rate-limiting strategies and quota enforcement (real Redis)."""

from __future__ import annotations

import uuid

import pytest

from app.models.api import QuotaPeriod, RateLimitAlgorithm
from app.services.quota import QuotaEnforcer
from app.services.rate_limit import RateLimitSpec, get_limiter
from tests.conftest import requires_docker

pytestmark = [requires_docker, pytest.mark.integration]


@pytest.mark.parametrize(
    "algorithm",
    [
        RateLimitAlgorithm.FIXED_WINDOW,
        RateLimitAlgorithm.SLIDING_WINDOW,
        RateLimitAlgorithm.TOKEN_BUCKET,
    ],
)
async def test_limiter_allows_up_to_limit_then_blocks(redis_client, algorithm) -> None:
    limiter = get_limiter(algorithm)
    key = f"test:{uuid.uuid4()}"
    spec = RateLimitSpec(requests=3, window_seconds=60, burst=3)

    results = [await limiter.check(redis_client, key=key, spec=spec) for _ in range(3)]
    assert all(r.allowed for r in results)

    blocked = await limiter.check(redis_client, key=key, spec=spec)
    assert blocked.allowed is False
    assert blocked.retry_after >= 0


async def test_fixed_window_reports_remaining(redis_client) -> None:
    limiter = get_limiter(RateLimitAlgorithm.FIXED_WINDOW)
    key = f"rem:{uuid.uuid4()}"
    spec = RateLimitSpec(requests=5, window_seconds=60)
    first = await limiter.check(redis_client, key=key, spec=spec)
    assert first.remaining == 4


async def test_token_bucket_burst_capacity(redis_client) -> None:
    limiter = get_limiter(RateLimitAlgorithm.TOKEN_BUCKET)
    key = f"burst:{uuid.uuid4()}"
    # 1 req/sec sustained, but burst of 5 allows 5 immediately.
    spec = RateLimitSpec(requests=1, window_seconds=1, burst=5)
    results = [await limiter.check(redis_client, key=key, spec=spec) for _ in range(5)]
    assert sum(r.allowed for r in results) == 5
    assert (await limiter.check(redis_client, key=key, spec=spec)).allowed is False


async def test_quota_consume_and_exceed(redis_client) -> None:
    enforcer = QuotaEnforcer(redis_client)
    key_id = uuid.uuid4()

    c1 = await enforcer.consume(api_key_id=key_id, period=QuotaPeriod.DAILY, limit=2)
    c2 = await enforcer.consume(api_key_id=key_id, period=QuotaPeriod.DAILY, limit=2)
    c3 = await enforcer.consume(api_key_id=key_id, period=QuotaPeriod.DAILY, limit=2)
    assert (c1.exceeded, c2.exceeded, c3.exceeded) == (False, False, True)


async def test_quota_rollback(redis_client) -> None:
    enforcer = QuotaEnforcer(redis_client)
    key_id = uuid.uuid4()
    await enforcer.consume(api_key_id=key_id, period=QuotaPeriod.MONTHLY, limit=5)
    await enforcer.rollback(api_key_id=key_id, period=QuotaPeriod.MONTHLY)
    again = await enforcer.consume(api_key_id=key_id, period=QuotaPeriod.MONTHLY, limit=5)
    assert again.used == 1
