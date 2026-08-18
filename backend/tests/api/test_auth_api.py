"""End-to-end API tests for the auth flow (real DB + Redis via the app)."""

from __future__ import annotations

import jwt
import pytest
from httpx import AsyncClient

from tests.conftest import requires_docker

pytestmark = [requires_docker, pytest.mark.integration]


async def test_access_token_carries_orgs_claim(client: AsyncClient) -> None:
    """Integration contract with Project B: the token embeds the user's org memberships + roles."""
    await client.post("/auth/register", json={"email": "claim@e.com", "password": "password123"})
    token1 = (
        await client.post("/auth/login", json={"email": "claim@e.com", "password": "password123"})
    ).json()["access_token"]
    org_id = (
        await client.post(
            "/organizations",
            json={"name": "Claim Co"},
            headers={"Authorization": f"Bearer {token1}"},
        )
    ).json()["id"]
    # Re-login so the fresh token reflects the new membership.
    token2 = (
        await client.post("/auth/login", json={"email": "claim@e.com", "password": "password123"})
    ).json()["access_token"]
    claims = jwt.decode(token2, options={"verify_signature": False})
    assert {"org_id": org_id, "role": "owner"} in claims["orgs"]


async def _register(client: AsyncClient, email: str, password: str = "password123") -> None:
    resp = await client.post(
        "/auth/register", json={"email": email, "password": password, "full_name": "T"}
    )
    assert resp.status_code == 201, resp.text


async def test_register_login_me_flow(client: AsyncClient) -> None:
    await _register(client, "flow@e.com")

    resp = await client.post("/auth/login", json={"email": "flow@e.com", "password": "password123"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    access = body["access_token"]
    assert body["token_type"] == "bearer"
    assert "refresh_token" in body

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200
    assert me.json()["email"] == "flow@e.com"


async def test_me_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/auth/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthenticated"


async def test_duplicate_registration_conflicts(client: AsyncClient) -> None:
    await _register(client, "dup@e.com")
    resp = await client.post(
        "/auth/register", json={"email": "dup@e.com", "password": "password123"}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


async def test_login_wrong_password(client: AsyncClient) -> None:
    await _register(client, "wp@e.com")
    resp = await client.post("/auth/login", json={"email": "wp@e.com", "password": "nope-nope"})
    assert resp.status_code == 401


async def test_refresh_rotation_via_cookie(client: AsyncClient) -> None:
    await _register(client, "cook@e.com")
    login = await client.post(
        "/auth/login", json={"email": "cook@e.com", "password": "password123"}
    )
    old_refresh = login.json()["refresh_token"]

    # Refresh using the cookie set by login.
    r1 = await client.post("/auth/refresh", json={})
    assert r1.status_code == 200
    assert r1.json()["refresh_token"] != old_refresh

    # Replaying the original refresh token is rejected (reuse detection).
    r2 = await client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert r2.status_code == 401


async def test_password_reset_response_is_uniform(client: AsyncClient) -> None:
    # Unknown email must not reveal non-existence.
    resp = await client.post("/auth/password-reset", json={"email": "ghost@e.com"})
    assert resp.status_code == 200
    assert "reset link" in resp.json()["message"].lower()


async def test_validation_error_envelope(client: AsyncClient) -> None:
    resp = await client.post("/auth/register", json={"email": "not-an-email", "password": "x"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"
