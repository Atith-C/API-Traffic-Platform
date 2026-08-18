"""API key repository."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.api_key import ApiKey
from app.repositories.base import BaseRepository


class ApiKeyRepository(BaseRepository[ApiKey]):
    model = ApiKey

    async def get_by_hash(self, key_hash: str) -> ApiKey | None:
        """Gateway lookup: resolve a presented key to its record (with the owning API loaded)."""
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash).options(selectinload(ApiKey.api))
        )
        return result.scalar_one_or_none()

    async def get_in_api(self, *, key_id: uuid.UUID, api_id: uuid.UUID) -> ApiKey | None:
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.api_id == api_id)
        )
        return result.scalar_one_or_none()

    async def list_for_api(self, api_id: uuid.UUID) -> list[ApiKey]:
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.api_id == api_id).order_by(ApiKey.created_at.desc())
        )
        return list(result.scalars().all())
