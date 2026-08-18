"""API key endpoints (nested under an API within an organization).

The full key value is returned exactly once, on create and on rotate. Afterwards only metadata
(prefix, last four, status) is ever exposed.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import ApiKeyServiceDep, CurrentUser, SessionDep, client_ip, require_permission
from app.core.permissions import Permission
from app.models.organization import OrganizationMember
from app.schemas.api_key import (
    ApiKeyCreate,
    ApiKeyCreatedResponse,
    ApiKeyResponse,
    ApiKeyRotateRequest,
)
from app.services.audit import AuditLogService

router = APIRouter(prefix="/organizations/{org_id}/apis/{api_id}/keys", tags=["api-keys"])

_ReadDep = Annotated[OrganizationMember, Depends(require_permission(Permission.KEY_READ))]
_CreateDep = Annotated[OrganizationMember, Depends(require_permission(Permission.KEY_CREATE))]
_RevokeDep = Annotated[OrganizationMember, Depends(require_permission(Permission.KEY_REVOKE))]
_RotateDep = Annotated[OrganizationMember, Depends(require_permission(Permission.KEY_ROTATE))]


@router.post("", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_key(
    org_id: uuid.UUID,
    api_id: uuid.UUID,
    payload: ApiKeyCreate,
    current_user: CurrentUser,
    service: ApiKeyServiceDep,
    session: SessionDep,
    request: Request,
    _: _CreateDep,
) -> ApiKeyCreatedResponse:
    issued = await service.create_key(
        organization_id=org_id,
        api_id=api_id,
        name=payload.name,
        expires_in_days=payload.expires_in_days,
        created_by_user_id=current_user.id,
    )
    await AuditLogService(session).record(
        action="api_key.create",
        resource_type="api_key",
        organization_id=org_id,
        actor_user_id=current_user.id,
        resource_id=issued.record.id,
        ip=client_ip(request),
        metadata={"api_id": str(api_id)},
    )
    return ApiKeyCreatedResponse(
        **ApiKeyResponse.model_validate(issued.record).model_dump(),
        api_key=issued.full_key,
    )


@router.get("", response_model=list[ApiKeyResponse])
async def list_keys(
    org_id: uuid.UUID, api_id: uuid.UUID, service: ApiKeyServiceDep, _: _ReadDep
) -> list[ApiKeyResponse]:
    keys = await service.list_keys(organization_id=org_id, api_id=api_id)
    return [ApiKeyResponse.model_validate(k) for k in keys]


@router.post("/{key_id}/rotate", response_model=ApiKeyCreatedResponse)
async def rotate_key(
    org_id: uuid.UUID,
    api_id: uuid.UUID,
    key_id: uuid.UUID,
    payload: ApiKeyRotateRequest,
    current_user: CurrentUser,
    service: ApiKeyServiceDep,
    session: SessionDep,
    request: Request,
    _: _RotateDep,
) -> ApiKeyCreatedResponse:
    issued = await service.rotate_key(
        organization_id=org_id,
        api_id=api_id,
        key_id=key_id,
        grace_period_hours=payload.grace_period_hours,
        created_by_user_id=current_user.id,
    )
    await AuditLogService(session).record(
        action="api_key.rotate",
        resource_type="api_key",
        organization_id=org_id,
        actor_user_id=current_user.id,
        resource_id=key_id,
        ip=client_ip(request),
        metadata={"new_key_id": str(issued.record.id)},
    )
    return ApiKeyCreatedResponse(
        **ApiKeyResponse.model_validate(issued.record).model_dump(),
        api_key=issued.full_key,
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(
    org_id: uuid.UUID,
    api_id: uuid.UUID,
    key_id: uuid.UUID,
    current_user: CurrentUser,
    service: ApiKeyServiceDep,
    session: SessionDep,
    request: Request,
    _: _RevokeDep,
) -> None:
    await service.revoke_key(organization_id=org_id, api_id=api_id, key_id=key_id)
    await AuditLogService(session).record(
        action="api_key.revoke",
        resource_type="api_key",
        organization_id=org_id,
        actor_user_id=current_user.id,
        resource_id=key_id,
        ip=client_ip(request),
    )
