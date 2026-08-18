"""Versioned telemetry event contract — the integration boundary with Project B.

These Pydantic models define the *wire format* of the events Project A produces. Every event
carries a ``schema_version`` so consumers can evolve safely. The models are transport-agnostic: the
same payloads can be written to the outbox table today and streamed over Kafka/Redis Streams later
**without changing this schema**.

This module is the single source of truth; JSON Schemas are generated from it. Keep it
dependency-light (only pydantic) so it can be vendored into Project B as-is.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"


class TelemetryEnvelope(BaseModel):
    """Common envelope fields shared by every telemetry event."""

    schema_version: str = Field(default=SCHEMA_VERSION)
    event_type: str
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    occurred_at: datetime

    def to_payload(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict for the outbox / stream."""
        return self.model_dump(mode="json")


class RequestLogEvent(TelemetryEnvelope):
    """One proxied API request. This is the primary signal Project B ingests."""

    event_type: Literal["request_log"] = "request_log"

    organization_id: uuid.UUID
    api_id: uuid.UUID
    api_version_id: uuid.UUID
    api_key_id: uuid.UUID | None
    method: str
    path: str
    status_code: int
    latency_ms: float
    request_bytes: int
    response_bytes: int
    client_ip: str
    upstream_url: str


class AuditLogEvent(TelemetryEnvelope):
    """An administrative action (create/revoke/rotate/...); correlated with incidents in B."""

    event_type: Literal["audit_log"] = "audit_log"

    organization_id: uuid.UUID | None
    actor_user_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: uuid.UUID | None
    ip: str | None
    metadata: dict[str, Any] = Field(default_factory=dict)


TelemetryEvent = RequestLogEvent | AuditLogEvent
