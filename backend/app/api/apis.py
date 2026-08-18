"""API-catalog endpoints (nested under an organization).

Routes live under ``/organizations/{org_id}/apis`` so the ``require_permission`` dependency resolves
the caller's membership in that org. Ownership of the API within the org is enforced in the service.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import ApiCatalogServiceDep, require_permission
from app.core.permissions import Permission
from app.models.organization import OrganizationMember
from app.schemas.api import (
    ApiCreate,
    ApiResponse,
    ApiUpdate,
    ApiVersionCreate,
    ApiVersionResponse,
    QuotaConfig,
    QuotaItem,
    RateLimitConfig,
    RateLimitResponse,
)
from app.schemas.common import Page

router = APIRouter(prefix="/organizations/{org_id}/apis", tags=["apis"])

# Reusable permission dependencies.
_ReadDep = Annotated[OrganizationMember, Depends(require_permission(Permission.API_READ))]
_CreateDep = Annotated[OrganizationMember, Depends(require_permission(Permission.API_CREATE))]
_UpdateDep = Annotated[OrganizationMember, Depends(require_permission(Permission.API_UPDATE))]
_DeleteDep = Annotated[OrganizationMember, Depends(require_permission(Permission.API_DELETE))]


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def create_api(
    org_id: uuid.UUID, payload: ApiCreate, service: ApiCatalogServiceDep, _: _CreateDep
) -> ApiResponse:
    api = await service.create_api(
        organization_id=org_id,
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
    )
    return ApiResponse.model_validate(api)


@router.get("", response_model=Page[ApiResponse])
async def list_apis(
    org_id: uuid.UUID,
    service: ApiCatalogServiceDep,
    _: _ReadDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ApiResponse]:
    apis, total = await service.list_apis(organization_id=org_id, limit=limit, offset=offset)
    return Page(
        items=[ApiResponse.model_validate(a) for a in apis],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{api_id}", response_model=ApiResponse)
async def get_api(
    org_id: uuid.UUID, api_id: uuid.UUID, service: ApiCatalogServiceDep, _: _ReadDep
) -> ApiResponse:
    api = await service.get_api(organization_id=org_id, api_id=api_id)
    return ApiResponse.model_validate(api)


@router.patch("/{api_id}", response_model=ApiResponse)
async def update_api(
    org_id: uuid.UUID,
    api_id: uuid.UUID,
    payload: ApiUpdate,
    service: ApiCatalogServiceDep,
    _: _UpdateDep,
) -> ApiResponse:
    api = await service.update_api(
        organization_id=org_id,
        api_id=api_id,
        name=payload.name,
        description=payload.description,
        is_active=payload.is_active,
    )
    return ApiResponse.model_validate(api)


@router.delete("/{api_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api(
    org_id: uuid.UUID, api_id: uuid.UUID, service: ApiCatalogServiceDep, _: _DeleteDep
) -> None:
    await service.delete_api(organization_id=org_id, api_id=api_id)


# ---- Versions ----
@router.post(
    "/{api_id}/versions", response_model=ApiVersionResponse, status_code=status.HTTP_201_CREATED
)
async def add_version(
    org_id: uuid.UUID,
    api_id: uuid.UUID,
    payload: ApiVersionCreate,
    service: ApiCatalogServiceDep,
    _: _UpdateDep,
) -> ApiVersionResponse:
    version = await service.add_version(
        organization_id=org_id,
        api_id=api_id,
        version=payload.version,
        upstream_base_url=str(payload.upstream_base_url),
        is_active=payload.is_active,
    )
    return ApiVersionResponse.model_validate(version)


@router.delete("/{api_id}/versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_version(
    org_id: uuid.UUID,
    api_id: uuid.UUID,
    version_id: uuid.UUID,
    service: ApiCatalogServiceDep,
    _: _UpdateDep,
) -> None:
    await service.delete_version(organization_id=org_id, api_id=api_id, version_id=version_id)


# ---- Quotas ----
@router.put("/{api_id}/quota", response_model=list[QuotaItem])
async def set_quota(
    org_id: uuid.UUID,
    api_id: uuid.UUID,
    payload: QuotaConfig,
    service: ApiCatalogServiceDep,
    _: _UpdateDep,
) -> list[QuotaItem]:
    quotas = await service.set_quotas(
        organization_id=org_id,
        api_id=api_id,
        quotas=[(q.period, q.max_requests) for q in payload.quotas],
    )
    return [QuotaItem(period=q.period, max_requests=q.max_requests) for q in quotas]


@router.get("/{api_id}/quota", response_model=list[QuotaItem])
async def get_quota(
    org_id: uuid.UUID, api_id: uuid.UUID, service: ApiCatalogServiceDep, _: _ReadDep
) -> list[QuotaItem]:
    quotas = await service.get_quotas(organization_id=org_id, api_id=api_id)
    return [QuotaItem(period=q.period, max_requests=q.max_requests) for q in quotas]


# ---- Rate limit ----
@router.put("/{api_id}/rate-limit", response_model=RateLimitResponse)
async def set_rate_limit(
    org_id: uuid.UUID,
    api_id: uuid.UUID,
    payload: RateLimitConfig,
    service: ApiCatalogServiceDep,
    _: _UpdateDep,
) -> RateLimitResponse:
    rule = await service.set_rate_limit(
        organization_id=org_id,
        api_id=api_id,
        algorithm=payload.algorithm,
        requests=payload.requests,
        window_seconds=payload.window_seconds,
        burst=payload.burst,
    )
    return RateLimitResponse.model_validate(rule)


@router.get("/{api_id}/rate-limit", response_model=RateLimitResponse | None)
async def get_rate_limit(
    org_id: uuid.UUID, api_id: uuid.UUID, service: ApiCatalogServiceDep, _: _ReadDep
) -> RateLimitResponse | None:
    rule = await service.get_rate_limit(organization_id=org_id, api_id=api_id)
    return RateLimitResponse.model_validate(rule) if rule else None
