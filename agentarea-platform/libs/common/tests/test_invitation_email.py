"""Tests for delivering a workspace invitation by email.

Delivery is best-effort by design: the plaintext token is returned to the
caller either way, so a dead SMTP server must not fail the invitation. What it
must not do is stay quiet about it — every outcome is reported back so the UI
can tell the user whether to share the link themselves.
"""

from agentarea_common.config.email import EmailSettings
from agentarea_common.infrastructure.email import SmtpMailer
from agentarea_common.workspaces.invitation_email import (
    InvitationEmailDelivery,
    build_invitation_email,
    deliver_invitation_email,
)

TOKEN = "plaintext-token-value"  # noqa: S105 — fixture credential
INVITE_URL = f"https://app.example.com/invite?token={TOKEN}"


def _settings(**overrides) -> EmailSettings:
    base = {
        "SMTP_HOST": "mailpit",
        "SMTP_PORT": 1025,
        "SMTP_FROM_EMAIL": "noreply@agentarea.local",
        "SMTP_FROM_NAME": "AgentArea",
    }
    return EmailSettings(**{**base, **overrides})


class RecordingSender:
    def __init__(self, error: Exception | None = None):
        self.calls: list = []
        self.error = error

    async def __call__(self, message, **kwargs):
        if self.error is not None:
            raise self.error
        self.calls.append(message)


def _mailer(sender) -> SmtpMailer:
    return SmtpMailer(_settings(), send_fn=sender)


# --------------------------------------------------------------------------
# content
# --------------------------------------------------------------------------


def test_email_carries_the_invite_url_in_both_parts():
    message = build_invitation_email(
        recipient="invitee@example.com", invite_url=INVITE_URL, workspace_name="Acme"
    )

    assert INVITE_URL in message.text_body
    assert INVITE_URL in message.html_body
    assert message.to == "invitee@example.com"


def test_subject_names_the_workspace():
    message = build_invitation_email(
        recipient="invitee@example.com", invite_url=INVITE_URL, workspace_name="Acme"
    )

    assert "Acme" in message.subject


def test_the_raw_token_only_ever_appears_inside_the_invite_url():
    """The token is a credential; it belongs in the link, not loose in the prose.

    The URL itself may repeat — the html renders it both as an anchor and as
    copyable text, because mail clients strip links.
    """
    message = build_invitation_email(
        recipient="invitee@example.com", invite_url=INVITE_URL, workspace_name="Acme"
    )

    assert message.text_body.count(TOKEN) == message.text_body.count(INVITE_URL)
    assert message.html_body.count(TOKEN) == message.html_body.count(INVITE_URL)


# --------------------------------------------------------------------------
# delivery outcomes
# --------------------------------------------------------------------------


async def test_reports_sent_on_success():
    sender = RecordingSender()

    outcome = await deliver_invitation_email(
        mailer=_mailer(sender),
        recipient="invitee@example.com",
        invite_url=INVITE_URL,
        workspace_name="Acme",
    )

    assert outcome == InvitationEmailDelivery.SENT
    assert len(sender.calls) == 1


async def test_reports_not_requested_without_a_recipient():
    """A link-only invitation is a deliberate choice, not a failure."""
    sender = RecordingSender()

    outcome = await deliver_invitation_email(
        mailer=_mailer(sender),
        recipient=None,
        invite_url=INVITE_URL,
        workspace_name="Acme",
    )

    assert outcome == InvitationEmailDelivery.NOT_REQUESTED
    assert sender.calls == []


async def test_reports_not_configured_when_there_is_no_mailer():
    outcome = await deliver_invitation_email(
        mailer=None,
        recipient="invitee@example.com",
        invite_url=INVITE_URL,
        workspace_name="Acme",
    )

    assert outcome == InvitationEmailDelivery.NOT_CONFIGURED


async def test_a_dead_server_degrades_to_failed_and_is_logged(caplog):
    sender = RecordingSender(error=OSError("connection refused"))

    with caplog.at_level("ERROR"):
        outcome = await deliver_invitation_email(
            mailer=_mailer(sender),
            recipient="invitee@example.com",
            invite_url=INVITE_URL,
            workspace_name="Acme",
        )

    assert outcome == InvitationEmailDelivery.FAILED
    assert "invitation" in caplog.text.lower()
    # Logged with the traceback, not swallowed into a bare message.
    assert "connection refused" in caplog.text


async def test_the_token_never_reaches_the_logs(caplog):
    sender = RecordingSender(error=OSError("connection refused"))

    with caplog.at_level("ERROR"):
        await deliver_invitation_email(
            mailer=_mailer(sender),
            recipient="invitee@example.com",
            invite_url=INVITE_URL,
            workspace_name="Acme",
        )

    assert TOKEN not in caplog.text
