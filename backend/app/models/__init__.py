"""ORM models package.

Importing this package must register every model on ``Base.metadata`` so Alembic autogenerate and
test schema creation see the full schema. As milestones add models, import them here and add their
names to ``__all__``.
"""

from __future__ import annotations

from app.models.analytics import DailyUsage
from app.models.api import (
    Api,
    ApiVersion,
    Quota,
    QuotaPeriod,
    RateLimitAlgorithm,
    RateLimitRule,
)
from app.models.api_key import ApiKey
from app.models.notification import Notification
from app.models.organization import (
    Organization,
    OrganizationMember,
    Permission,
    Role,
    role_permissions,
)
from app.models.telemetry import ApiKeyUsage, AuditLog, RequestLog, TelemetryOutbox
from app.models.user import RefreshToken, User

__all__ = [
    "Api",
    "ApiKey",
    "ApiKeyUsage",
    "ApiVersion",
    "AuditLog",
    "DailyUsage",
    "Notification",
    "Organization",
    "OrganizationMember",
    "Permission",
    "Quota",
    "QuotaPeriod",
    "RateLimitAlgorithm",
    "RateLimitRule",
    "RefreshToken",
    "RequestLog",
    "Role",
    "TelemetryOutbox",
    "User",
    "role_permissions",
]
