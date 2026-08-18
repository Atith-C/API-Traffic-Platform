"""Tests for notifications and request-log search (Milestone 10 feature completion)."""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import AsyncClient

from tests.conftest import requires_docker

pytestmark = [requires_docker, pytest.mark.integration]

UPSTREAM = "https://upstream.test"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _login(client: AsyncClient, email: str) -> str:
    await client.post("/auth/register", json={"email": email, "password": "password123"})
    return (
        await client.post("/auth/login", json={"email": email, "password": "password123"})
    ).json()["access_token"]


async def test_member_added_gets_notification(client: AsyncClient) -> None:
    owner = await _login(client, "notif-owner@e.com")
    await _login(client, "invitee@e.com")
    org_id = (
        await client.post("/organizations", json={"name": "Org"}, headers=_auth(owner))
    ).json()["id"]
    await client.post(
        f"/organizations/{org_id}/members",
        json={"email": "invitee@e.com", "role": "developer"},
        headers=_auth(owner),
    )

    invitee_token = (
        await client.post("/auth/login", json={"email": "invitee@e.com", "password": "password123"})
    ).json()["access_token"]
    notifs = await client.get("/notifications", headers=_auth(invitee_token))
    assert notifs.status_code == 200
    body = notifs.json()
    assert len(body) == 1
    assert body[0]["type"] == "member.added"
    assert body[0]["read_at"] is None

    # Mark read.
    nid = body[0]["id"]
    marked = await client.post(f"/notifications/{nid}/read", headers=_auth(invitee_token))
    assert marked.status_code == 200
    assert marked.json()["read_at"] is not None

    unread = await client.get("/notifications?unread_only=true", headers=_auth(invitee_token))
    assert unread.json() == []


async def test_owner_does_not_notify_self(client: AsyncClient) -> None:
    owner = await _login(client, "solo-notif@e.com")
    await client.post("/organizations", json={"name": "Solo"}, headers=_auth(owner))
    # Creating an org (self as owner) should not generate a notification.
    notifs = await client.get("/notifications", headers=_auth(owner))
    assert notifs.json() == []


async def test_request_log_search_filters(client: AsyncClient) -> None:
    owner = await _login(client, "search@e.com")
    org_id = (
        await client.post("/organizations", json={"name": "Org"}, headers=_auth(owner))
    ).json()["id"]
    api = (
        await client.post(
            f"/organizations/{org_id}/apis", json={"name": "Echo"}, headers=_auth(owner)
        )
    ).json()
    await client.post(
        f"/organizations/{org_id}/apis/{api['id']}/versions",
        json={"version": "v1", "upstream_base_url": UPSTREAM},
        headers=_auth(owner),
    )
    key = (
        await client.post(
            f"/organizations/{org_id}/apis/{api['id']}/keys", json={}, headers=_auth(owner)
        )
    ).json()["api_key"]

    with respx.mock(assert_all_mocked=False) as mock:
        mock.get(f"{UPSTREAM}/ok").mock(return_value=httpx.Response(200, text="ok"))
        mock.get(f"{UPSTREAM}/bad").mock(return_value=httpx.Response(500, text="err"))
        for _ in range(3):
            await client.get(f"/gw/{api['slug']}/v1/ok", headers={"X-API-Key": key})
        await client.get(f"/gw/{api['slug']}/v1/bad", headers={"X-API-Key": key})

    base = f"/organizations/{org_id}/request-logs"
    # All logs.
    all_logs = await client.get(base, headers=_auth(owner))
    assert all_logs.json()["total"] == 4

    # Filter to errors only.
    errors = await client.get(f"{base}?status_min=500", headers=_auth(owner))
    assert errors.json()["total"] == 1
    assert errors.json()["items"][0]["path"] == "bad"

    # Filter by path substring.
    ok_only = await client.get(f"{base}?path_contains=ok", headers=_auth(owner))
    assert ok_only.json()["total"] == 3


async def test_request_log_search_requires_permission(client: AsyncClient) -> None:
    owner = await _login(client, "search-owner@e.com")
    outsider = await _login(client, "search-out@e.com")
    org_id = (
        await client.post("/organizations", json={"name": "Org"}, headers=_auth(owner))
    ).json()["id"]
    resp = await client.get(f"/organizations/{org_id}/request-logs", headers=_auth(outsider))
    assert resp.status_code == 403
