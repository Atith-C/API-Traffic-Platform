"""End-to-end API tests for API key lifecycle: create (shown once), list, revoke, rotate."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import requires_docker

pytestmark = [requires_docker, pytest.mark.integration]


async def _api_ctx(client: AsyncClient, email: str) -> tuple[dict[str, str], str, str]:
    await client.post("/auth/register", json={"email": email, "password": "password123"})
    token = (
        await client.post("/auth/login", json={"email": email, "password": "password123"})
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    org_id = (await client.post("/organizations", json={"name": "Org"}, headers=headers)).json()[
        "id"
    ]
    api_id = (
        await client.post(f"/organizations/{org_id}/apis", json={"name": "Svc"}, headers=headers)
    ).json()["id"]
    return headers, org_id, api_id


async def test_create_key_returns_secret_once(client: AsyncClient) -> None:
    headers, org_id, api_id = await _api_ctx(client, "keys1@e.com")
    base = f"/organizations/{org_id}/apis/{api_id}/keys"

    created = await client.post(base, json={"name": "prod"}, headers=headers)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["api_key"].startswith("atp_")
    assert body["prefix"] in body["api_key"]

    # Listing never exposes the secret.
    listing = await client.get(base, headers=headers)
    assert listing.status_code == 200
    items = listing.json()
    assert len(items) == 1
    assert "api_key" not in items[0]
    assert items[0]["last_four"] == body["last_four"]


async def test_revoke_key(client: AsyncClient) -> None:
    headers, org_id, api_id = await _api_ctx(client, "keys2@e.com")
    base = f"/organizations/{org_id}/apis/{api_id}/keys"
    key_id = (await client.post(base, json={}, headers=headers)).json()["id"]

    resp = await client.delete(f"{base}/{key_id}", headers=headers)
    assert resp.status_code == 204

    items = (await client.get(base, headers=headers)).json()
    assert items[0]["revoked_at"] is not None


async def test_rotate_key_issues_new_secret(client: AsyncClient) -> None:
    headers, org_id, api_id = await _api_ctx(client, "keys3@e.com")
    base = f"/organizations/{org_id}/apis/{api_id}/keys"
    original = (await client.post(base, json={"name": "svc"}, headers=headers)).json()

    rotated = await client.post(
        f"{base}/{original['id']}/rotate", json={"grace_period_hours": 24}, headers=headers
    )
    assert rotated.status_code == 200
    new_body = rotated.json()
    assert new_body["api_key"] != original["api_key"]
    assert new_body["id"] != original["id"]

    # Two keys now exist; the old one is grace-windowed (expires_at set, not yet revoked).
    items = {k["id"]: k for k in (await client.get(base, headers=headers)).json()}
    assert len(items) == 2
    assert items[original["id"]]["expires_at"] is not None
    assert items[original["id"]]["revoked_at"] is None


async def test_rotate_with_zero_grace_revokes_immediately(client: AsyncClient) -> None:
    headers, org_id, api_id = await _api_ctx(client, "keys4@e.com")
    base = f"/organizations/{org_id}/apis/{api_id}/keys"
    original = (await client.post(base, json={}, headers=headers)).json()

    await client.post(
        f"{base}/{original['id']}/rotate", json={"grace_period_hours": 0}, headers=headers
    )
    items = {k["id"]: k for k in (await client.get(base, headers=headers)).json()}
    assert items[original["id"]]["revoked_at"] is not None
