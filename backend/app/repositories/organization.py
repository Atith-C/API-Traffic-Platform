"""Repositories for organizations, memberships, and roles."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.organization import Organization, OrganizationMember, Role
from app.repositories.base import BaseRepository


class OrganizationRepository(BaseRepository[Organization]):
    model = Organization

    async def get_by_slug(self, slug: str) -> Organization | None:
        result = await self.session.execute(select(Organization).where(Organization.slug == slug))
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[Organization], int]:
        base = (
            select(Organization)
            .join(OrganizationMember)
            .where(OrganizationMember.user_id == user_id)
        )
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        result = await self.session.execute(
            base.order_by(Organization.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)


class RoleRepository(BaseRepository[Role]):
    model = Role

    async def get_by_name(self, name: str) -> Role | None:
        result = await self.session.execute(select(Role).where(Role.name == name))
        return result.scalar_one_or_none()


class MembershipRepository(BaseRepository[OrganizationMember]):
    model = OrganizationMember

    async def get(self, id_: uuid.UUID) -> OrganizationMember | None:
        return await self.session.get(OrganizationMember, id_)

    async def get_for_user_and_org(
        self, *, user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> OrganizationMember | None:
        result = await self.session.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == user_id,
                OrganizationMember.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_org(self, organization_id: uuid.UUID) -> list[OrganizationMember]:
        result = await self.session.execute(
            select(OrganizationMember)
            .where(OrganizationMember.organization_id == organization_id)
            .options(selectinload(OrganizationMember.role))
            .order_by(OrganizationMember.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_org_roles_for_user(
        self, user_id: uuid.UUID
    ) -> list[tuple[uuid.UUID, str]]:
        """(organization_id, role_name) for every org the user belongs to.

        Used to embed an ``orgs`` claim in the access token so downstream products (Project B) can
        authorize the user against an organization without a shared database.
        """
        result = await self.session.execute(
            select(OrganizationMember)
            .where(OrganizationMember.user_id == user_id)
            .options(selectinload(OrganizationMember.role))
        )
        return [(m.organization_id, m.role.name) for m in result.scalars().all()]

    async def count_with_role(self, *, organization_id: uuid.UUID, role_id: uuid.UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(OrganizationMember)
                .where(
                    OrganizationMember.organization_id == organization_id,
                    OrganizationMember.role_id == role_id,
                )
            )
            or 0
        )
