"""Shared outbound HTTP client for the gateway.

A single pooled ``httpx.AsyncClient`` is reused across requests (connection pooling matters for a
gateway). Redirects are not followed automatically — the gateway forwards the upstream's response,
including 3xx, verbatim. In tests, ``respx`` intercepts this client so no real network calls happen.
"""

from __future__ import annotations

import httpx

from app.core.config import get_settings

_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.gateway_upstream_timeout_seconds),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
    return _client


async def close_http_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None
