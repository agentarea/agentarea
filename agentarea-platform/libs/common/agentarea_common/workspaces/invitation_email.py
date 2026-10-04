"""Delivering a workspace invitation by email.

Best-effort by design: the plaintext token goes back to the caller either way,
so the invitation still works when mail does not. Every outcome is reported so
the product surface can say whether the link still has to be shared by hand —
"we sent it" must never be implied by silence.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from urllib.parse import quote

from ..config import get_settings
from ..infrastructure.email import EmailMessage, SmtpMailer, get_mailer
from .repository import WorkspaceRepository

logger = logging.getLogger(__name__)


class InvitationEmailDelivery(StrEnum):
    SENT = "sent"
    NOT_REQUESTED = "not_requested"
    NOT_CONFIGURED = "not_configured"
    FAILED = "failed"


def build_invitation_email(
    *,
    recipient: str,
    invite_url: str,
    workspace_name: str,
) -> EmailMessage:
    subject = f"You have been invited to {workspace_name} on AgentArea"
    text_body = (
        f"You have been invited to join {workspace_name} on AgentArea.\n\n"
        f"Open this link to accept:\n{invite_url}\n\n"
        "If you were not expecting this invitation, ignore this email — "
        "the link only works for whoever opens it first, and it expires."
    )
    html_body = (
        f"<p>You have been invited to join <strong>{workspace_name}</strong> "
        "on AgentArea.</p>"
        f'<p><a href="{invite_url}">Accept the invitation</a></p>'
        f'<p style="color:#666;font-size:12px">Or paste this link into your '
        f"browser:<br>{invite_url}</p>"
        '<p style="color:#666;font-size:12px">If you were not expecting this '
        "invitation, ignore this email — the link only works for whoever opens "
        "it first, and it expires.</p>"
    )
    return EmailMessage(to=recipient, subject=subject, text_body=text_body, html_body=html_body)


async def deliver_invitation_email(
    *,
    mailer: SmtpMailer | None,
    recipient: str | None,
    invite_url: str,
    workspace_name: str,
) -> InvitationEmailDelivery:
    if not recipient:
        return InvitationEmailDelivery.NOT_REQUESTED
    if mailer is None:
        logger.info(
            "No transactional mail configured; invitation for %s is link-only",
            recipient,
        )
        return InvitationEmailDelivery.NOT_CONFIGURED

    try:
        await mailer.send(
            build_invitation_email(
                recipient=recipient,
                invite_url=invite_url,
                workspace_name=workspace_name,
            )
        )
    except Exception:
        # Never log invite_url — it carries the token.
        logger.exception("Failed to send workspace invitation email to %s", recipient)
        return InvitationEmailDelivery.FAILED

    return InvitationEmailDelivery.SENT


async def deliver_invitation_for_workspace(
    *,
    workspace_repo: WorkspaceRepository,
    workspace_id: str,
    recipient: str | None,
    token: str,
) -> InvitationEmailDelivery:
    """Compose and send the invitation for one workspace.

    Shared by the REST route and the members toolset so both surfaces produce
    the same email and report the same outcome.
    """
    base_url = get_settings().app.APP_URL.rstrip("/")
    workspace = await workspace_repo.get(workspace_id)
    return await deliver_invitation_email(
        mailer=get_mailer(),
        recipient=recipient,
        invite_url=f"{base_url}/invite?token={quote(token, safe='')}",
        # Without a workspace row there is no name to use, and a raw id in the
        # subject line would be worse than saying nothing specific.
        workspace_name=workspace.name if workspace is not None else "a workspace",
    )
