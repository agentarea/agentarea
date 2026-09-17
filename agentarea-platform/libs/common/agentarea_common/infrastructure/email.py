"""SMTP transport for the platform's own transactional email.

Distinct from the trigger channel adapters on purpose: those deliver a user's
configured channel and resolve per-trigger credentials from the secret store,
so they cannot send mail that has no trigger behind it. This mailer carries
platform mail — a workspace invitation today — on deployment-level settings.

It only sends. What a failure means is the caller's decision.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage
from typing import Any

import aiosmtplib

from ..config.email import EmailSettings, get_email_settings

logger = logging.getLogger(__name__)

SendFn = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text_body: str
    html_body: str | None


class SmtpMailer:
    def __init__(self, settings: EmailSettings, send_fn: SendFn | None = None) -> None:
        self._settings = settings
        self._send = send_fn or aiosmtplib.send

    async def send(self, message: EmailMessage) -> None:
        """Deliver one message. Raises whatever the transport raises."""
        connection = self._settings.connection()
        if connection is None:
            raise RuntimeError("SMTP is not configured")

        await self._send(
            self._to_mime(message),
            hostname=connection.host,
            port=connection.port,
            username=connection.username,
            password=connection.password,
            use_tls=connection.use_tls,
            start_tls=connection.start_tls,
            validate_certs=connection.validate_certs,
        )

    def _to_mime(self, message: EmailMessage) -> MimeMessage:
        mime = MimeMessage()
        mime["From"] = self._settings.from_header
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.text_body)
        if message.html_body is not None:
            mime.add_alternative(message.html_body, subtype="html")
        return mime


def build_mailer(settings: EmailSettings) -> SmtpMailer | None:
    """A mailer, or None when this deployment has no transactional mail."""
    if not settings.is_configured:
        return None
    return SmtpMailer(settings)


def get_mailer() -> SmtpMailer | None:
    return build_mailer(get_email_settings())
