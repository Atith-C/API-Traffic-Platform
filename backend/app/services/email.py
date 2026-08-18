"""Email delivery abstraction.

The domain depends only on the :class:`EmailSender` protocol, so swapping the console sender for SES
/ SendGrid / SMTP later touches one place. In development/tests the console sender just logs the
message (and records it, so tests can assert what would have been sent).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    body: str


class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


class ConsoleEmailSender:
    """Logs emails instead of sending them. Keeps a list of sent messages for assertions."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.sent.append(message)
        logger.info("email_sent", to=message.to, subject=message.subject)


_default_sender: EmailSender = ConsoleEmailSender()


def get_email_sender() -> EmailSender:
    """FastAPI dependency returning the configured email sender."""
    return _default_sender
