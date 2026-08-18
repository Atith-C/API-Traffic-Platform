"""Integration tests for AuthService against a real database.

These exercise the security-critical logic directly (no HTTP): refresh rotation, reuse detection,
and single-use password reset.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, ConflictError, ValidationAppError
from app.repositories.user import RefreshTokenRepository, UserRepository
from app.services.auth import AuthService
from app.services.email import ConsoleEmailSender
from tests.conftest import requires_docker

pytestmark = [requires_docker, pytest.mark.integration]


def _service(session: AsyncSession) -> tuple[AuthService, ConsoleEmailSender]:
    sender = ConsoleEmailSender()
    service = AuthService(
        users=UserRepository(session),
        refresh_tokens=RefreshTokenRepository(session),
        email_sender=sender,
    )
    return service, sender


async def test_register_sends_verification_and_rejects_duplicates(db_session: AsyncSession) -> None:
    service, sender = _service(db_session)
    user = await service.register(email="A@Example.com", password="password123", full_name="A")
    assert user.email == "a@example.com"  # normalized
    assert user.is_email_verified is False
    assert len(sender.sent) == 1

    with pytest.raises(ConflictError):
        await service.register(email="a@example.com", password="password123", full_name="A")


async def test_authenticate_success_and_failure(db_session: AsyncSession) -> None:
    service, _ = _service(db_session)
    await service.register(email="u@e.com", password="password123", full_name=None)

    user = await service.authenticate(email="u@e.com", password="password123")
    assert user.email == "u@e.com"

    with pytest.raises(AuthenticationError):
        await service.authenticate(email="u@e.com", password="wrong")
    with pytest.raises(AuthenticationError):
        await service.authenticate(email="missing@e.com", password="whatever")


async def test_refresh_rotation_and_reuse_detection(db_session: AsyncSession) -> None:
    service, _ = _service(db_session)
    user = await service.register(email="r@e.com", password="password123", full_name=None)
    first = await service.issue_tokens(user)

    # Rotating returns a new refresh token and invalidates the old.
    second = await service.rotate(first.refresh_token)
    assert second.refresh_token != first.refresh_token

    # Reusing the *original* (now revoked) token is detected as theft and kills the family.
    with pytest.raises(AuthenticationError):
        await service.rotate(first.refresh_token)

    # ...which also revokes the legitimate successor.
    with pytest.raises(AuthenticationError):
        await service.rotate(second.refresh_token)


async def test_logout_revokes_refresh(db_session: AsyncSession) -> None:
    service, _ = _service(db_session)
    user = await service.register(email="l@e.com", password="password123", full_name=None)
    tokens = await service.issue_tokens(user)
    await service.logout(tokens.refresh_token)
    with pytest.raises(AuthenticationError):
        await service.rotate(tokens.refresh_token)


async def test_password_reset_is_single_use(db_session: AsyncSession) -> None:
    service, sender = _service(db_session)
    await service.register(email="p@e.com", password="password123", full_name=None)
    sender.sent.clear()

    await service.request_password_reset("p@e.com")
    assert len(sender.sent) == 1
    token = sender.sent[0].body.split()[-1]

    await service.reset_password(token, "newpassword456")
    # Old password no longer works; new one does.
    await service.authenticate(email="p@e.com", password="newpassword456")
    with pytest.raises(AuthenticationError):
        await service.authenticate(email="p@e.com", password="password123")

    # The same reset token cannot be used twice (bound to the old password hash).
    with pytest.raises(ValidationAppError):
        await service.reset_password(token, "anotherpass789")


async def test_email_verification(db_session: AsyncSession) -> None:
    service, sender = _service(db_session)
    user = await service.register(email="v@e.com", password="password123", full_name=None)
    token = sender.sent[0].body.split()[-1]
    verified = await service.verify_email(token)
    assert verified.id == user.id
    assert verified.is_email_verified is True
