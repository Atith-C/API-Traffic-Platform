"""End-to-end API tests for the API catalog (register APIs, versions, quotas, rate limits)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import requires_docker

pytestmark = [requires_docker, pytest.mark.integration]


async def _owner_with_org(client: AsyncClient, email: str) -> tuple[dict[str, str], str]:
    await client.post("/auth/register", json={"email": email, "password": "password123"})
    token = (
        await client.post("/auth/login", json={"email": email, "password": "password123"})
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    org_id = (await client.post("/organizations", json={"name": "Org"}, headers=headers)).json()[
        "id"
    ]
    return headers, org_id


async def test_api_crud_and_versioning(client: AsyncClient) -> None:
    headers, org_id = await _owner_with_org(client, "api-owner@e.com")
    base = f"/organizations/{org_id}/apis"

    created = await client.post(
        base, json={"name": "Payments API", "description": "Money"}, headers=headers
    )
    assert created.status_code == 201, created.text
    api = created.json()
    assert api["slug"] == "payments-api"

    # Add a version pointing at a real-ish upstream.
    v = await client.post(
        f"{base}/{api['id']}/versions",
        json={"version": "v1", "upstream_base_url": "https://httpbin.org"},
        headers=headers,
    )
    assert v.status_code == 201, v.text

    # Duplicate version conflicts.
    dup = await client.post(
        f"{base}/{api['id']}/versions",
        json={"version": "v1", "upstream_base_url": "https://httpbin.org"},
        headers=headers,
    )
    assert dup.status_code == 409

    got = await client.get(f"{base}/{api['id']}", headers=headers)
    assert got.status_code == 200
    assert len(got.json()["versions"]) == 1


async def test_quota_and_rate_limit_config(client: AsyncClient) -> None:
    headers, org_id = await _owner_with_org(client, "cfg-owner@e.com")
    base = f"/organizations/{org_id}/apis"
    api_id = (await client.post(base, json={"name": "Metered"}, headers=headers)).json()["id"]

    # Set quotas.
    quota = await client.put(
        f"{base}/{api_id}/quota",
        json={"quotas": [{"period": "daily", "max_requests": 1000}]},
        headers=headers,
    )
    assert quota.status_code == 200
    assert quota.json()[0]["max_requests"] == 1000

    # Set a token-bucket rate limit with burst.
    rl = await client.put(
        f"{base}/{api_id}/rate-limit",
        json={
            "algorithm": "token_bucket",
            "requests": 10,
            "window_seconds": 1,
            "burst": 20,
        },
        headers=headers,
    )
    assert rl.status_code == 200
    assert rl.json()["burst"] == 20

    # burst is rejected for non-token-bucket algorithms.
    bad = await client.put(
        f"{base}/{api_id}/rate-limit",
        json={"algorithm": "fixed_window", "requests": 5, "window_seconds": 60, "burst": 10},
        headers=headers,
    )
    assert bad.status_code == 422


async def test_invalid_upstream_url_rejected(client: AsyncClient) -> None:
    headers, org_id = await _owner_with_org(client, "bad-url@e.com")
    base = f"/organizations/{org_id}/apis"
    api_id = (await client.post(base, json={"name": "X"}, headers=headers)).json()["id"]
    resp = await client.post(
        f"{base}/{api_id}/versions",
        json={"version": "v1", "upstream_base_url": "not-a-url"},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_developer_can_create_viewer_cannot(client: AsyncClient) -> None:
    headers, org_id = await _owner_with_org(client, "own2@e.com")
    base = f"/organizations/{org_id}/apis"

    for email, role in [("dev2@e.com", "developer"), ("view2@e.com", "viewer")]:
        await client.post("/auth/register", json={"email": email, "password": "password123"})
        await client.post(
            f"/organizations/{org_id}/members",
            json={"email": email, "role": role},
            headers=headers,
        )

    dev = {
        "Authorization": "Bearer "
        + (
            await client.post(
                "/auth/login", json={"email": "dev2@e.com", "password": "password123"}
            )
        ).json()["access_token"]
    }
    viewer = {
        "Authorization": "Bearer "
        + (
            await client.post(
                "/auth/login", json={"email": "view2@e.com", "password": "password123"}
            )
        ).json()["access_token"]
    }

    assert (await client.post(base, json={"name": "DevMade"}, headers=dev)).status_code == 201
    assert (await client.post(base, json={"name": "Nope"}, headers=viewer)).status_code == 403
    # Viewer can still read.
    assert (await client.get(base, headers=viewer)).status_code == 200


async def test_cross_org_isolation(client: AsyncClient) -> None:
    headers_a, org_a = await _owner_with_org(client, "tenant-a@e.com")
    headers_b, org_b = await _owner_with_org(client, "tenant-b@e.com")
    api_a = (
        await client.post(
            f"/organizations/{org_a}/apis", json={"name": "SecretA"}, headers=headers_a
        )
    ).json()["id"]

    # Tenant B cannot see tenant A's API even by guessing the id (not a member of org A).
    resp = await client.get(f"/organizations/{org_a}/apis/{api_a}", headers=headers_b)
    assert resp.status_code == 403
    # And addressing it under B's org returns 404 (belongs to A).
    resp2 = await client.get(f"/organizations/{org_b}/apis/{api_a}", headers=headers_b)
    assert resp2.status_code == 404
