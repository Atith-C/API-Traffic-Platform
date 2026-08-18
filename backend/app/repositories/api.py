"""Repositories for the API catalog (apis, versions, quotas, rate-limit rules)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.api import Api, ApiVersion, Quota, RateLimitRule
from app.repositories.base import BaseRepository


class ApiRepository(BaseRepository[Api]):
    model = Api

    async def get_in_org(self, *, api_id: uuid.UUID, organization_id: uuid.UUID) -> Api | None:
        result = await self.session.execute(
            select(Api)
            .where(Api.id == api_id, Api.organization_id == organization_id)
            .options(
                selectinload(Api.versions),
                selectinload(Api.quotas),
                selectinload(Api.rate_limit_rule),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_slug_in_org(self, *, slug: str, organization_id: uuid.UUID) -> Api | None:
        result = await self.session.execute(
            select(Api).where(Api.slug == slug, Api.organization_id == organization_id)
        )
        return result.scalar_one_or_none()

    async def list_in_org(
        self, *, organization_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[Api], int]:
        base = select(Api).where(Api.organization_id == organization_id)
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        result = await self.session.execute(
            base.order_by(Api.created_at.desc())
            .options(selectinload(Api.versions))
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)


class ApiVersionRepository(BaseRepository[ApiVersion]):
    model = ApiVersion

    async def get_active(self, *, api_id: uuid.UUID, version: str) -> ApiVersion | None:
        result = await self.session.execute(
            select(ApiVersion).where(ApiVersion.api_id == api_id, ApiVersion.version == version)
        )
        return result.scalar_one_or_none()


class QuotaRepository(BaseRepository[Quota]):
    model = Quota

    async def list_for_api(self, api_id: uuid.UUID) -> list[Quota]:
        result = await self.session.execute(select(Quota).where(Quota.api_id == api_id))
        return list(result.scalars().all())


class RateLimitRuleRepository(BaseRepository[RateLimitRule]):
    model = RateLimitRule

    async def get_for_api(self, api_id: uuid.UUID) -> RateLimitRule | None:
        result = await self.session.execute(
            select(RateLimitRule).where(RateLimitRule.api_id == api_id)
        )
        return result.scalar_one_or_none()
