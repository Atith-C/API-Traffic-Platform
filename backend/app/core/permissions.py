"""RBAC permission catalog and default role definitions.

This module is the single source of truth for permissions and the built-in roles. The catalog is
seeded into the database (``permissions`` / ``roles`` / ``role_permissions``) for auditability,
while authorization checks use the in-memory mapping for speed. A test asserts the two never drift.
"""

from __future__ import annotations

from enum import StrEnum


class Permission(StrEnum):
    # Organization
    ORG_READ = "org:read"
    ORG_UPDATE = "org:update"
    ORG_DELETE = "org:delete"
    # Membership
    MEMBER_READ = "member:read"
    MEMBER_INVITE = "member:invite"
    MEMBER_UPDATE_ROLE = "member:update_role"
    MEMBER_REMOVE = "member:remove"
    # APIs
    API_CREATE = "api:create"
    API_READ = "api:read"
    API_UPDATE = "api:update"
    API_DELETE = "api:delete"
    # API keys
    KEY_CREATE = "key:create"
    KEY_READ = "key:read"
    KEY_REVOKE = "key:revoke"
    KEY_ROTATE = "key:rotate"
    # Analytics & audit
    ANALYTICS_READ = "analytics:read"
    AUDIT_READ = "audit:read"


class RoleName(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"


ALL_PERMISSIONS: frozenset[Permission] = frozenset(Permission)

_READ_ONLY: frozenset[Permission] = frozenset(
    {
        Permission.ORG_READ,
        Permission.MEMBER_READ,
        Permission.API_READ,
        Permission.KEY_READ,
        Permission.ANALYTICS_READ,
        Permission.AUDIT_READ,
    }
)

_DEVELOPER: frozenset[Permission] = _READ_ONLY | {
    Permission.API_CREATE,
    Permission.API_UPDATE,
    Permission.API_DELETE,
    Permission.KEY_CREATE,
    Permission.KEY_REVOKE,
    Permission.KEY_ROTATE,
}

ROLE_PERMISSIONS: dict[RoleName, frozenset[Permission]] = {
    RoleName.OWNER: ALL_PERMISSIONS,
    RoleName.ADMIN: ALL_PERMISSIONS - {Permission.ORG_DELETE},
    RoleName.DEVELOPER: frozenset(_DEVELOPER),
    RoleName.VIEWER: _READ_ONLY,
}

ROLE_DESCRIPTIONS: dict[RoleName, str] = {
    RoleName.OWNER: "Full control, including deleting the organization.",
    RoleName.ADMIN: "Manage members, APIs, and keys; cannot delete the organization.",
    RoleName.DEVELOPER: "Create and manage APIs and keys; read analytics.",
    RoleName.VIEWER: "Read-only access.",
}


def role_has_permission(role: RoleName, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]
