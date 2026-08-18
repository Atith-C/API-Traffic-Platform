"""Idempotent seeding of the RBAC catalog (permissions, roles, role_permissions).

Run on startup and in tests. Uses the in-code catalog from :mod:`app.core.permissions` as the source
of truth, so the database always reflects the current definitions.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import (
    ALL_PERMISSIONS,
    ROLE_DESCRIPTIONS,
    ROLE_PERMISSIONS,
    RoleName,
)
from app.models.organization import Permission, Role

logger = structlog.get_logger(__name__)


async def seed_rbac(session: AsyncSession) -> None:
    """Ensure every permission and built-in role exists and has the right permission set."""
    # Permissions
    existing_perms = {
        p.code: p for p in (await session.execute(select(Permission))).scalars().all()
    }
    for code in sorted(ALL_PERMISSIONS):
        if code not in existing_perms:
            perm = Permission(code=str(code), description=str(code))
            session.add(perm)
            existing_perms[code] = perm
    await session.flush()

    # Roles + their permission assignments
    existing_roles = {r.name: r for r in (await session.execute(select(Role))).scalars().all()}
    for role_name in RoleName:
        role = existing_roles.get(role_name)
        if role is None:
            role = Role(
                name=str(role_name),
                description=ROLE_DESCRIPTIONS[role_name],
                is_system=True,
            )
            session.add(role)
            await session.flush()
        # Reconcile the permission set to match the catalog exactly. Load the current collection
        # via awaitable_attrs first so the reassignment doesn't trigger a lazy load in sync context.
        await role.awaitable_attrs.permissions
        desired = {str(p) for p in ROLE_PERMISSIONS[role_name]}
        role.permissions = [existing_perms[c] for c in desired]

    await session.flush()
    logger.info("rbac_seeded", roles=len(RoleName), permissions=len(ALL_PERMISSIONS))
