"""Email channel adapter for outbound message delivery via SMTP."""

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from . import register_adapter

logger = logging.getLogger(__name__)


class EmailAdapter:
    """Send messages via SMTP.

    Inbound is handled by data extractors (MailSlurper, IMAP).
    This adapter handles outbound: formatting events as HTML emails.

    Uses summary presentation — batches events and sends one email at completion.
    """

    def __init__(
        self,
        smtp_host: str = "localhost",
        smtp_port: int = 25,
        from_address: str = "agent@agentarea.local",
        use_tls: bool = False,
        username: str | None = None,
        password: str | None = None,
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.from_address = from_address
        self.use_tls = use_tls
        self.username = username
        self.password = password

    def format(self, event: dict[str, Any], presentation: str) -> str:
        """Format a workflow event as HTML for email.

        In summary mode, only result/interaction events come through.
        """
        event_type = event.get("event_type", "")
        data = event.get("data", {})

        if event_type == "WorkflowCompleted":
            result = data.get("result", "Task completed successfully.")
            return _html_wrap(
                subject="Task Complete",
                body=f"<p>{_escape_html(str(result))}</p>",
                status="success",
            )

        if event_type == "WorkflowFailed":
            error = data.get("error", "Unknown error")
            return _html_wrap(
                subject="Task Failed",
                body=f"<p><strong>Error:</strong> {_escape_html(str(error))}</p>",
                status="error",
            )

        if event_type == "WorkflowCancelled":
            return _html_wrap(
                subject="Task Cancelled",
                body="<p>The task was cancelled.</p>",
                status="warning",
            )

        if event_type == "HumanApprovalRequested":
            question = data.get("question", "Approval needed")
            return _html_wrap(
                subject="Action Required",
                body=f"<p><strong>Your input is needed:</strong></p>"
                f"<blockquote>{_escape_html(str(question))}</blockquote>"
                f"<p>Please respond via the AgentArea dashboard.</p>",
                status="warning",
            )

        if event_type == "HumanApprovalReceived":
            return _html_wrap(
                subject="Approval Received",
                body="<p>Your approval was received. The agent is continuing.</p>",
                status="success",
            )

        # Fallback
        return _html_wrap(
            subject=f"Agent Update: {event_type}",
            body=f"<p>{_escape_html(event_type)}</p>",
            status="info",
        )

    async def send(self, channel_config: dict[str, Any], message: str) -> None:
        """Send email via SMTP."""
        reply_to = channel_config.get("reply_to")
        if not reply_to:
            logger.error("No reply_to address in channel config")
            return

        subject = channel_config.get("subject", "Agent Update")
        from_addr = channel_config.get("from_address", self.from_address)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = reply_to

        # Add In-Reply-To for email threading
        original_message_id = channel_config.get("message_id")
        if original_message_id:
            msg["In-Reply-To"] = original_message_id
            msg["References"] = original_message_id

        # Plain text fallback + HTML
        plain_text = _html_to_plain(message)
        msg.attach(MIMEText(plain_text, "plain"))
        msg.attach(MIMEText(message, "html"))

        try:
            import aiosmtplib

            smtp_kwargs: dict[str, Any] = {
                "hostname": channel_config.get("smtp_host", self.smtp_host),
                "port": channel_config.get("smtp_port", self.smtp_port),
            }
            if self.use_tls:
                smtp_kwargs["use_tls"] = True
            if self.username:
                smtp_kwargs["username"] = self.username
                smtp_kwargs["password"] = self.password

            await aiosmtplib.send(msg, **smtp_kwargs)
            logger.info("Email sent to %s: %s", reply_to, subject)
        except ImportError:
            logger.error("aiosmtplib not installed — cannot send email")
        except Exception as e:
            logger.error("Email send failed: %s", e)


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


def create_email_adapter(
    smtp_host: str = "localhost",
    smtp_port: int = 25,
    from_address: str = "agent@agentarea.local",
    **kwargs: Any,
) -> EmailAdapter:
    """Create and register an email adapter."""
    adapter = EmailAdapter(smtp_host=smtp_host, smtp_port=smtp_port, from_address=from_address, **kwargs)
    register_adapter("email", adapter)
    return adapter
