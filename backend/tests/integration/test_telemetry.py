"""Integration tests for request logging, audit logging, and the telemetry outbox drain."""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import func, select

from app.db.session import get_sessionmaker
from app.models.telemetry import ApiKeyUsage, AuditLog, RequestLog, TelemetryOutbox
from app.services.telemetry.publisher import drain_outbox
from tests.conftest import requires_docker

pytestmark = [requires_docker, pytest.mark.integration]

UPSTREAM = "https://upstream.test"


async def _setup_api(client: AsyncClient, email: str) -> tuple[str, str]:
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
    return api["slug"], key


async def test_gateway_writes_log_usage_and_outbox(client: AsyncClient) -> None:
    slug, key = await _setup_api(client, "tel1@e.com")
    with respx.mock(assert_all_mocked=False) as mock:
        mock.get(f"{UPSTREAM}/anything").mock(return_value=httpx.Response(200, text="ok"))
        resp = await client.get(f"/gw/{slug}/v1/anything", headers={"X-API-Key": key})
    assert resp.status_code == 200

    async with get_sessionmaker()() as session:
        logs = await session.scalar(select(func.count()).select_from(RequestLog))
        usage = await session.scalar(select(func.count()).select_from(ApiKeyUsage))
        events = (
            (
                await session.execute(
                    select(TelemetryOutbox).where(TelemetryOutbox.event_type == "request_log")
                )
            )
            .scalars()
            .all()
        )
    assert logs == 1
    assert usage == 1
    assert len(events) == 1
    assert events[0].published_at is None  # pending until drained
    assert events[0].payload["status_code"] == 200


async def test_outbox_drain_marks_published(client: AsyncClient) -> None:
    slug, key = await _setup_api(client, "tel2@e.com")
    with respx.mock(assert_all_mocked=False) as mock:
        mock.get(f"{UPSTREAM}/x").mock(return_value=httpx.Response(200, text="ok"))
        await client.get(f"/gw/{slug}/v1/x", headers={"X-API-Key": key})

    async with get_sessionmaker()() as session:
        published = await drain_outbox(session, batch_size=100)
        await session.commit()
    assert published >= 1

    async with get_sessionmaker()() as session:
        pending = await session.scalar(
            select(func.count())
            .select_from(TelemetryOutbox)
            .where(TelemetryOutbox.published_at.is_(None))
        )
    assert pending == 0


async def test_usage_increments_across_requests(client: AsyncClient) -> None:
    slug, key = await _setup_api(client, "tel3@e.com")
    with respx.mock(assert_all_mocked=False) as mock:
        mock.get(f"{UPSTREAM}/p").mock(return_value=httpx.Response(200, text="ok"))
        for _ in range(3):
            await client.get(f"/gw/{slug}/v1/p", headers={"X-API-Key": key})

    async with get_sessionmaker()() as session:
        row = (await session.execute(select(ApiKeyUsage))).scalar_one()
    assert row.request_count == 3
    assert row.error_count == 0


async def test_error_response_counted(client: AsyncClient) -> None:
    slug, key = await _setup_api(client, "tel4@e.com")
    with respx.mock(assert_all_mocked=False) as mock:
        mock.get(f"{UPSTREAM}/e").mock(return_value=httpx.Response(500, text="boom"))
        await client.get(f"/gw/{slug}/v1/e", headers={"X-API-Key": key})

    async with get_sessionmaker()() as session:
        row = (await session.execute(select(ApiKeyUsage))).scalar_one()
    assert row.error_count == 1


async def test_api_key_actions_are_audited(client: AsyncClient) -> None:
    await client.post("/auth/register", json={"email": "aud@e.com", "password": "password123"})
    token = (
        await client.post("/auth/login", json={"email": "aud@e.com", "password": "password123"})
    ).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    org_id = (await client.post("/organizations", json={"name": "Org"}, headers=h)).json()["id"]
    api_id = (
        await client.post(f"/organizations/{org_id}/apis", json={"name": "A"}, headers=h)
    ).json()["id"]
    key_id = (
        await client.post(f"/organizations/{org_id}/apis/{api_id}/keys", json={}, headers=h)
    ).json()["id"]
    await client.delete(f"/organizations/{org_id}/apis/{api_id}/keys/{key_id}", headers=h)

    # Audit endpoint reflects both actions.
    logs = await client.get(f"/organizations/{org_id}/audit-logs", headers=h)
    assert logs.status_code == 200
    actions = {row["action"] for row in logs.json()}
    assert {"api_key.create", "api_key.revoke"} <= actions

    # And the same actions are queued as telemetry.
    async with get_sessionmaker()() as session:
        audit_count = await session.scalar(select(func.count()).select_from(AuditLog))
        audit_events = await session.scalar(
            select(func.count())
            .select_from(TelemetryOutbox)
            .where(TelemetryOutbox.event_type == "audit_log")
        )
    assert audit_count == 2
    assert audit_events == 2
