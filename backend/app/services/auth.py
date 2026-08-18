"""Authentication service — the business logic behind the auth API.

Framework-agnostic: it receives a session, repositories, and an email sender by construction and
knows nothing about FastAPI. Covers registration, login, refresh-token rotation with reuse
detection, logout, email verification, and password reset.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import jwt
import structlog

if TYPE_CHECKING:
    from app.repositories.organization import MembershipRepository

from app.core.config import Settings, get_settings
from app.core.errors import AuthenticationError, ConflictError, ValidationAppError
from app.core.security import (
    create_access_token,
    create_action_token,
    decode_action_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    verify_password,
)
from app.models.user import RefreshToken, User
from app.repositories.user import RefreshTokenRepository, UserRepository
from app.services.email import EmailMessage, EmailSender

logger = structlog.get_logger(__name__)

VERIFY_PURPOSE = "email_verify"
RESET_PURPOSE = "password_reset"
VERIFY_TTL = 60 * 60 * 24  # 24h
RESET_TTL = 60 * 60  # 1h


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int


class AuthService:
    def __init__(
        self,
        *,
        users: UserRepository,
        refresh_tokens: RefreshTokenRepository,
        email_sender: EmailSender,
        memberships: MembershipRepository | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.users = users
        self.refresh_tokens = refresh_tokens
        self.email_sender = email_sender
        # Optional: when provided, the access token carries an ``orgs`` claim (org_id + role) so
        # downstream products (Project B) can authorize the user without a shared database.
        self.memberships = memberships
        self.settings = settings or get_settings()

    # ---- Registration ----
    async def register(self, *, email: str, password: str, full_name: str | None) -> User:
        email = email.lower()
        if await self.users.get_by_email(email):
            raise ConflictError("An account with this email already exists.")
        user = User(
            email=email,
            full_name=full_name,
            password_hash=hash_password(password),
            is_active=True,
            is_email_verified=False,
        )
        await self.users.add(user)
        await self._send_verification_email(user)
        logger.info("user_registered", user_id=str(user.id), email=email)
        return user

    # ---- Login ----
    async def authenticate(self, *, email: str, password: str) -> User:
        user = await self.users.get_by_email(email.lower())
        # Constant-ish behaviour: verify against a dummy hash if user missing to reduce timing leak.
        if user is None:
            hash_password(password)  # burn time
            raise AuthenticationError("Invalid email or password.")
        if not verify_password(password, user.password_hash):
            raise AuthenticationError("Invalid email or password.")
        if not user.is_active:
            raise AuthenticationError("Account is disabled.")
        # Opportunistically upgrade the hash if parameters changed.
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        return user

    # ---- Token issuance & rotation ----
    async def issue_tokens(self, user: User, *, family_id: uuid.UUID | None = None) -> IssuedTokens:
        raw_refresh = generate_refresh_token()
        family = family_id or uuid.uuid4()
        token = RefreshToken(
            user_id=user.id,
            family_id=family,
            token_hash=hash_token(raw_refresh),
            expires_at=datetime.now(UTC)
            + timedelta(seconds=self.settings.refresh_token_ttl_seconds),
        )
        await self.refresh_tokens.add(token)
        extra_claims: dict = {"email": user.email}
        if self.memberships is not None:
            org_roles = await self.memberships.list_org_roles_for_user(user.id)
            extra_claims["orgs"] = [
                {"org_id": str(org_id), "role": role} for org_id, role in org_roles
            ]
        access = create_access_token(subject=str(user.id), extra_claims=extra_claims)
        return IssuedTokens(
            access_token=access,
            refresh_token=raw_refresh,
            expires_in=self.settings.access_token_ttl_seconds,
        )

    async def rotate(self, raw_refresh: str) -> IssuedTokens:
        stored = await self.refresh_tokens.get_by_hash(hash_token(raw_refresh))
        if stored is None:
            raise AuthenticationError("Invalid refresh token.")

        # Reuse detection: a token that was already revoked/rotated is being replayed => theft.
        if stored.revoked_at is not None:
            await self.refresh_tokens.revoke_family(stored.family_id)
            logger.warning(
                "refresh_reuse_detected",
                family_id=str(stored.family_id),
                user_id=str(stored.user_id),
            )
            raise AuthenticationError("Refresh token has been revoked.")

        if stored.expires_at <= datetime.now(UTC):
            await self.refresh_tokens.revoke(stored)
            raise AuthenticationError("Refresh token has expired.")

        user = await self.users.get(stored.user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("Account is unavailable.")

        # Rotate: revoke the old, issue a successor in the same family.
        tokens = await self.issue_tokens(user, family_id=stored.family_id)
        stored.revoked_at = datetime.now(UTC)
        successor = await self.refresh_tokens.get_by_hash(hash_token(tokens.refresh_token))
        stored.rotated_to = successor.id if successor else None
        return tokens

    async def logout(self, raw_refresh: str) -> None:
        stored = await self.refresh_tokens.get_by_hash(hash_token(raw_refresh))
        if stored and stored.revoked_at is None:
            await self.refresh_tokens.revoke(stored)

    # ---- Email verification ----
    async def _send_verification_email(self, user: User) -> None:
        token = create_action_token(
            subject=str(user.id), purpose=VERIFY_PURPOSE, ttl_seconds=VERIFY_TTL
        )
        await self.email_sender.send(
            EmailMessage(
                to=user.email,
                subject="Verify your email",
                body=f"Use this token to verify your email: {token}",
            )
        )

    async def verify_email(self, token: str) -> User:
        try:
            claims = decode_action_token(token, purpose=VERIFY_PURPOSE)
        except jwt.PyJWTError as exc:
            raise ValidationAppError("Invalid or expired verification token.") from exc
        user = await self.users.get(uuid.UUID(claims["sub"]))
        if user is None:
            raise ValidationAppError("Invalid verification token.")
        user.is_email_verified = True
        return user

    # ---- Password reset ----
    async def request_password_reset(self, email: str) -> None:
        user = await self.users.get_by_email(email.lower())
        # Do not reveal whether the email exists.
        if user is None:
            logger.info("password_reset_requested_unknown_email")
            return
        token = create_action_token(
            subject=str(user.id),
            purpose=RESET_PURPOSE,
            ttl_seconds=RESET_TTL,
            # Bind to current password hash => token is single-use (invalid once password changes).
            extra_claims={"pfp": hash_token(user.password_hash)[:16]},
        )
        await self.email_sender.send(
            EmailMessage(
                to=user.email,
                subject="Reset your password",
                body=f"Use this token to reset your password: {token}",
            )
        )

    async def reset_password(self, token: str, new_password: str) -> User:
        try:
            claims = decode_action_token(token, purpose=RESET_PURPOSE)
        except jwt.PyJWTError as exc:
            raise ValidationAppError("Invalid or expired reset token.") from exc
        user = await self.users.get(uuid.UUID(claims["sub"]))
        if user is None:
            raise ValidationAppError("Invalid reset token.")
        if claims.get("pfp") != hash_token(user.password_hash)[:16]:
            raise ValidationAppError("This reset token has already been used.")
        user.password_hash = hash_password(new_password)
        # Revoke all refresh tokens on password reset (security best practice).
        for rt in await self._active_tokens_for(user.id):
            rt.revoked_at = datetime.now(UTC)
        return user

    async def _active_tokens_for(self, user_id: uuid.UUID) -> list[RefreshToken]:
        from sqlalchemy import select

        result = await self.refresh_tokens.session.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
            )
        )
        return list(result.scalars().all())
