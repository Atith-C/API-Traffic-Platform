"""End-to-end API tests for organizations + RBAC enforcement."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import requires_docker

pytestmark = [requires_docker, pytest.mark.integration]


async def _signup(client: AsyncClient, email: str) -> str:
    await client.post("/auth/register", json={"email": email, "password": "password123"})
    resp = await client.post("/auth/login", json={"email": email, "password": "password123"})
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_create_and_list_org(client: AsyncClient) -> None:
    token = await _signup(client, "owner@e.com")
    resp = await client.post("/organizations", json={"name": "Acme"}, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    assert resp.json()["slug"] == "acme"

    listing = await client.get("/organizations", headers=_auth(token))
    assert listing.status_code == 200
    assert listing.json()["total"] == 1


async def test_non_member_is_forbidden(client: AsyncClient) -> None:
    owner = await _signup(client, "owner2@e.com")
    outsider = await _signup(client, "outsider@e.com")
    org_id = (
        await client.post("/organizations", json={"name": "Private"}, headers=_auth(owner))
    ).json()["id"]

    resp = await client.get(f"/organizations/{org_id}", headers=_auth(outsider))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "permission_denied"


async def test_viewer_cannot_invite_members(client: AsyncClient) -> None:
    owner = await _signup(client, "owner3@e.com")
    await _signup(client, "viewer@e.com")
    await _signup(client, "target@e.com")
    org_id = (
        await client.post("/organizations", json={"name": "Team"}, headers=_auth(owner))
    ).json()["id"]

    # Owner adds a viewer.
    add = await client.post(
        f"/organizations/{org_id}/members",
        json={"email": "viewer@e.com", "role": "viewer"},
        headers=_auth(owner),
    )
    assert add.status_code == 201

    viewer_token = (
        await client.post("/auth/login", json={"email": "viewer@e.com", "password": "password123"})
    ).json()["access_token"]

    # Viewer can read members...
    read = await client.get(f"/organizations/{org_id}/members", headers=_auth(viewer_token))
    assert read.status_code == 200
    # ...but cannot invite (lacks member:invite).
    forbidden = await client.post(
        f"/organizations/{org_id}/members",
        json={"email": "target@e.com", "role": "developer"},
        headers=_auth(viewer_token),
    )
    assert forbidden.status_code == 403


async def test_owner_can_manage_member_roles(client: AsyncClient) -> None:
    owner = await _signup(client, "owner4@e.com")
    await _signup(client, "dev@e.com")
    org_id = (
        await client.post("/organizations", json={"name": "RoleOrg"}, headers=_auth(owner))
    ).json()["id"]

    member = (
        await client.post(
            f"/organizations/{org_id}/members",
            json={"email": "dev@e.com", "role": "developer"},
            headers=_auth(owner),
        )
    ).json()

    promote = await client.patch(
        f"/organizations/{org_id}/members/{member['id']}",
        json={"role": "admin"},
        headers=_auth(owner),
    )
    assert promote.status_code == 200
    assert promote.json()["role"] == "admin"

    remove = await client.delete(
        f"/organizations/{org_id}/members/{member['id']}", headers=_auth(owner)
    )
    assert remove.status_code == 204


async def test_cannot_remove_last_owner_via_api(client: AsyncClient) -> None:
    owner = await _signup(client, "solo@e.com")
    org_id = (
        await client.post("/organizations", json={"name": "Solo"}, headers=_auth(owner))
    ).json()["id"]
    members = (await client.get(f"/organizations/{org_id}/members", headers=_auth(owner))).json()
    owner_member_id = members[0]["id"]
    resp = await client.delete(
        f"/organizations/{org_id}/members/{owner_member_id}", headers=_auth(owner)
    )
    assert resp.status_code == 422
    assert "last owner" in resp.json()["error"]["message"].lower()
