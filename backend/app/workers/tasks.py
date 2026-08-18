"""Celery tasks and periodic schedule.

Tasks reuse the same async services as the API (no logic duplication). Since Celery workers are
sync, each task runs its coroutine on a fresh event loop via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio

import structlog

from app.db.session import session_scope
from app.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)


async def _publish_telemetry() -> int:
    from app.services.telemetry.publisher import drain_outbox

    published_total = 0
    async with session_scope() as session:
        # Drain in batches until the outbox is empty (bounded per run by the loop below).
        for _ in range(50):
            count = await drain_outbox(session, batch_size=200)
            published_total += count
            if count == 0:
                break
    return published_total


@celery_app.task(name="telemetry.publish")
def publish_telemetry() -> int:
    """Drain pending telemetry outbox events to the configured sink."""
    return asyncio.run(_publish_telemetry())


async def _rollup_daily_usage() -> int:
    from datetime import UTC, datetime, timedelta

    from app.repositories.analytics import AnalyticsRepository

    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)
    async with session_scope() as session:
        repo = AnalyticsRepository(session)
        # Recompute yesterday (now complete) and today (partial) idempotently.
        return await repo.rollup_daily(yesterday) + await repo.rollup_daily(today)


@celery_app.task(name="analytics.rollup_daily")
def rollup_daily() -> int:
    """Rebuild the daily_usage rollup for yesterday and today from request_logs."""
    return asyncio.run(_rollup_daily_usage())
