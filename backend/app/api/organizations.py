"""Organization & membership endpoints.

Authorization is enforced by the ``require_permission`` dependency per route. Creating and listing
organizations only require authentication (any user can start an org and sees only their own).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUser, OrgServiceDep, SessionDep, require_permission
from app.core.permissions import Permission
from app.models.organization import OrganizationMember
from app.schemas.common import Page
from app.schemas.organization import (
    AddMemberRequest,
    MemberResponse,
    OrganizationCreate,
    OrganizationResponse,
    OrganizationUpdate,
    UpdateMemberRoleRequest,
)
from app.services.notification import NotificationService

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _member_response(member: OrganizationMember) -> MemberResponse:
    return MemberResponse(
        id=member.id,
        user_id=member.user_id,
        email=member.user.email,
        full_name=member.user.full_name,
        role=member.role.name,
        created_at=member.created_at,
    )


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: OrganizationCreate, current_user: CurrentUser, service: OrgServiceDep
) -> OrganizationResponse:
    org = await service.create_organization(
        owner=current_user, name=payload.name, slug=payload.slug
    )
    return OrganizationResponse.model_validate(org)


@router.get("", response_model=Page[OrganizationResponse])
async def list_organizations(
    current_user: CurrentUser,
    service: OrgServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[OrganizationResponse]:
    orgs, total = await service.list_for_user(user_id=current_user.id, limit=limit, offset=offset)
    return Page(
        items=[OrganizationResponse.model_validate(o) for o in orgs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: uuid.UUID,
    service: OrgServiceDep,
    _: Annotated[OrganizationMember, Depends(require_permission(Permission.ORG_READ))],
) -> OrganizationResponse:
    org = await service.get_organization(org_id)
    return OrganizationResponse.model_validate(org)


@router.patch("/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: uuid.UUID,
    payload: OrganizationUpdate,
    service: OrgServiceDep,
    _: Annotated[OrganizationMember, Depends(require_permission(Permission.ORG_UPDATE))],
) -> OrganizationResponse:
    org = await service.update_organization(org_id, name=payload.name)
    return OrganizationResponse.model_validate(org)


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    org_id: uuid.UUID,
    service: OrgServiceDep,
    _: Annotated[OrganizationMember, Depends(require_permission(Permission.ORG_DELETE))],
) -> None:
    await service.delete_organization(org_id)


@router.get("/{org_id}/members", response_model=list[MemberResponse])
async def list_members(
    org_id: uuid.UUID,
    service: OrgServiceDep,
    _: Annotated[OrganizationMember, Depends(require_permission(Permission.MEMBER_READ))],
) -> list[MemberResponse]:
    members = await service.list_members(org_id)
    return [_member_response(m) for m in members]


@router.post(
    "/{org_id}/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED
)
async def add_member(
    org_id: uuid.UUID,
    payload: AddMemberRequest,
    service: OrgServiceDep,
    session: SessionDep,
    _: Annotated[OrganizationMember, Depends(require_permission(Permission.MEMBER_INVITE))],
) -> MemberResponse:
    member = await service.add_member(org_id=org_id, email=payload.email, role=payload.role)
    # Notify the newly added member.
    await NotificationService(session).create(
        user_id=member.user_id,
        type="member.added",
        title="You were added to an organization",
        body=f"You now have the '{member.role.name}' role.",
        organization_id=org_id,
    )
    return _member_response(member)


@router.patch("/{org_id}/members/{member_id}", response_model=MemberResponse)
async def update_member_role(
    org_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: UpdateMemberRoleRequest,
    service: OrgServiceDep,
    _: Annotated[OrganizationMember, Depends(require_permission(Permission.MEMBER_UPDATE_ROLE))],
) -> MemberResponse:
    member = await service.update_member_role(org_id=org_id, member_id=member_id, role=payload.role)
    return _member_response(member)


@router.delete("/{org_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    org_id: uuid.UUID,
    member_id: uuid.UUID,
    service: OrgServiceDep,
    _: Annotated[OrganizationMember, Depends(require_permission(Permission.MEMBER_REMOVE))],
) -> None:
    await service.remove_member(org_id=org_id, member_id=member_id)
