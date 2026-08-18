"""Unit tests for the RBAC catalog and slug helper."""

from __future__ import annotations

from app.core.permissions import (
    ROLE_PERMISSIONS,
    Permission,
    RoleName,
    role_has_permission,
)
from app.services.organization import slugify


def test_every_role_defined() -> None:
    assert set(ROLE_PERMISSIONS) == set(RoleName)


def test_owner_has_all_permissions() -> None:
    assert ROLE_PERMISSIONS[RoleName.OWNER] == frozenset(Permission)


def test_admin_cannot_delete_org() -> None:
    assert not role_has_permission(RoleName.ADMIN, Permission.ORG_DELETE)
    assert role_has_permission(RoleName.ADMIN, Permission.MEMBER_INVITE)


def test_viewer_is_read_only() -> None:
    for perm in ROLE_PERMISSIONS[RoleName.VIEWER]:
        assert perm.value.endswith(":read")
    assert not role_has_permission(RoleName.VIEWER, Permission.API_CREATE)


def test_developer_can_manage_apis_not_members() -> None:
    assert role_has_permission(RoleName.DEVELOPER, Permission.API_CREATE)
    assert role_has_permission(RoleName.DEVELOPER, Permission.KEY_CREATE)
    assert not role_has_permission(RoleName.DEVELOPER, Permission.MEMBER_INVITE)


def test_slugify() -> None:
    assert slugify("My Cool Org!") == "my-cool-org"
    assert slugify("  spaces  ") == "spaces"
    assert slugify("!!!") == "org"
