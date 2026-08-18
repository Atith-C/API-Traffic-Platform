"""Telemetry & audit models: request logs, per-key usage, audit logs, and the telemetry outbox.

These tables are append-mostly and decoupled from the transactional catalog tables, so Project B can
ingest them (or the outbox stream) without touching Project A's write path. Large tables carry
composite indexes on ``(scope, created_at)`` for time-range analytics.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RequestLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One proxied gateway request. Written in the same transaction as its outbox event."""

    __tablename__ = "request_logs"
    __table_args__ = (
        Index("ix_request_logs_api_created", "api_id", "created_at"),
        Index("ix_request_logs_org_created", "organization_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    api_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    api_version_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(2048), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[float] = mapped_column(nullable=False)
    request_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    client_ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    upstream_url: Mapped[str] = mapped_column(String(2048), nullable=False, default="")


class ApiKeyUsage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-key, per-day usage aggregate — fast per-key stats without scanning request logs."""

    __tablename__ = "api_key_usage"
    __table_args__ = (
        UniqueConstraint("api_key_id", "usage_date", name="uq_api_key_usage_key_date"),
        Index("ix_api_key_usage_api_date", "api_id", "usage_date"),
    )

    api_key_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False
    )
    api_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AuditLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An administrative action, for compliance and Project B incident correlation."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_org_created", "organization_id", "created_at"),)

    organization_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audit_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class TelemetryOutbox(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Transactional outbox: events committed atomically with their business write, drained async.

    ``published_at IS NULL`` => pending. A background publisher delivers pending rows to the
    configured sink (log now; Kafka/Redis Streams later) and stamps ``published_at`` — the payload
    schema never changes when the transport does.
    """

    __tablename__ = "telemetry_outbox"
    __table_args__ = (Index("ix_telemetry_outbox_pending", "published_at", "created_at"),)

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
