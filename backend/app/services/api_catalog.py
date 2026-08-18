"""API-catalog business logic: register APIs, manage versions, configure quotas & rate limits.

All operations are scoped to an organization and validate ownership (an API's ``organization_id``
must match the org in the request path), so cross-tenant access is impossible even with a valid id.
"""

from __future__ import annotations

import uuid

import structlog

from app.core.errors import ConflictError, NotFoundError
from app.models.api import (
    Api,
    ApiVersion,
    Quota,
    QuotaPeriod,
    RateLimitAlgorithm,
    RateLimitRule,
)
from app.repositories.api import (
    ApiRepository,
    ApiVersionRepository,
    QuotaRepository,
    RateLimitRuleRepository,
)
from app.services.organization import slugify

logger = structlog.get_logger(__name__)


class ApiCatalogService:
    def __init__(
        self,
        *,
        apis: ApiRepository,
        versions: ApiVersionRepository,
        quotas: QuotaRepository,
        rate_limits: RateLimitRuleRepository,
    ) -> None:
        self.apis = apis
        self.versions = versions
        self.quotas = quotas
        self.rate_limits = rate_limits

    async def _unique_slug(self, *, organization_id: uuid.UUID, desired: str) -> str:
        base = slugify(desired)
        slug = base
        suffix = 2
        while (
            await self.apis.get_by_slug_in_org(slug=slug, organization_id=organization_id)
            is not None
        ):
            slug = f"{base}-{suffix}"
            suffix += 1
        return slug

    async def get_api(self, *, organization_id: uuid.UUID, api_id: uuid.UUID) -> Api:
        api = await self.apis.get_in_org(api_id=api_id, organization_id=organization_id)
        if api is None:
            raise NotFoundError("API not found in this organization.")
        return api

    async def create_api(
        self,
        *,
        organization_id: uuid.UUID,
        name: str,
        slug: str | None,
        description: str,
    ) -> Api:
        if slug is not None and (
            await self.apis.get_by_slug_in_org(slug=slug, organization_id=organization_id)
        ):
            raise ConflictError("An API with this slug already exists in the organization.")
        api = Api(
            organization_id=organization_id,
            name=name,
            slug=await self._unique_slug(organization_id=organization_id, desired=slug or name),
            description=description,
        )
        await self.apis.add(api)
        logger.info("api_created", api_id=str(api.id), org_id=str(organization_id))
        return await self.get_api(organization_id=organization_id, api_id=api.id)

    async def list_apis(
        self, *, organization_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[Api], int]:
        return await self.apis.list_in_org(
            organization_id=organization_id, limit=limit, offset=offset
        )

    async def update_api(
        self,
        *,
        organization_id: uuid.UUID,
        api_id: uuid.UUID,
        name: str | None,
        description: str | None,
        is_active: bool | None,
    ) -> Api:
        api = await self.get_api(organization_id=organization_id, api_id=api_id)
        if name is not None:
            api.name = name
        if description is not None:
            api.description = description
        if is_active is not None:
            api.is_active = is_active
        return api

    async def delete_api(self, *, organization_id: uuid.UUID, api_id: uuid.UUID) -> None:
        api = await self.get_api(organization_id=organization_id, api_id=api_id)
        await self.apis.delete(api)

    # ---- Versions ----
    async def add_version(
        self,
        *,
        organization_id: uuid.UUID,
        api_id: uuid.UUID,
        version: str,
        upstream_base_url: str,
        is_active: bool,
    ) -> ApiVersion:
        await self.get_api(organization_id=organization_id, api_id=api_id)
        if await self.versions.get_active(api_id=api_id, version=version):
            raise ConflictError(f"Version '{version}' already exists for this API.")
        api_version = ApiVersion(
            api_id=api_id,
            version=version,
            upstream_base_url=upstream_base_url,
            is_active=is_active,
        )
        await self.versions.add(api_version)
        logger.info("api_version_created", api_id=str(api_id), version=version)
        return api_version

    async def delete_version(
        self, *, organization_id: uuid.UUID, api_id: uuid.UUID, version_id: uuid.UUID
    ) -> None:
        await self.get_api(organization_id=organization_id, api_id=api_id)
        version = await self.versions.get(version_id)
        if version is None or version.api_id != api_id:
            raise NotFoundError("Version not found for this API.")
        await self.versions.delete(version)

    # ---- Quotas ----
    async def set_quotas(
        self,
        *,
        organization_id: uuid.UUID,
        api_id: uuid.UUID,
        quotas: list[tuple[QuotaPeriod, int]],
    ) -> list[Quota]:
        await self.get_api(organization_id=organization_id, api_id=api_id)
        # Replace the full quota set.
        for existing in await self.quotas.list_for_api(api_id):
            await self.quotas.delete(existing)
        created: list[Quota] = []
        for period, max_requests in quotas:
            q = Quota(api_id=api_id, period=period, max_requests=max_requests)
            await self.quotas.add(q)
            created.append(q)
        return created

    async def get_quotas(self, *, organization_id: uuid.UUID, api_id: uuid.UUID) -> list[Quota]:
        await self.get_api(organization_id=organization_id, api_id=api_id)
        return await self.quotas.list_for_api(api_id)

    # ---- Rate limit ----
    async def set_rate_limit(
        self,
        *,
        organization_id: uuid.UUID,
        api_id: uuid.UUID,
        algorithm: RateLimitAlgorithm,
        requests: int,
        window_seconds: int,
        burst: int | None,
    ) -> RateLimitRule:
        await self.get_api(organization_id=organization_id, api_id=api_id)
        rule = await self.rate_limits.get_for_api(api_id)
        if rule is None:
            # Construct fully before persisting (all columns are NOT NULL).
            rule = RateLimitRule(
                api_id=api_id,
                algorithm=algorithm,
                requests=requests,
                window_seconds=window_seconds,
                burst=burst,
            )
            self.rate_limits.session.add(rule)
        else:
            rule.algorithm = algorithm
            rule.requests = requests
            rule.window_seconds = window_seconds
            rule.burst = burst
        await self.rate_limits.session.flush()
        return rule

    async def get_rate_limit(
        self, *, organization_id: uuid.UUID, api_id: uuid.UUID
    ) -> RateLimitRule | None:
        await self.get_api(organization_id=organization_id, api_id=api_id)
        return await self.rate_limits.get_for_api(api_id)
