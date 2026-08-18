"""Unit tests for security primitives (no external deps)."""

from __future__ import annotations

import time

import jwt
import pytest

from app.core import security


def test_password_hash_and_verify() -> None:
    h = security.hash_password("s3cr3t-password")
    assert h != "s3cr3t-password"
    assert security.verify_password("s3cr3t-password", h) is True
    assert security.verify_password("wrong", h) is False


def test_verify_password_rejects_garbage_hash() -> None:
    assert security.verify_password("x", "not-a-valid-hash") is False


def test_access_token_roundtrip() -> None:
    token = security.create_access_token(subject="user-123", extra_claims={"email": "a@b.com"})
    claims = security.decode_access_token(token)
    assert claims["sub"] == "user-123"
    assert claims["type"] == "access"
    assert claims["email"] == "a@b.com"


def test_access_token_expired() -> None:
    token = security.create_access_token(subject="u", ttl_seconds=-1)
    time.sleep(0.01)
    with pytest.raises(jwt.ExpiredSignatureError):
        security.decode_access_token(token)


def test_action_token_purpose_enforced() -> None:
    token = security.create_action_token(subject="u", purpose="password_reset", ttl_seconds=60)
    # Correct purpose decodes.
    assert security.decode_action_token(token, purpose="password_reset")["sub"] == "u"
    # Wrong purpose is rejected (can't replay a reset token as a verify token).
    with pytest.raises(jwt.InvalidTokenError):
        security.decode_action_token(token, purpose="email_verify")


def test_refresh_token_is_high_entropy_and_hashable() -> None:
    raw1 = security.generate_refresh_token()
    raw2 = security.generate_refresh_token()
    assert raw1 != raw2
    assert len(raw1) > 40
    assert security.hash_token(raw1) == security.hash_token(raw1)
    assert security.hash_token(raw1) != security.hash_token(raw2)
