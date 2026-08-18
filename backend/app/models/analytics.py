"""Analytics rollup model.

``daily_usage`` is a pre-aggregated per-(organization, api, day) rollup of ``request_logs``, so
time-series dashboards over long ranges don't scan the raw log table. It is rebuilt idempotently by
a scheduled worker (and can be recomputed for any day on demand).
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, Float, Index, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DailyUsage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "daily_usage"
    __table_args__ = (
        UniqueConstraint("api_id", "usage_date", name="uq_daily_usage_api_date"),
        Index("ix_daily_usage_org_date", "organization_id", "usage_date"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    api_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_request_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_response_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
