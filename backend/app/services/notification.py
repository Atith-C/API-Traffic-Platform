"""Notification service.

A thin façade for creating and reading in-app notifications. Other services call :meth:`create` to
notify a user of an event (e.g. being added to an organization).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.notification import Notification
from app.repositories.notification import NotificationRepository


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = NotificationRepository(session)

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        type: str,
        title: str,
        body: str = "",
        organization_id: uuid.UUID | None = None,
    ) -> Notification:
        notification = Notification(
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            organization_id=organization_id,
        )
        return await self.repo.add(notification)

    async def list(
        self, *, user_id: uuid.UUID, unread_only: bool, limit: int, offset: int
    ) -> list[Notification]:
        return await self.repo.list_for_user(
            user_id=user_id, unread_only=unread_only, limit=limit, offset=offset
        )

    async def mark_read(self, *, user_id: uuid.UUID, notification_id: uuid.UUID) -> Notification:
        notification = await self.repo.get_for_user(
            notification_id=notification_id, user_id=user_id
        )
        if notification is None:
            raise NotFoundError("Notification not found.")
        if notification.read_at is None:
            notification.read_at = datetime.now(UTC)
        await self.session.flush()
        return notification

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        return await self.repo.mark_all_read(user_id)
