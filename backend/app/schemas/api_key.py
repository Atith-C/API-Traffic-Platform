"""API key schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreate(BaseModel):
    name: str = Field(default="", max_length=200)
    expires_in_days: int | None = Field(
        default=None, gt=0, le=3650, description="Optional expiry; omit for a non-expiring key."
    )


class ApiKeyResponse(BaseModel):
    """Metadata about a key (never includes the secret)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    api_id: uuid.UUID
    name: str
    prefix: str
    last_four: str
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyCreatedResponse(ApiKeyResponse):
    """Returned once on create/rotate with the full secret. Store it now; it won't reappear."""

    api_key: str = Field(description="The full API key. Shown only once.")


class ApiKeyRotateRequest(BaseModel):
    grace_period_hours: int = Field(
        default=24,
        ge=0,
        le=720,
        description="How long the old key keeps working after rotation (0 = immediate).",
    )
