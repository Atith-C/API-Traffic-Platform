"""Telemetry emitter — writes events to the transactional outbox.

``emit`` enqueues an event into ``telemetry_outbox`` **using the caller's session**, so the event
is committed atomically with the business write that produced it (exactly-once at the source; no
lost or duplicated events). Delivery to the transport happens later, async, in the publisher.

The :class:`TelemetryEmitter` protocol is the seam Project B slots into: a Kafka/Redis-Streams
emitter can replace ``OutboxEmitter`` without changing callers or the event schema.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telemetry import TelemetryOutbox
from app.telemetry.events import TelemetryEnvelope


class TelemetryEmitter(Protocol):
    async def emit(self, session: AsyncSession, event: TelemetryEnvelope) -> None: ...


class OutboxEmitter:
    """Default emitter: append the event to the transactional outbox table."""

    async def emit(self, session: AsyncSession, event: TelemetryEnvelope) -> None:
        session.add(
            TelemetryOutbox(
                event_type=event.event_type,
                schema_version=event.schema_version,
                payload=event.to_payload(),
            )
        )


_default_emitter: TelemetryEmitter = OutboxEmitter()


def get_emitter() -> TelemetryEmitter:
    return _default_emitter
