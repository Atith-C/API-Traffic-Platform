"""Security primitives: password hashing, JWT access tokens, refresh-token secrets.

Password hashing uses Argon2id (memory-hard, the modern OWASP recommendation). Access tokens are
short-lived signed JWTs. Refresh tokens are opaque high-entropy secrets: the raw value goes to the
client, only a SHA-256 hash is stored, and they are rotated on every use with family reuse-detection
(handled in the auth service).
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings

_password_hasher = PasswordHasher()


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """True if the hash used outdated parameters and should be upgraded on next login."""
    return _password_hasher.check_needs_rehash(password_hash)


# ---------------------------------------------------------------------------
# Access tokens (JWT)
# ---------------------------------------------------------------------------
def create_access_token(
    *,
    subject: str,
    extra_claims: dict[str, Any] | None = None,
    ttl_seconds: int | None = None,
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    ttl = ttl_seconds if ttl_seconds is not None else settings.access_token_ttl_seconds
    payload: dict[str, Any] = {
        "sub": subject,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode & verify a JWT. Raises ``jwt.PyJWTError`` subclasses on failure."""
    settings = get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub", "type"]},
    )


# ---------------------------------------------------------------------------
# Action tokens (email verification, password reset) — short-lived signed JWTs
# ---------------------------------------------------------------------------
def create_action_token(
    *, subject: str, purpose: str, ttl_seconds: int, extra_claims: dict[str, Any] | None = None
) -> str:
    """Signed, self-contained token for a one-off action (e.g. verify email / reset password).

    ``purpose`` is encoded as the token ``type`` and must match on decode, so a verification token
    can never be replayed as a reset token. Single-use is achieved by callers binding a state
    fingerprint (e.g. the current password hash) into ``extra_claims``.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": purpose,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_action_token(token: str, *, purpose: str) -> dict[str, Any]:
    """Decode an action token and assert its ``type`` matches ``purpose``. Raises on mismatch."""
    settings = get_settings()
    claims = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub", "type"]},
    )
    if claims.get("type") != purpose:
        raise jwt.InvalidTokenError("token purpose mismatch")
    return claims


# ---------------------------------------------------------------------------
# Refresh tokens (opaque secrets, stored hashed)
# ---------------------------------------------------------------------------
def generate_refresh_token() -> str:
    """A URL-safe, high-entropy opaque token handed to the client (never stored raw)."""
    return secrets.token_urlsafe(48)


def hash_token(raw: str) -> str:
    """Deterministic SHA-256 hash for lookup of opaque tokens / API keys."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# API keys (shown once, stored hashed)
# ---------------------------------------------------------------------------
API_KEY_PREFIX = "atp"


@dataclass(frozen=True)
class GeneratedApiKey:
    full_key: str  # shown to the user exactly once
    prefix: str  # public identifier, safe to store/display (e.g. "atp_ab12cd34")
    last_four: str
    key_hash: str  # what we persist


def generate_api_key() -> GeneratedApiKey:
    """Create a new API key. The full value is returned once; only its hash should be stored."""
    public_id = secrets.token_hex(4)  # 8 hex chars
    secret = secrets.token_urlsafe(32)
    prefix = f"{API_KEY_PREFIX}_{public_id}"
    full_key = f"{prefix}_{secret}"
    return GeneratedApiKey(
        full_key=full_key,
        prefix=prefix,
        last_four=secret[-4:],
        key_hash=hash_token(full_key),
    )
