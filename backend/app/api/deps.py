"""Shared FastAPI dependencies (dependency injection wiring at the edge).

These functions assemble services from repositories + session + external clients, and provide the
authenticated-user dependency. Business logic lives in services; this module only wires them.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated

import jwt
import structlog
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.permissions import Permission, RoleName, role_has_permission
from app.core.redis import get_redis
from app.core.security import decode_access_token
from app.db.session import get_session
from app.models.organization import OrganizationMember
from app.models.user import User
from app.repositories.organization import (
    MembershipRepository,
    OrganizationRepository,
    RoleRepository,
)
from app.repositories.user import RefreshTokenRepository, UserRepository
from app.services.auth import AuthService
from app.services.auth_throttle import AuthThrottle
from app.services.email import EmailSender, get_email_sender
from app.services.organization import OrganizationService

if TYPE_CHECKING:
    from app.services.api_catalog import ApiCatalogService
    from app.services.api_key import ApiKeyService
    from app.services.gateway import GatewayService

logger = structlog.get_logger(__name__)

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_bearer = HTTPBearer(auto_error=False)


def get_auth_service(
    session: SessionDep,
    email_sender: Annotated[EmailSender, Depends(get_email_sender)],
) -> AuthService:
    return AuthService(
        users=UserRepository(session),
        refresh_tokens=RefreshTokenRepository(session),
        email_sender=email_sender,
        memberships=MembershipRepository(session),
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def get_auth_throttle() -> AuthThrottle:
    return AuthThrottle(get_redis())


AuthThrottleDep = Annotated[AuthThrottle, Depends(get_auth_throttle)]


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """Resolve the caller from a Bearer access token. Raises 401 on any problem."""
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Missing bearer token.")
    try:
        claims = decode_access_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid or expired access token.") from exc
    if claims.get("type") != "access":
        raise AuthenticationError("Wrong token type.")
    user = await session.get(User, uuid.UUID(claims["sub"]))
    if user is None or not user.is_active:
        raise AuthenticationError("User not found or inactive.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_superuser(current_user: CurrentUser) -> User:
    if not current_user.is_superuser:
        raise PermissionDeniedError("Superuser privileges are required.")
    return current_user


CurrentSuperuser = Annotated[User, Depends(get_current_superuser)]


def get_api_catalog_service(session: SessionDep) -> ApiCatalogService:
    from app.repositories.api import (
        ApiRepository,
        ApiVersionRepository,
        QuotaRepository,
        RateLimitRuleRepository,
    )
    from app.services.api_catalog import ApiCatalogService

    return ApiCatalogService(
        apis=ApiRepository(session),
        versions=ApiVersionRepository(session),
        quotas=QuotaRepository(session),
        rate_limits=RateLimitRuleRepository(session),
    )


ApiCatalogServiceDep = Annotated["ApiCatalogService", Depends(get_api_catalog_service)]


def get_api_key_service(session: SessionDep) -> ApiKeyService:
    from app.repositories.api_key import ApiKeyRepository
    from app.services.api_key import ApiKeyService

    return ApiKeyService(
        keys=ApiKeyRepository(session),
        catalog=get_api_catalog_service(session),
    )


ApiKeyServiceDep = Annotated["ApiKeyService", Depends(get_api_key_service)]


def get_gateway_service(session: SessionDep) -> GatewayService:
    from app.core.http_client import get_http_client
    from app.repositories.api import (
        ApiVersionRepository,
        QuotaRepository,
        RateLimitRuleRepository,
    )
    from app.repositories.api_key import ApiKeyRepository
    from app.services.gateway import GatewayService

    return GatewayService(
        api_keys=ApiKeyRepository(session),
        versions=ApiVersionRepository(session),
        rate_limits=RateLimitRuleRepository(session),
        quotas=QuotaRepository(session),
        redis_client=get_redis(),
        http_client=get_http_client(),
    )


GatewayServiceDep = Annotated["GatewayService", Depends(get_gateway_service)]


def get_org_service(session: SessionDep) -> OrganizationService:
    return OrganizationService(
        organizations=OrganizationRepository(session),
        members=MembershipRepository(session),
        roles=RoleRepository(session),
        users=UserRepository(session),
    )


OrgServiceDep = Annotated[OrganizationService, Depends(get_org_service)]


def require_permission(permission: Permission):
    """Build a dependency that authorizes the caller for ``permission`` in the path's organization.

    Resolves the caller's membership in ``{org_id}``, checks their role grants the permission, and
    returns the membership so handlers can use it. Superusers bypass the membership requirement.
    """

    async def dependency(
        org_id: uuid.UUID,
        current_user: CurrentUser,
        session: SessionDep,
    ) -> OrganizationMember:
        member = await MembershipRepository(session).get_for_user_and_org(
            user_id=current_user.id, organization_id=org_id
        )
        if member is None:
            if current_user.is_superuser:
                raise PermissionDeniedError(
                    "Superuser access to organizations requires membership."
                )
            raise PermissionDeniedError("You are not a member of this organization.")
        if not role_has_permission(RoleName(member.role.name), permission):
            raise PermissionDeniedError(
                f"Your role '{member.role.name}' lacks the '{permission}' permission."
            )
        return member

    return dependency


def client_ip(request: Request) -> str:
    """Best-effort client IP (honours a single X-Forwarded-For hop for typical proxy setups)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
