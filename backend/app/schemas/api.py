"""API-catalog schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator

from app.models.api import QuotaPeriod, RateLimitAlgorithm


class ApiVersionCreate(BaseModel):
    version: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")
    upstream_base_url: AnyHttpUrl
    is_active: bool = True


class ApiVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: str
    upstream_base_url: str
    is_active: bool
    created_at: datetime


class ApiCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str = Field(default="", max_length=1000)


class ApiUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None


class ApiResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    slug: str
    description: str
    is_active: bool
    created_at: datetime
    versions: list[ApiVersionResponse] = []


class QuotaItem(BaseModel):
    period: QuotaPeriod
    max_requests: int = Field(gt=0)


class QuotaConfig(BaseModel):
    """Full desired quota set for an API (replaces existing)."""

    quotas: list[QuotaItem] = Field(default_factory=list)

    @field_validator("quotas")
    @classmethod
    def _unique_periods(cls, value: list[QuotaItem]) -> list[QuotaItem]:
        periods = [q.period for q in value]
        if len(periods) != len(set(periods)):
            raise ValueError("Duplicate quota periods are not allowed.")
        return value


class RateLimitConfig(BaseModel):
    algorithm: RateLimitAlgorithm
    requests: int = Field(gt=0, description="Requests permitted per window.")
    window_seconds: int = Field(gt=0, le=86_400)
    burst: int | None = Field(default=None, gt=0, description="Token-bucket burst capacity.")

    @field_validator("burst")
    @classmethod
    def _burst_only_for_token_bucket(cls, value: int | None, info) -> int | None:
        algo = info.data.get("algorithm")
        if value is not None and algo != RateLimitAlgorithm.TOKEN_BUCKET:
            raise ValueError("burst is only valid for the token_bucket algorithm.")
        return value


class RateLimitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    algorithm: RateLimitAlgorithm
    requests: int
    window_seconds: int
    burst: int | None
