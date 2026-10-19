"""The ``smtp`` reply sender: a task answers the mail that started it."""

from __future__ import annotations

import logging
import socket
from collections.abc import Awaitable, Callable
from email.errors import HeaderParseError
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import getaddresses
from typing import TYPE_CHECKING, Any

import aiosmtplib
from agentarea_common.outbound import member_connection
from agentarea_common.utils.url_safety import UnsafeUrlError

from . import register_adapter
from .exceptions import FatalError, RetryableError
from .source_credentials import credentials_of

if TYPE_CHECKING:
    from .source_credentials import CredentialReader

logger = logging.getLogger(__name__)

Connect = Callable[[str, int], Awaitable[socket.socket]]


class EmailAdapter:
    """Send a task's events as HTML mail to whoever wrote the mail that started it.

    The address's target carries whom to answer (``to``: the incoming mail's
    ``Reply-To`` or ``From``), its ``subject``, ``message_id`` and ``references``; the source's credentials carry
    ``smtp_host``, ``smtp_port``, ``username``, ``password``, ``from_address``
    and ``use_tls``.
    """

    def __init__(self, credentials: CredentialReader, connect: Connect = member_connection):
        self._credentials = credentials
        # The SMTP host is the member's: the connection goes to the address it
        # was vetted at (a test seam otherwise).
        self._connect = connect

    def format(self, event: dict[str, Any], presentation: str, config: dict[str, Any]) -> str:
        """Format a workflow event as HTML for email.

        In summary mode, only result/interaction events come through.
        """
        event_type = event.get("event_type", "")
        data = event.get("data", {})

        if event_type == "task.completed":
            result = data.get("final_response") or data.get("result") or "Task completed."
            return _html_wrap(
                subject="Task Complete",
                body=f"<p>{_escape_html(str(result))}</p>",
                status="success",
            )

        if event_type == "task.failed":
            error = data.get("error", "Unknown error")
            return _html_wrap(
                subject="Task Failed",
                body=f"<p><strong>Error:</strong> {_escape_html(str(error))}</p>",
                status="error",
            )

        if event_type == "task.cancelled":
            return _html_wrap(
                subject="Task Cancelled",
                body="<p>The task was cancelled.</p>",
                status="warning",
            )

        if event_type == "approval.requested":
            question = data.get("question", "Approval needed")
            return _html_wrap(
                subject="Action Required",
                body=f"<p><strong>Your input is needed:</strong></p>"
                f"<blockquote>{_escape_html(str(question))}</blockquote>"
                f"<p>Please respond via the AgentArea dashboard.</p>",
                status="warning",
            )

        if event_type == "approval.decided":
            approved = data.get("approved")
            comment = data.get("comment")
            if approved is True:
                return _html_wrap(
                    subject="Approved",
                    body="<p>The action was approved. The agent is continuing.</p>",
                    status="success",
                )
            if approved is False:
                reason = (
                    f"<p><strong>Reason:</strong> {_escape_html(str(comment))}</p>"
                    if comment
                    else ""
                )
                return _html_wrap(
                    subject="Action Denied",
                    body=f"<p>The action was denied and did not run.</p>{reason}",
                    status="error",
                )
            return _html_wrap(
                subject="Approval Resolved",
                body="<p>The approval request was resolved.</p>",
                status="info",
            )

        # Fallback
        return _html_wrap(
            subject=f"Agent Update: {event_type}",
            body=f"<p>{_escape_html(event_type)}</p>",
            status="info",
        )

    async def send(self, channel_config: dict[str, Any], message: str) -> None:
        """Send the reply over SMTP, threaded under the mail it answers.

        Failures are raised, never swallowed, so the delivery consumer can act
        on them: misconfiguration (no reply_to / unresolvable credentials / SMTP
        auth rejected) raises ``FatalError`` (ACK + DLQ — retrying won't help);
        transient transport failures (connect/timeout/disconnect) raise
        ``RetryableError`` so the broker redelivers.
        """
        target = channel_config.get("target") or {}
        to_address = reply_address(target.get("to"))
        if to_address is None:
            raise FatalError(f"email channel: {target.get('to')!r} has no address to reply to")

        credential_type, credential_key = credentials_of(channel_config)
        smtp_creds = await self._credentials(
            workspace_id=str(channel_config["workspace_id"]),
            owner=str(channel_config["owner"]),
            credential_type=credential_type,
            credential_key=credential_key,
        )

        subject = reply_subject(target.get("subject"))
        from_addr = smtp_creds.get("from_address", "agent@agentarea.local")

        msg = MIMEMultipart("alternative")
        try:
            msg["Subject"] = subject
            msg["From"] = from_addr
            msg["To"] = to_address
        except (HeaderParseError, ValueError) as exc:
            # A header that cannot be written now never can be.
            raise FatalError(f"email channel: invalid header: {exc}") from exc

        # Thread the reply. Clients thread on References, so the whole chain
        # goes back out; the parent alone would start a sibling thread.
        original_message_id = target.get("message_id")
        if original_message_id:
            msg["In-Reply-To"] = original_message_id
        references = reply_references(target.get("references"), original_message_id)
        if references:
            msg["References"] = " ".join(references)

        # Plain text fallback + HTML
        plain_text = _html_to_plain(message)
        msg.attach(MIMEText(plain_text, "plain"))
        msg.attach(MIMEText(message, "html"))

        host = smtp_creds.get("smtp_host")
        if not host:
            raise FatalError("email channel: SMTP credentials have no smtp_host")
        try:
            sock = await self._connect(host, int(smtp_creds.get("smtp_port", 25)))
        except UnsafeUrlError as exc:
            raise FatalError(f"email channel: SMTP host refused: {exc}") from exc
        except (ConnectionError, TimeoutError, OSError) as exc:
            raise RetryableError(f"email channel: SMTP transport error: {exc}") from exc
        # The connection is made; the name stays for STARTTLS/TLS verification.
        smtp_kwargs: dict[str, Any] = {"hostname": host, "sock": sock}
        if smtp_creds.get("use_tls"):
            smtp_kwargs["use_tls"] = True
        username = smtp_creds.get("username")
        if username:
            smtp_kwargs["username"] = username
            smtp_kwargs["password"] = smtp_creds.get("password", "")

        try:
            await aiosmtplib.send(msg, **smtp_kwargs)
        except (HeaderParseError, ValueError) as exc:
            raise FatalError(f"email channel: the message cannot be sent: {exc}") from exc
        except aiosmtplib.SMTPAuthenticationError as exc:
            # Bad/rejected credentials — retrying with the same secret won't help.
            raise FatalError(f"email channel: SMTP authentication failed: {exc}") from exc
        except (
            aiosmtplib.SMTPConnectError,
            aiosmtplib.SMTPServerDisconnected,
            aiosmtplib.SMTPTimeoutError,
            ConnectionError,
            TimeoutError,
            OSError,
        ) as exc:
            raise RetryableError(f"email channel: SMTP transport error: {exc}") from exc
        except aiosmtplib.SMTPException as exc:
            # Unknown SMTP failure: prefer over-retry per the consumer contract.
            raise RetryableError(f"email channel: SMTP error: {exc}") from exc
        finally:
            sock.close()

        logger.info("Email sent to %s: %s", to_address, subject)


