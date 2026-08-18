"""Integration tests for health endpoints against real Postgres + Redis."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import requires_docker


@requires_docker
@pytest.mark.integration
async def test_liveness(client: AsyncClient) -> None:
    resp = await client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@requires_docker
@pytest.mark.integration
async def test_readiness_ok(client: AsyncClient) -> None:
    resp = await client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["components"]["database"]["status"] == "ok"
    assert body["components"]["redis"]["status"] == "ok"


@requires_docker
@pytest.mark.integration
async def test_root_and_request_id_header(client: AsyncClient) -> None:
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "x-request-id" in resp.headers
    assert resp.json()["service"]
