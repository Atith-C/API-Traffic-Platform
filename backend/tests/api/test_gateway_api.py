"""End-to-end gateway tests.

The upstream is mocked with ``respx`` so no real network call happens (``assert_all_mocked=False``
lets in-process calls to our own ASGI app pass through, while ``https://upstream.test`` is mocked).
This proves the full traffic-management flow: key auth, rate limit, quota, forwarding, latency.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import AsyncClient

from tests.conftest import requires_docker

pytestmark = [requires_docker, pytest.mark.integration]

UPSTREAM = "https://upstream.test"


async def _setup(
    client: AsyncClient,
    email: str,
    *,
    slug_name: str = "Echo",
    rate_limit: dict | None = None,
    quota: dict | None = None,
) -> tuple[str, str]:
    """Set up user+org+api+version(+rate limit/quota)+key. Returns (api_slug, api_key)."""
    await client.post("/auth/register", json={"email": email, "password": "password123"})
    token = (
        await client.post("/auth/login", json={"email": email, "password": "password123"})
    ).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    org_id = (await client.post("/organizations", json={"name": "Org"}, headers=h)).json()["id"]
    api = (
        await client.post(f"/organizations/{org_id}/apis", json={"name": slug_name}, headers=h)
    ).json()
    await client.post(
        f"/organizations/{org_id}/apis/{api['id']}/versions",
        json={"version": "v1", "upstream_base_url": UPSTREAM},
        headers=h,
    )
    if rate_limit:
        await client.put(
            f"/organizations/{org_id}/apis/{api['id']}/rate-limit",
            json=rate_limit,
            headers=h,
        )
    if quota:
        await client.put(f"/organizations/{org_id}/apis/{api['id']}/quota", json=quota, headers=h)
    key = (
        await client.post(f"/organizations/{org_id}/apis/{api['id']}/keys", json={}, headers=h)
    ).json()["api_key"]
    return api["slug"], key


async def test_proxy_forwards_and_measures(client: AsyncClient) -> None:
    slug, key = await _setup(client, "gw1@e.com")
    with respx.mock(assert_all_mocked=False) as mock:
        route = mock.get(f"{UPSTREAM}/anything").mock(
            return_value=httpx.Response(200, json={"upstream": "hello"})
        )
        resp = await client.get(f"/gw/{slug}/v1/anything", headers={"X-API-Key": key})

    assert route.called
    assert resp.status_code == 200
    assert resp.json() == {"upstream": "hello"}
    assert "X-Gateway-Latency-Ms" in resp.headers


async def test_proxy_forwards_body_and_method(client: AsyncClient) -> None:
    slug, key = await _setup(client, "gw2@e.com")
    with respx.mock(assert_all_mocked=False) as mock:
        route = mock.post(f"{UPSTREAM}/submit").mock(
            return_value=httpx.Response(201, json={"created": True})
        )
        resp = await client.post(
            f"/gw/{slug}/v1/submit",
            headers={"X-API-Key": key},
            json={"field": "value"},
        )
    assert resp.status_code == 201
    sent = route.calls.last.request
    assert sent.method == "POST"
    assert b"field" in sent.content


async def test_missing_key_rejected(client: AsyncClient) -> None:
    slug, _ = await _setup(client, "gw3@e.com")
    resp = await client.get(f"/gw/{slug}/v1/anything")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "missing_api_key"


async def test_invalid_key_rejected(client: AsyncClient) -> None:
    slug, _ = await _setup(client, "gw4@e.com")
    resp = await client.get(f"/gw/{slug}/v1/anything", headers={"X-API-Key": "atp_deadbeef_nope"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_api_key"


async def test_unknown_version_404(client: AsyncClient) -> None:
    slug, key = await _setup(client, "gw5@e.com")
    resp = await client.get(f"/gw/{slug}/v9/anything", headers={"X-API-Key": key})
    assert resp.status_code == 404


async def test_rate_limit_enforced(client: AsyncClient) -> None:
    slug, key = await _setup(
        client,
        "gw6@e.com",
        rate_limit={"algorithm": "fixed_window", "requests": 2, "window_seconds": 60},
    )
    with respx.mock(assert_all_mocked=False) as mock:
        mock.get(f"{UPSTREAM}/ping").mock(return_value=httpx.Response(200, text="ok"))
        statuses = [
            (await client.get(f"/gw/{slug}/v1/ping", headers={"X-API-Key": key})).status_code
            for _ in range(3)
        ]
    assert statuses == [200, 200, 429]


async def test_quota_enforced(client: AsyncClient) -> None:
    slug, key = await _setup(
        client,
        "gw7@e.com",
        quota={"quotas": [{"period": "daily", "max_requests": 2}]},
    )
    with respx.mock(assert_all_mocked=False) as mock:
        mock.get(f"{UPSTREAM}/ping").mock(return_value=httpx.Response(200, text="ok"))
        statuses = [
            (await client.get(f"/gw/{slug}/v1/ping", headers={"X-API-Key": key})).status_code
            for _ in range(3)
        ]
    assert statuses[-1] == 429
    last = await client.get(f"/gw/{slug}/v1/ping", headers={"X-API-Key": key})
    assert last.json()["error"]["code"] == "quota_exceeded"


async def test_upstream_status_passthrough(client: AsyncClient) -> None:
    slug, key = await _setup(client, "gw8@e.com")
    with respx.mock(assert_all_mocked=False) as mock:
        mock.get(f"{UPSTREAM}/boom").mock(return_value=httpx.Response(503, text="down"))
        resp = await client.get(f"/gw/{slug}/v1/boom", headers={"X-API-Key": key})
    # The gateway forwards upstream's own status, not a synthetic error.
    assert resp.status_code == 503


async def test_upstream_timeout_returns_502(client: AsyncClient) -> None:
    slug, key = await _setup(client, "gw9@e.com")
    with respx.mock(assert_all_mocked=False) as mock:
        mock.get(f"{UPSTREAM}/slow").mock(side_effect=httpx.TimeoutException("timeout"))
        resp = await client.get(f"/gw/{slug}/v1/slow", headers={"X-API-Key": key})
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "upstream_timeout"


async def test_key_for_wrong_api_rejected(client: AsyncClient) -> None:
    slug_a, key_a = await _setup(client, "gwA@e.com", slug_name="Alpha")
    slug_b, _ = await _setup(client, "gwB@e.com", slug_name="Beta")
    # Use A's key against B's slug.
    resp = await client.get(f"/gw/{slug_b}/v1/x", headers={"X-API-Key": key_a})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "key_api_mismatch"
