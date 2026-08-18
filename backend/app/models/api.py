"""API catalog models: registered APIs, their versions, quotas, and rate-limit rules."""

from __future__ import annotations

import uuid
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class QuotaPeriod(StrEnum):
    DAILY = "daily"
    MONTHLY = "monthly"


class RateLimitAlgorithm(StrEnum):
    FIXED_WINDOW = "fixed_window"
    SLIDING_WINDOW = "sliding_window"
    TOKEN_BUCKET = "token_bucket"


class Api(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A registered API owned by an organization. Traffic is routed via its versions' upstreams."""

    __tablename__ = "apis"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_apis_org_slug"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    versions: Mapped[list[ApiVersion]] = relationship(
        back_populates="api", cascade="all, delete-orphan"
    )
    quotas: Mapped[list[Quota]] = relationship(back_populates="api", cascade="all, delete-orphan")
    rate_limit_rule: Mapped[RateLimitRule | None] = relationship(
        back_populates="api", cascade="all, delete-orphan", uselist=False
    )


class ApiVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A concrete version of an API, forwarding to a configured upstream base URL."""

    __tablename__ = "api_versions"
    __table_args__ = (UniqueConstraint("api_id", "version", name="uq_api_versions_api_version"),)

    api_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("apis.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    upstream_base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    api: Mapped[Api] = relationship(back_populates="versions")


class Quota(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A per-period request cap for an API, enforced across its API keys."""

    __tablename__ = "quotas"
    __table_args__ = (UniqueConstraint("api_id", "period", name="uq_quotas_api_period"),)

    api_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("apis.id", ondelete="CASCADE"), index=True, nullable=False
    )
    period: Mapped[QuotaPeriod] = mapped_column(String(16), nullable=False)
    max_requests: Mapped[int] = mapped_column(Integer, nullable=False)

    api: Mapped[Api] = relationship(back_populates="quotas")


class RateLimitRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single rate-limit policy for an API (one per API; absent => no rate limiting)."""

    __tablename__ = "rate_limit_rules"
    __table_args__ = (UniqueConstraint("api_id", name="uq_rate_limit_rules_api"),)

    api_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("apis.id", ondelete="CASCADE"), index=True, nullable=False
    )
    algorithm: Mapped[RateLimitAlgorithm] = mapped_column(String(24), nullable=False)
    # Requests allowed per window; window length in seconds; burst for token-bucket.
    requests: Mapped[int] = mapped_column(Integer, nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    burst: Mapped[int | None] = mapped_column(Integer, nullable=True)

    api: Mapped[Api] = relationship(back_populates="rate_limit_rule")
