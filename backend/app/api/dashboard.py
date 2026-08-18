"""Dashboard endpoints.

- **Developer dashboard** (per org): a single call assembling the headline metrics a developer wants
  — usage summary, top endpoints, status breakdown, and API count.
- **Admin overview** (superuser): platform-wide health — organizations, APIs, recent traffic, error
  rate, and dependency health.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import CurrentSuperuser, SessionDep, require_permission
from app.api.health import _check_db, _check_redis
from app.core.permissions import Permission
from app.models.api import Api
from app.models.organization import Organization, OrganizationMember
from app.models.telemetry import RequestLog
from app.repositories.analytics import AnalyticsRepository
from app.services.analytics import AnalyticsService

router = APIRouter(tags=["dashboards"])


@router.get("/organizations/{org_id}/dashboard")
async def developer_dashboard(
    org_id: uuid.UUID,
    session: SessionDep,
    _: Annotated[OrganizationMember, Depends(require_permission(Permission.ANALYTICS_READ))],
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> dict[str, Any]:
    service = AnalyticsService(AnalyticsRepository(session))
    api_count = await session.scalar(
        select(func.count()).select_from(Api).where(Api.organization_id == org_id)
    )
    return {
        "summary": await service.summary(organization_id=org_id, api_id=None, days=days),
        "top_endpoints": await service.top_endpoints(
            organization_id=org_id, api_id=None, days=days, limit=5
        ),
        "status_breakdown": await service.status_breakdown(
            organization_id=org_id, api_id=None, days=days
        ),
        "top_keys": await service.top_keys(organization_id=org_id, days=days, limit=5),
        "api_count": int(api_count or 0),
    }


@router.get("/admin/overview")
async def admin_overview(
    _: CurrentSuperuser,
    session: SessionDep,
) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(hours=24)
    org_count = await session.scalar(select(func.count()).select_from(Organization))
    api_count = await session.scalar(select(func.count()).select_from(Api))
    active_api_count = await session.scalar(
        select(func.count()).select_from(Api).where(Api.is_active.is_(True))
    )
    total_24h = await session.scalar(
        select(func.count()).select_from(RequestLog).where(RequestLog.created_at >= since)
    )
    errors_24h = await session.scalar(
        select(func.count())
        .select_from(RequestLog)
        .where(RequestLog.created_at >= since, RequestLog.status_code >= 500)
    )
    total = int(total_24h or 0)
    return {
        "organizations": int(org_count or 0),
        "apis": int(api_count or 0),
        "active_apis": int(active_api_count or 0),
        "requests_24h": total,
        "errors_24h": int(errors_24h or 0),
        "error_rate_24h": round((int(errors_24h or 0) / total), 4) if total else 0.0,
        "health": {
            "database": (await _check_db()).status,
            "redis": (await _check_redis()).status,
        },
    }
