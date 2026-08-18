"""API key business logic: issue (shown once), list, revoke, rotate (with grace window).

Ownership is enforced via the API catalog service, so a key can only be managed by someone with the
right permission in the API's organization.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog

from app.core.errors import NotFoundError, ValidationAppError
from app.core.security import GeneratedApiKey, generate_api_key
from app.models.api_key import ApiKey
from app.repositories.api_key import ApiKeyRepository
from app.services.api_catalog import ApiCatalogService

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class IssuedApiKey:
    record: ApiKey
    full_key: str


class ApiKeyService:
    def __init__(self, *, keys: ApiKeyRepository, catalog: ApiCatalogService) -> None:
        self.keys = keys
        self.catalog = catalog

    async def create_key(
        self,
        *,
        organization_id: uuid.UUID,
        api_id: uuid.UUID,
        name: str,
        expires_in_days: int | None,
        created_by_user_id: uuid.UUID | None,
    ) -> IssuedApiKey:
        # Validates the API exists in the org (raises 404 otherwise).
        await self.catalog.get_api(organization_id=organization_id, api_id=api_id)
        generated: GeneratedApiKey = generate_api_key()
        expires_at = (
            datetime.now(UTC) + timedelta(days=expires_in_days)
            if expires_in_days is not None
            else None
        )
        record = ApiKey(
            api_id=api_id,
            organization_id=organization_id,
            name=name,
            prefix=generated.prefix,
            last_four=generated.last_four,
            key_hash=generated.key_hash,
            created_by_user_id=created_by_user_id,
            expires_at=expires_at,
        )
        await self.keys.add(record)
        logger.info("api_key_created", key_id=str(record.id), api_id=str(api_id))
        return IssuedApiKey(record=record, full_key=generated.full_key)

    async def list_keys(self, *, organization_id: uuid.UUID, api_id: uuid.UUID) -> list[ApiKey]:
        await self.catalog.get_api(organization_id=organization_id, api_id=api_id)
        return await self.keys.list_for_api(api_id)

    async def _get_key(
        self, *, organization_id: uuid.UUID, api_id: uuid.UUID, key_id: uuid.UUID
    ) -> ApiKey:
        await self.catalog.get_api(organization_id=organization_id, api_id=api_id)
        key = await self.keys.get_in_api(key_id=key_id, api_id=api_id)
        if key is None:
            raise NotFoundError("API key not found for this API.")
        return key

    async def revoke_key(
        self, *, organization_id: uuid.UUID, api_id: uuid.UUID, key_id: uuid.UUID
    ) -> None:
        key = await self._get_key(organization_id=organization_id, api_id=api_id, key_id=key_id)
        if key.revoked_at is None:
            key.revoked_at = datetime.now(UTC)
        await self.keys.session.flush()

    async def rotate_key(
        self,
        *,
        organization_id: uuid.UUID,
        api_id: uuid.UUID,
        key_id: uuid.UUID,
        grace_period_hours: int,
        created_by_user_id: uuid.UUID | None,
    ) -> IssuedApiKey:
        old = await self._get_key(organization_id=organization_id, api_id=api_id, key_id=key_id)
        if old.revoked_at is not None:
            raise ValidationAppError("Cannot rotate a revoked key.")

        issued = await self.create_key(
            organization_id=organization_id,
            api_id=api_id,
            name=old.name,
            expires_in_days=None,
            created_by_user_id=created_by_user_id,
        )
        now = datetime.now(UTC)
        # Grace-window the old key: keep it valid for the grace period, then it expires.
        grace_expiry = now + timedelta(hours=grace_period_hours)
        if grace_period_hours == 0:
            old.revoked_at = now
        elif old.expires_at is None or old.expires_at > grace_expiry:
            old.expires_at = grace_expiry
        old.rotated_to = issued.record.id
        await self.keys.session.flush()
        logger.info(
            "api_key_rotated",
            old_key_id=str(old.id),
            new_key_id=str(issued.record.id),
            grace_hours=grace_period_hours,
        )
        return issued
