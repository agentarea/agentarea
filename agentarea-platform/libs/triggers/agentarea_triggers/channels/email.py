"""Email channel adapter for outbound message delivery via SMTP."""

from __future__ import annotations

import json
import logging
import socket
from collections.abc import Awaitable, Callable
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING, Any

import aiosmtplib
from agentarea_common.outbound import member_connection
from agentarea_common.utils.url_safety import UnsafeUrlError

from . import register_adapter
from .exceptions import FatalError, RetryableError

if TYPE_CHECKING:
    from .secret_reader import SecretReader

logger = logging.getLogger(__name__)

Connect = Callable[[str, int], Awaitable[socket.socket]]


class EmailAdapter:
    """Send messages via SMTP.

    Inbound is handled by data extractors (e.g. IMAP).
    This adapter handles outbound: formatting events as HTML emails.

    Credentials (smtp_host, smtp_port, username, password, from_address, use_tls)
    are resolved from the secret store via channel_config["secret_key"].
    The secret store holds a JSON blob with these fields.
    """

    def __init__(self, secret_reader: SecretReader, connect: Connect = member_connection):
        self._secret_reader = secret_reader
        # The SMTP host is the member's: the connection goes to the address it
        # was vetted at (a test seam otherwise).
        self._connect = connect

    def format(self, event: dict[str, Any], presentation: str) -> str:
        """Format a workflow event as HTML for email.

        In summary mode, only result/interaction events come through.
        """
        event_type = event.get("event_type", "")
        data = event.get("data", {})

        if event_type == "task.completed":
            result = data.get("result", "Task completed successfully.")
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
        """Send email via SMTP.

        Resolves SMTP credentials from the secret store using
        channel_config["secret_key"].

        Failures are raised, never swallowed, so the delivery consumer can act
        on them: misconfiguration (no reply_to / unresolvable credentials / SMTP
        auth rejected) raises ``FatalError`` (ACK + DLQ — retrying won't help);
        transient transport failures (connect/timeout/disconnect) raise
        ``RetryableError`` so the broker redelivers.
        """
        reply_to = channel_config.get("reply_to")
        if not reply_to:
            raise FatalError("email channel: no reply_to address in channel config")

        # Raises FatalError if credentials cannot be resolved.
        smtp_creds = await self._resolve_smtp_credentials(channel_config)

        subject = channel_config.get("subject", "Agent Update")
        from_addr = smtp_creds.get("from_address", "agent@agentarea.local")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = reply_to

        # Thread the reply. Clients thread on References, so the whole chain
        # goes back out; the parent alone would start a sibling thread.
        original_message_id = channel_config.get("message_id")
        if original_message_id:
            msg["In-Reply-To"] = original_message_id
        references = channel_config.get("references") or (
            [original_message_id] if original_message_id else []
        )
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

        logger.info("Email sent to %s: %s", reply_to, subject)

    async def _resolve_smtp_credentials(self, channel_config: dict[str, Any]) -> dict[str, Any]:
        """Resolve SMTP credentials from the secret store.

        Secret name is derived: channel_cred:{type}:{trigger_id}

        Raises ``FatalError`` when credentials cannot be resolved — a
        misconfigured channel won't be fixed by redelivery.
        """
        trigger_id = channel_config.get("trigger_id")
        if not trigger_id:
            raise FatalError(
                "email channel: no trigger_id in channel_config — cannot resolve credentials"
            )

        # A polled mailbox keeps one credential blob covering both IMAP and
        # SMTP, so the origin says which one to read instead of assuming the
        # secret is named after the outbound channel.
        cred_type = channel_config.get("credential_type") or channel_config.get("type", "email")
        secret_name = f"channel_cred:{cred_type}:{trigger_id}"
        raw = await self._secret_reader.get_secret(secret_name)
        if not raw:
            raise FatalError(
                f"email channel: credentials not found for trigger {trigger_id} "
                f"(secret {secret_name!r})"
            )

        return json.loads(raw)


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


def create_email_adapter(secret_reader: SecretReader) -> EmailAdapter:
    """Create and register an email adapter."""
    adapter = EmailAdapter(secret_reader=secret_reader)
    register_adapter("email", adapter)
    return adapter
