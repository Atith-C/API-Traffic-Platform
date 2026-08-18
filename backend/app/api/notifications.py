"""Notification endpoints (scoped to the current user)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from app.api.deps import CurrentUser, SessionDep
from app.schemas.auth import MessageResponse
from app.services.notification import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    title: str
    body: str
    organization_id: uuid.UUID | None
    read_at: datetime | None
    created_at: datetime


@router.get("", response_model=list[NotificationResponse])
async def list_notifications(
    current_user: CurrentUser,
    session: SessionDep,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[NotificationResponse]:
    items = await NotificationService(session).list(
        user_id=current_user.id, unread_only=unread_only, limit=limit, offset=offset
    )
    return [NotificationResponse.model_validate(n) for n in items]


@router.post("/{notification_id}/read", response_model=NotificationResponse)
async def mark_read(
    notification_id: uuid.UUID, current_user: CurrentUser, session: SessionDep
) -> NotificationResponse:
    n = await NotificationService(session).mark_read(
        user_id=current_user.id, notification_id=notification_id
    )
    return NotificationResponse.model_validate(n)


@router.post("/read-all", response_model=MessageResponse)
async def mark_all_read(current_user: CurrentUser, session: SessionDep) -> MessageResponse:
    count = await NotificationService(session).mark_all_read(current_user.id)
    return MessageResponse(message=f"Marked {count} notification(s) as read.")
