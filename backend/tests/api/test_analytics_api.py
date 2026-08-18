"""End-to-end analytics tests: drive real gateway traffic, then query analytics + rollup."""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import AsyncClient

from app.db.session import get_sessionmaker
from app.repositories.analytics import AnalyticsRepository
from tests.conftest import requires_docker

pytestmark = [requires_docker, pytest.mark.integration]

UPSTREAM = "https://upstream.test"


async def _setup(client: AsyncClient, email: str) -> tuple[dict, str, str, str]:
    await client.post("/auth/register", json={"email": email, "password": "password123"})
    token = (
        await client.post("/auth/login", json={"email": email, "password": "password123"})
    ).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    org_id = (await client.post("/organizations", json={"name": "Org"}, headers=h)).json()["id"]
    api = (
        await client.post(f"/organizations/{org_id}/apis", json={"name": "Echo"}, headers=h)
    ).json()
    await client.post(
        f"/organizations/{org_id}/apis/{api['id']}/versions",
        json={"version": "v1", "upstream_base_url": UPSTREAM},
        headers=h,
    )
    key = (
        await client.post(f"/organizations/{org_id}/apis/{api['id']}/keys", json={}, headers=h)
    ).json()["api_key"]
    return h, org_id, api["slug"], key


async def _drive_traffic(client: AsyncClient, slug: str, key: str) -> None:
    with respx.mock(assert_all_mocked=False) as mock:
        mock.get(f"{UPSTREAM}/ok").mock(return_value=httpx.Response(200, text="ok"))
        mock.get(f"{UPSTREAM}/fail").mock(return_value=httpx.Response(500, text="err"))
        for _ in range(4):
            await client.get(f"/gw/{slug}/v1/ok", headers={"X-API-Key": key})
        await client.get(f"/gw/{slug}/v1/fail", headers={"X-API-Key": key})


async def test_summary_reflects_traffic(client: AsyncClient) -> None:
    h, org_id, slug, key = await _setup(client, "an1@e.com")
    await _drive_traffic(client, slug, key)

    resp = await client.get(f"/organizations/{org_id}/analytics/summary?days=7", headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["request_count"] == 5
    assert body["error_count"] == 1
    assert round(body["error_rate"], 2) == 0.2
    assert body["active_keys"] == 1
    assert body["p95_latency_ms"] >= 0


async def test_top_endpoints(client: AsyncClient) -> None:
    h, org_id, slug, key = await _setup(client, "an2@e.com")
    await _drive_traffic(client, slug, key)
    resp = await client.get(f"/organizations/{org_id}/analytics/top-endpoints?days=7", headers=h)
    assert resp.status_code == 200
    rows = {r["path"]: r["request_count"] for r in resp.json()}
    assert rows.get("ok") == 4
    assert rows.get("fail") == 1


async def test_status_breakdown(client: AsyncClient) -> None:
    h, org_id, slug, key = await _setup(client, "an3@e.com")
    await _drive_traffic(client, slug, key)
    resp = await client.get(f"/organizations/{org_id}/analytics/status-breakdown?days=7", headers=h)
    assert resp.status_code == 200
    breakdown = resp.json()
    assert breakdown.get("2xx") == 4
    assert breakdown.get("5xx") == 1


async def test_rollup_then_timeseries(client: AsyncClient) -> None:
    h, org_id, slug, key = await _setup(client, "an4@e.com")
    await _drive_traffic(client, slug, key)

    # Run the rollup (what the Celery beat task does).
    from datetime import UTC, datetime

    async with get_sessionmaker()() as session:
        await AnalyticsRepository(session).rollup_daily(datetime.now(UTC).date())
        await session.commit()

    resp = await client.get(f"/organizations/{org_id}/analytics/timeseries?days=2", headers=h)
    assert resp.status_code == 200
    series = resp.json()
    assert len(series) == 1
    assert series[0]["request_count"] == 5
    assert series[0]["error_count"] == 1


async def test_rollup_is_idempotent(client: AsyncClient) -> None:
    h, org_id, slug, key = await _setup(client, "an5@e.com")
    await _drive_traffic(client, slug, key)
    from datetime import UTC, datetime

    today = datetime.now(UTC).date()
    async with get_sessionmaker()() as session:
        repo = AnalyticsRepository(session)
        await repo.rollup_daily(today)
        await repo.rollup_daily(today)  # second run must not double-count
        await session.commit()

    resp = await client.get(f"/organizations/{org_id}/analytics/timeseries?days=2", headers=h)
    assert resp.json()[0]["request_count"] == 5


async def test_analytics_requires_permission(client: AsyncClient) -> None:
    h, org_id, _, _ = await _setup(client, "an6@e.com")
    # Add a viewer... viewer HAS analytics:read, so use an outsider instead.
    await client.post("/auth/register", json={"email": "out@e.com", "password": "password123"})
    outsider = {
        "Authorization": "Bearer "
        + (
            await client.post("/auth/login", json={"email": "out@e.com", "password": "password123"})
        ).json()["access_token"]
    }
    resp = await client.get(f"/organizations/{org_id}/analytics/summary", headers=outsider)
    assert resp.status_code == 403
