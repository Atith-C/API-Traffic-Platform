"""Analytics endpoints (require the ``analytics:read`` permission).

All are scoped to an organization and accept an optional ``api_id`` filter and a ``days`` window.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import SessionDep, require_permission
from app.core.permissions import Permission
from app.models.organization import OrganizationMember
from app.repositories.analytics import AnalyticsRepository
from app.schemas.analytics import (
    EndpointStat,
    KeyStat,
    SummaryResponse,
    TimeseriesPoint,
)
from app.services.analytics import AnalyticsService

router = APIRouter(prefix="/organizations/{org_id}/analytics", tags=["analytics"])

_ReadDep = Annotated[OrganizationMember, Depends(require_permission(Permission.ANALYTICS_READ))]
_Days = Annotated[int, Query(ge=1, le=365)]


def _service(session: SessionDep) -> AnalyticsService:
    return AnalyticsService(AnalyticsRepository(session))


@router.get("/summary", response_model=SummaryResponse)
async def summary(
    org_id: uuid.UUID,
    session: SessionDep,
    _: _ReadDep,
    api_id: uuid.UUID | None = None,
    days: _Days = 7,
) -> SummaryResponse:
    data = await _service(session).summary(organization_id=org_id, api_id=api_id, days=days)
    return SummaryResponse(**data)


@router.get("/top-endpoints", response_model=list[EndpointStat])
async def top_endpoints(
    org_id: uuid.UUID,
    session: SessionDep,
    _: _ReadDep,
    api_id: uuid.UUID | None = None,
    days: _Days = 7,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> list[EndpointStat]:
    rows = await _service(session).top_endpoints(
        organization_id=org_id, api_id=api_id, days=days, limit=limit
    )
    return [EndpointStat(**r) for r in rows]


@router.get("/status-breakdown", response_model=dict[str, int])
async def status_breakdown(
    org_id: uuid.UUID,
    session: SessionDep,
    _: _ReadDep,
    api_id: uuid.UUID | None = None,
    days: _Days = 7,
) -> dict[str, int]:
    return await _service(session).status_breakdown(
        organization_id=org_id, api_id=api_id, days=days
    )


@router.get("/timeseries", response_model=list[TimeseriesPoint])
async def timeseries(
    org_id: uuid.UUID,
    session: SessionDep,
    _: _ReadDep,
    api_id: uuid.UUID | None = None,
    days: _Days = 30,
) -> list[TimeseriesPoint]:
    rows = await _service(session).timeseries(organization_id=org_id, api_id=api_id, days=days)
    return [TimeseriesPoint(**r) for r in rows]


@router.get("/top-keys", response_model=list[KeyStat])
async def top_keys(
    org_id: uuid.UUID,
    session: SessionDep,
    _: _ReadDep,
    days: _Days = 7,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> list[KeyStat]:
    rows = await _service(session).top_keys(organization_id=org_id, days=days, limit=limit)
    return [KeyStat(**r) for r in rows]
