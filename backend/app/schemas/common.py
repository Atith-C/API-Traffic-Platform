"""Common API schema shapes reused across routers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthComponent(BaseModel):
    status: str = Field(description="'ok' or 'error'")
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str = Field(description="Overall health: 'ok' or 'degraded'")
    version: str
    components: dict[str, HealthComponent]


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class ErrorResponse(BaseModel):
    """Standard error envelope returned for every non-2xx response."""

    error: ErrorDetail


class Page[T](BaseModel):
    """Generic pagination envelope."""

    items: list[T]
    total: int
    limit: int
    offset: int
