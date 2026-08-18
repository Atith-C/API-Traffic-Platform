"""Unit tests for the versioned telemetry event contract (Project B boundary)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.telemetry.events import SCHEMA_VERSION, AuditLogEvent, RequestLogEvent


def test_request_log_event_payload_is_json_safe() -> None:
    event = RequestLogEvent(
        occurred_at=datetime.now(UTC),
        organization_id=uuid.uuid4(),
        api_id=uuid.uuid4(),
        api_version_id=uuid.uuid4(),
        api_key_id=uuid.uuid4(),
        method="GET",
        path="anything",
        status_code=200,
        latency_ms=12.5,
        request_bytes=0,
        response_bytes=42,
        client_ip="127.0.0.1",
        upstream_url="https://upstream.test",
    )
    payload = event.to_payload()
    assert payload["event_type"] == "request_log"
    assert payload["schema_version"] == SCHEMA_VERSION
    # UUIDs and datetimes must be serialized to strings (JSON-safe).
    assert isinstance(payload["api_id"], str)
    assert isinstance(payload["occurred_at"], str)


def test_audit_log_event_defaults() -> None:
    event = AuditLogEvent(
        occurred_at=datetime.now(UTC),
        organization_id=None,
        actor_user_id=None,
        action="api_key.revoke",
        resource_type="api_key",
        resource_id=uuid.uuid4(),
        ip=None,
    )
    payload = event.to_payload()
    assert payload["event_type"] == "audit_log"
    assert payload["metadata"] == {}
    assert "event_id" in payload
