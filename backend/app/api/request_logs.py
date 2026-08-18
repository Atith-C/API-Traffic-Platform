"""Request-log search endpoint — structured filtering over the raw gateway logs.

Requires ``analytics:read``. Supports filtering by API, method, status range, path substring, and a
time window, with pagination.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from app.api.deps import SessionDep, require_permission
from app.core.permissions import Permission
from app.models.organization import OrganizationMember
from app.repositories.telemetry import RequestLogRepository
from app.schemas.common import Page

router = APIRouter(prefix="/organizations/{org_id}/request-logs", tags=["request-logs"])


class RequestLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    api_id: uuid.UUID
    api_version_id: uuid.UUID
    api_key_id: uuid.UUID | None
    method: str
    path: str
    status_code: int
    latency_ms: float
    request_bytes: int
    response_bytes: int
    client_ip: str
    created_at: datetime


@router.get("", response_model=Page[RequestLogResponse])
async def search_request_logs(
    org_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[OrganizationMember, Depends(require_permission(Permission.ANALYTICS_READ))],
    api_id: uuid.UUID | None = None,
    method: str | None = None,
    status_min: Annotated[int | None, Query(ge=100, le=599)] = None,
    status_max: Annotated[int | None, Query(ge=100, le=599)] = None,
    path_contains: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[RequestLogResponse]:
    logs, total = await RequestLogRepository(session).search(
        organization_id=org_id,
        api_id=api_id,
        method=method,
        status_min=status_min,
        status_max=status_max,
        path_contains=path_contains,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return Page(
        items=[RequestLogResponse.model_validate(log) for log in logs],
        total=total,
        limit=limit,
        offset=offset,
    )
