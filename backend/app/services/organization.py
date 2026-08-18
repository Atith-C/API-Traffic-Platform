"""Organization & membership business logic.

Enforces the invariants that keep an org usable: unique slugs, and never leaving an organization
without an owner (can't demote/remove the last owner).
"""

from __future__ import annotations

import re
import uuid

import structlog

from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.core.permissions import RoleName
from app.models.organization import Organization, OrganizationMember
from app.models.user import User
from app.repositories.organization import (
    MembershipRepository,
    OrganizationRepository,
    RoleRepository,
)
from app.repositories.user import UserRepository

logger = structlog.get_logger(__name__)

_slug_strip = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    slug = _slug_strip.sub("-", value.lower()).strip("-")
    return slug or "org"


class OrganizationService:
    def __init__(
        self,
        *,
        organizations: OrganizationRepository,
        members: MembershipRepository,
        roles: RoleRepository,
        users: UserRepository,
    ) -> None:
        self.organizations = organizations
        self.members = members
        self.roles = roles
        self.users = users

    async def _role_id(self, role_name: RoleName) -> uuid.UUID:
        role = await self.roles.get_by_name(str(role_name))
        if role is None:  # pragma: no cover - seeding guarantees presence
            raise NotFoundError(f"Role '{role_name}' is not configured.")
        return role.id

    async def _unique_slug(self, desired: str) -> str:
        base = slugify(desired)
        slug = base
        suffix = 2
        while await self.organizations.get_by_slug(slug) is not None:
            slug = f"{base}-{suffix}"
            suffix += 1
        return slug

    async def create_organization(
        self, *, owner: User, name: str, slug: str | None
    ) -> Organization:
        if slug is not None and await self.organizations.get_by_slug(slug) is not None:
            raise ConflictError("An organization with this slug already exists.")
        org = Organization(name=name, slug=await self._unique_slug(slug or name))
        await self.organizations.add(org)
        await self.members.add(
            OrganizationMember(
                organization_id=org.id,
                user_id=owner.id,
                role_id=await self._role_id(RoleName.OWNER),
            )
        )
        logger.info("organization_created", org_id=str(org.id), owner_id=str(owner.id))
        return org

    async def list_for_user(
        self, *, user_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[Organization], int]:
        return await self.organizations.list_for_user(user_id, limit=limit, offset=offset)

    async def get_organization(self, org_id: uuid.UUID) -> Organization:
        org = await self.organizations.get(org_id)
        if org is None:
            raise NotFoundError("Organization not found.")
        return org

    async def update_organization(self, org_id: uuid.UUID, *, name: str) -> Organization:
        org = await self.get_organization(org_id)
        org.name = name
        return org

    async def delete_organization(self, org_id: uuid.UUID) -> None:
        org = await self.get_organization(org_id)
        await self.organizations.delete(org)

    # ---- Membership ----
    async def add_member(
        self, *, org_id: uuid.UUID, email: str, role: RoleName
    ) -> OrganizationMember:
        user = await self.users.get_by_email(email.lower())
        if user is None:
            raise NotFoundError("No registered user with that email.")
        existing = await self.members.get_for_user_and_org(user_id=user.id, organization_id=org_id)
        if existing is not None:
            raise ConflictError("User is already a member of this organization.")
        member = OrganizationMember(
            organization_id=org_id,
            user_id=user.id,
            role_id=await self._role_id(role),
        )
        await self.members.add(member)
        await self._hydrate(member)
        logger.info("member_added", org_id=str(org_id), user_id=str(user.id), role=str(role))
        return member

    async def _hydrate(self, member: OrganizationMember) -> None:
        """Eager-load ``user`` and ``role`` so sync response serialization needs no lazy IO."""
        await self.members.session.refresh(member, attribute_names=["user", "role"])

    async def list_members(self, org_id: uuid.UUID) -> list[OrganizationMember]:
        return await self.members.list_for_org(org_id)

    async def _get_member(self, *, org_id: uuid.UUID, member_id: uuid.UUID) -> OrganizationMember:
        member = await self.members.get(member_id)
        if member is None or member.organization_id != org_id:
            raise NotFoundError("Member not found in this organization.")
        return member

    async def update_member_role(
        self, *, org_id: uuid.UUID, member_id: uuid.UUID, role: RoleName
    ) -> OrganizationMember:
        member = await self._get_member(org_id=org_id, member_id=member_id)
        owner_role_id = await self._role_id(RoleName.OWNER)
        # Prevent demoting the last owner.
        if member.role_id == owner_role_id and role != RoleName.OWNER:
            owners = await self.members.count_with_role(
                organization_id=org_id, role_id=owner_role_id
            )
            if owners <= 1:
                raise ValidationAppError("Cannot demote the last owner of the organization.")
        member.role_id = await self._role_id(role)
        await self.members.session.flush()
        await self._hydrate(member)
        return member

    async def remove_member(self, *, org_id: uuid.UUID, member_id: uuid.UUID) -> None:
        member = await self._get_member(org_id=org_id, member_id=member_id)
        owner_role_id = await self._role_id(RoleName.OWNER)
        if member.role_id == owner_role_id:
            owners = await self.members.count_with_role(
                organization_id=org_id, role_id=owner_role_id
            )
            if owners <= 1:
                raise ValidationAppError("Cannot remove the last owner of the organization.")
        await self.members.delete(member)
