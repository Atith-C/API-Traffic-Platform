"""Analytics response schemas."""

from __future__ import annotations

from pydantic import BaseModel


class SummaryResponse(BaseModel):
    request_count: int
    error_count: int
    error_rate: float
    avg_latency_ms: float
    p95_latency_ms: float
    active_keys: int
    window_days: int


class EndpointStat(BaseModel):
    path: str
    request_count: int
    avg_latency_ms: float


class TimeseriesPoint(BaseModel):
    date: str
    request_count: int
    error_count: int
    avg_latency_ms: float


class KeyStat(BaseModel):
    api_key_id: str
    request_count: int
    error_count: int
