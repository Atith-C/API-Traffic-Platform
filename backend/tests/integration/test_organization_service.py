"""Integration tests for organization/membership logic + RBAC seed consistency."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.core.permissions import ROLE_PERMISSIONS, RoleName
from app.models.organization import Role
from app.models.user import User
from app.repositories.organization import (
    MembershipRepository,
    OrganizationRepository,
    RoleRepository,
)
from app.repositories.user import UserRepository
from app.services.organization import OrganizationService
from tests.conftest import requires_docker

pytestmark = [requires_docker, pytest.mark.integration]


def _service(session: AsyncSession) -> OrganizationService:
    return OrganizationService(
        organizations=OrganizationRepository(session),
        members=MembershipRepository(session),
        roles=RoleRepository(session),
        users=UserRepository(session),
    )


async def _user(session: AsyncSession, email: str) -> User:
    user = User(email=email, password_hash="x", is_active=True)
    session.add(user)
    await session.flush()
    return user


async def test_seed_matches_catalog(db_session: AsyncSession) -> None:
    """The DB role->permission assignment must equal the in-code catalog exactly."""
    roles = (await db_session.execute(select(Role))).scalars().all()
    by_name = {r.name: {p.code for p in r.permissions} for r in roles}
    for role_name, perms in ROLE_PERMISSIONS.items():
        assert by_name[str(role_name)] == {str(p) for p in perms}


async def test_create_organization_makes_owner(db_session: AsyncSession) -> None:
    service = _service(db_session)
    owner = await _user(db_session, "owner@e.com")
    org = await service.create_organization(owner=owner, name="Acme Inc", slug=None)
    assert org.slug == "acme-inc"

    members = await service.list_members(org.id)
    assert len(members) == 1
    assert members[0].role.name == RoleName.OWNER
    assert members[0].user_id == owner.id


async def test_slug_uniqueness_autoincrements(db_session: AsyncSession) -> None:
    service = _service(db_session)
    owner = await _user(db_session, "o2@e.com")
    a = await service.create_organization(owner=owner, name="Dup", slug=None)
    b = await service.create_organization(owner=owner, name="Dup", slug=None)
    assert a.slug == "dup"
    assert b.slug == "dup-2"


async def test_explicit_duplicate_slug_conflicts(db_session: AsyncSession) -> None:
    service = _service(db_session)
    owner = await _user(db_session, "o3@e.com")
    await service.create_organization(owner=owner, name="X", slug="taken")
    with pytest.raises(ConflictError):
        await service.create_organization(owner=owner, name="Y", slug="taken")


async def test_add_member_requires_registered_user(db_session: AsyncSession) -> None:
    service = _service(db_session)
    owner = await _user(db_session, "o4@e.com")
    org = await service.create_organization(owner=owner, name="Org", slug=None)
    with pytest.raises(NotFoundError):
        await service.add_member(org_id=org.id, email="ghost@e.com", role=RoleName.DEVELOPER)


async def test_add_duplicate_member_conflicts(db_session: AsyncSession) -> None:
    service = _service(db_session)
    owner = await _user(db_session, "o5@e.com")
    dev = await _user(db_session, "dev@e.com")
    org = await service.create_organization(owner=owner, name="Org", slug=None)
    await service.add_member(org_id=org.id, email=dev.email, role=RoleName.DEVELOPER)
    with pytest.raises(ConflictError):
        await service.add_member(org_id=org.id, email=dev.email, role=RoleName.VIEWER)


async def test_cannot_remove_or_demote_last_owner(db_session: AsyncSession) -> None:
    service = _service(db_session)
    owner = await _user(db_session, "o6@e.com")
    org = await service.create_organization(owner=owner, name="Org", slug=None)
    members = await service.list_members(org.id)
    owner_member_id = members[0].id

    with pytest.raises(ValidationAppError):
        await service.update_member_role(
            org_id=org.id, member_id=owner_member_id, role=RoleName.ADMIN
        )
    with pytest.raises(ValidationAppError):
        await service.remove_member(org_id=org.id, member_id=owner_member_id)


async def test_second_owner_allows_demotion(db_session: AsyncSession) -> None:
    service = _service(db_session)
    owner = await _user(db_session, "o7@e.com")
    other = await _user(db_session, "other@e.com")
    org = await service.create_organization(owner=owner, name="Org", slug=None)
    await service.add_member(org_id=org.id, email=other.email, role=RoleName.OWNER)
    # Now demoting the original owner is allowed (a second owner remains).
    members = await service.list_members(org.id)
    original = next(m for m in members if m.user_id == owner.id)
    updated = await service.update_member_role(
        org_id=org.id, member_id=original.id, role=RoleName.ADMIN
    )
    admin_role = await RoleRepository(db_session).get_by_name(str(RoleName.ADMIN))
    assert admin_role is not None
    assert updated.role_id == admin_role.id
