"""Telemetry sinks — where drained outbox events are delivered.

The default :class:`LoggingSink` emits structured logs. :class:`HttpForwarderSink` delivers events
to the Observability platform (Project B) over an **HMAC-signed HTTP POST** — the concrete
realization of the transport-agnostic seam. A ``KafkaSink`` / ``RedisStreamSink`` implementing the
same :class:`TelemetrySink` protocol can be dropped in later with no change to the event schema, the
outbox, or the publisher.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from typing import Protocol

import httpx
import orjson
import structlog

from app.core.config import get_settings

logger = structlog.get_logger("telemetry")


class TelemetrySink(Protocol):
    async def deliver(self, events: list[dict]) -> None: ...


class LoggingSink:
    """Delivers events as structured logs. Suitable for local dev and log-based ingestion."""

    async def deliver(self, events: list[dict]) -> None:
        for event in events:
            logger.info(
                "telemetry_event",
                event_type=event.get("event_type"),
                schema_version=event.get("schema_version"),
                payload=event,
            )


class HttpForwarderSink:
    """Forwards events to Project B's ingestion API, authenticated by HMAC (separate from JWT).

    On any delivery failure it raises, so the outbox publisher leaves the rows pending and retries
    them later — preserving at-least-once delivery (Project B dedupes on ``event_id``).
    """

    def __init__(self, *, url: str, secret: str, timeout_seconds: float) -> None:
        self._url = url
        self._secret = secret
        self._timeout = timeout_seconds

    def _sign(self, body: bytes) -> dict[str, str]:
        timestamp = str(int(time.time()))
        nonce = str(uuid.uuid4())
        message = timestamp.encode() + b"." + nonce.encode() + b"." + body
        signature = hmac.new(self._secret.encode(), message, hashlib.sha256).hexdigest()
        return {
            "content-type": "application/json",
            "x-telemetry-timestamp": timestamp,
            "x-telemetry-nonce": nonce,
            "x-telemetry-signature": signature,
        }

    async def deliver(self, events: list[dict]) -> None:
        body = orjson.dumps({"events": events})
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(self._url, content=body, headers=self._sign(body))
            resp.raise_for_status()
        logger.info("telemetry_forwarded", count=len(events), url=self._url)


_logging_sink: TelemetrySink = LoggingSink()


def get_sink() -> TelemetrySink:
    """Select the sink from settings: HTTP forwarder when a URL is configured, else logging."""
    settings = get_settings()
    if settings.telemetry_forward_url:
        return HttpForwarderSink(
            url=settings.telemetry_forward_url,
            secret=settings.telemetry_forward_hmac_secret,
            timeout_seconds=settings.telemetry_forward_timeout_seconds,
        )
    return _logging_sink
