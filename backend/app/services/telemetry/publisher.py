"""Telemetry publisher — drains the outbox and delivers pending events to a sink.

Selects pending rows (``published_at IS NULL``), locks them with ``FOR UPDATE SKIP LOCKED`` so
multiple workers can drain concurrently without double-delivery, hands the batch to the sink, and
stamps ``published_at``. Idempotent and safe to run on a schedule (Celery beat).
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telemetry import TelemetryOutbox
from app.services.telemetry.sink import TelemetrySink, get_sink

logger = structlog.get_logger(__name__)


async def drain_outbox(
    session: AsyncSession,
    *,
    sink: TelemetrySink | None = None,
    batch_size: int = 100,
) -> int:
    """Deliver up to ``batch_size`` pending events. Returns the number published."""
    sink = sink or get_sink()
    result = await session.execute(
        select(TelemetryOutbox)
        .where(TelemetryOutbox.published_at.is_(None))
        .order_by(TelemetryOutbox.created_at.asc())
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    rows = list(result.scalars().all())
    if not rows:
        return 0

    try:
        await sink.deliver([row.payload for row in rows])
    except Exception:
        # Leave rows pending (published_at stays NULL); bump attempts for observability.
        for row in rows:
            row.attempts += 1
        await session.flush()
        logger.warning("telemetry_publish_failed", batch=len(rows))
        raise

    now = datetime.now(UTC)
    for row in rows:
        row.published_at = now
        row.attempts += 1
    await session.flush()
    logger.info("telemetry_published", count=len(rows))
    return len(rows)
