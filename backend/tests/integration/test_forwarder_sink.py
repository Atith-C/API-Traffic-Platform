"""Tests for the HttpForwarderSink — the A→B telemetry delivery seam (HMAC-signed HTTP POST)."""

from __future__ import annotations

import hashlib
import hmac

import httpx
import pytest
import respx

from app.services.telemetry.sink import HttpForwarderSink, LoggingSink, get_sink

pytestmark = pytest.mark.integration  # no DB needed, but grouped with integration

FORWARD_URL = "https://observe.test/v1/telemetry/events"
SECRET = "shared-ingest-secret"


async def test_get_sink_defaults_to_logging(monkeypatch) -> None:
    # With no forward URL configured, the default sink just logs.
    assert isinstance(get_sink(), LoggingSink)


async def test_forwarder_signs_and_posts() -> None:
    sink = HttpForwarderSink(url=FORWARD_URL, secret=SECRET, timeout_seconds=5.0)
    events = [{"event_type": "request_log", "event_id": "e1", "schema_version": "1.0"}]

    with respx.mock() as mock:
        route = mock.post(FORWARD_URL).mock(return_value=httpx.Response(200, json={"accepted": 1}))
        await sink.deliver(events)

    assert route.called
    req = route.calls.last.request
    # Headers carry the HMAC triple.
    ts = req.headers["x-telemetry-timestamp"]
    nonce = req.headers["x-telemetry-nonce"]
    sig = req.headers["x-telemetry-signature"]
    # Recompute the signature over the exact bytes B will verify.
    message = ts.encode() + b"." + nonce.encode() + b"." + req.content
    expected = hmac.new(SECRET.encode(), message, hashlib.sha256).hexdigest()
    assert sig == expected
    assert b'"event_id":"e1"' in req.content


async def test_forwarder_raises_on_upstream_error() -> None:
    """A delivery failure must raise so the outbox publisher retries (at-least-once)."""
    sink = HttpForwarderSink(url=FORWARD_URL, secret=SECRET, timeout_seconds=5.0)
    with respx.mock() as mock:
        mock.post(FORWARD_URL).mock(return_value=httpx.Response(503, text="down"))
        with pytest.raises(httpx.HTTPStatusError):
            await sink.deliver([{"event_type": "audit_log"}])
