"""Audit-log read endpoint (requires the ``audit:read`` permission)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import SessionDep, require_permission
from app.core.permissions import Permission
from app.models.organization import OrganizationMember
from app.repositories.telemetry import AuditLogRepository

router = APIRouter(prefix="/organizations/{org_id}/audit-logs", tags=["audit"])


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action: str
    resource_type: str
    resource_id: uuid.UUID | None
    actor_user_id: uuid.UUID | None
    ip: str | None
    metadata: dict[str, Any] = Field(validation_alias="audit_metadata", default_factory=dict)
    created_at: datetime


@router.get("", response_model=list[AuditLogResponse])
async def list_audit_logs(
    org_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[OrganizationMember, Depends(require_permission(Permission.AUDIT_READ))],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditLogResponse]:
    logs = await AuditLogRepository(session).list_for_org(
        organization_id=org_id, limit=limit, offset=offset
    )
    return [AuditLogResponse.model_validate(log) for log in logs]