def reply_subject(subject: str | None) -> str:
    """The reply's subject on one line: a line break in the sender's subject is not a header."""
    subject = " ".join((subject or "").split())
    if not subject:
        return "Re: (no subject)"
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"


def reply_address(sender: str | None) -> str | None:
    """The one address a reply goes to: the first in the sender's ``Reply-To`` or ``From``."""
    if not sender:
        return None
    for _, address in getaddresses([str(sender)]):
        if "@" in address:
            return address
    return None


def reply_references(references: Any, message_id: str | None) -> list[str]:
    """The whole chain plus the mail answered: clients thread on ``References``."""
    if isinstance(references, str):
        chain = references.split()
    elif isinstance(references, list):
        chain = [str(reference) for reference in references]
    else:
        chain = []
    if message_id and message_id not in chain:
        chain.append(message_id)
    return chain


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _html_wrap(subject: str, body: str, status: str = "info") -> str:
    """Wrap content in a minimal HTML email template."""
    colors = {
        "success": "#22c55e",
        "error": "#ef4444",
        "warning": "#f59e0b",
        "info": "#3b82f6",
    }
    color = colors.get(status, colors["info"])

    return f"""<div style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto;">
  <div style="border-left: 4px solid {color}; padding: 12px 16px; margin: 16px 0;">
    <h3 style="margin: 0 0 8px 0; color: #1f2937;">{_escape_html(subject)}</h3>
    {body}
  </div>
  <p style="color: #9ca3af; font-size: 12px;">Sent by AgentArea</p>
</div>"""


def _html_to_plain(html: str) -> str:
    """Crude HTML to plain text conversion."""
    import re

    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return text.strip()


def create_email_adapter(credentials: CredentialReader) -> EmailAdapter:
    """Create the SMTP reply sender and register it."""
    adapter = EmailAdapter(credentials=credentials)
    register_adapter("smtp", adapter)
    return adapter
