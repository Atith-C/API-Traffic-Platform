"""End-to-end tests for the developer dashboard and admin overview."""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import AsyncClient

from app.db.session import get_sessionmaker
from app.models.user import User
from tests.conftest import requires_docker

pytestmark = [requires_docker, pytest.mark.integration]

UPSTREAM = "https://upstream.test"


async def test_developer_dashboard(client: AsyncClient) -> None:
    await client.post("/auth/register", json={"email": "dash@e.com", "password": "password123"})
    token = (
        await client.post("/auth/login", json={"email": "dash@e.com", "password": "password123"})
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

    with respx.mock(assert_all_mocked=False) as mock:
        mock.get(f"{UPSTREAM}/ok").mock(return_value=httpx.Response(200, text="ok"))
        for _ in range(3):
            await client.get(f"/gw/{api['slug']}/v1/ok", headers={"X-API-Key": key})

    resp = await client.get(f"/organizations/{org_id}/dashboard?days=7", headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"]["request_count"] == 3
    assert body["api_count"] == 1
    assert body["status_breakdown"].get("2xx") == 3
    assert len(body["top_endpoints"]) == 1


async def test_admin_overview_requires_superuser(client: AsyncClient) -> None:
    await client.post("/auth/register", json={"email": "plain@e.com", "password": "password123"})
    token = (
        await client.post("/auth/login", json={"email": "plain@e.com", "password": "password123"})
    ).json()["access_token"]
    resp = await client.get("/admin/overview", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


async def test_admin_overview_for_superuser(client: AsyncClient) -> None:
    await client.post("/auth/register", json={"email": "boss@e.com", "password": "password123"})
    # Promote to superuser directly in the DB.
    async with get_sessionmaker()() as session:
        from sqlalchemy import update

        await session.execute(
            update(User).where(User.email == "boss@e.com").values(is_superuser=True)
        )
        await session.commit()

    token = (
        await client.post("/auth/login", json={"email": "boss@e.com", "password": "password123"})
    ).json()["access_token"]
    resp = await client.get("/admin/overview", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["organizations"] >= 0
    assert "health" in body
    assert body["health"]["database"] == "ok"
