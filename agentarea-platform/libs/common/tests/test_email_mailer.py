"""Tests for the transactional mailer.

This is the platform's own sender for product email (workspace invitations
today). It is deliberately separate from the trigger channel adapters: those
resolve per-trigger credentials from the secret store, while an invitation has
no trigger behind it. Kratos keeps sending its own auth email through its
courier — it has no API for sending ours.
"""

import pytest
from agentarea_common.config.email import EmailSettings
from agentarea_common.infrastructure.email import (
    EmailMessage,
    SmtpMailer,
    build_mailer,
)

RECIPIENT = "invitee@example.com"


def _settings(**overrides) -> EmailSettings:
    base = {
        "SMTP_HOST": "mailpit",
        "SMTP_PORT": 1025,
        "SMTP_USERNAME": "user",
        "SMTP_PASSWORD": "pass",
        "SMTP_FROM_EMAIL": "noreply@agentarea.local",
        "SMTP_FROM_NAME": "AgentArea",
        "SMTP_PROTOCOL": "smtp",
        "SMTP_DISABLE_STARTTLS": True,
        "SMTP_SKIP_SSL_VERIFY": True,
    }
    return EmailSettings(**{**base, **overrides})


class RecordingSender:
    def __init__(self, error: Exception | None = None):
        self.calls: list[tuple] = []
        self.error = error

    async def __call__(self, message, **kwargs):
        if self.error is not None:
            raise self.error
        self.calls.append((message, kwargs))


def _message() -> EmailMessage:
    return EmailMessage(
        to=RECIPIENT,
        subject="You have been invited",
        text_body="Open this link",
        html_body="<p>Open this link</p>",
    )


async def test_send_addresses_the_envelope_from_settings():
    sender = RecordingSender()

    await SmtpMailer(_settings(), send_fn=sender).send(_message())

    message, kwargs = sender.calls[0]
    assert message["To"] == RECIPIENT
    assert message["Subject"] == "You have been invited"
    assert message["From"] == "AgentArea <noreply@agentarea.local>"
    assert kwargs["hostname"] == "mailpit"
    assert kwargs["port"] == 1025
    assert kwargs["username"] == "user"
    assert kwargs["password"] == "pass"  # noqa: S105 — fixture credential


async def test_send_carries_both_a_text_and_an_html_part():
    sender = RecordingSender()

    await SmtpMailer(_settings(), send_fn=sender).send(_message())

    message, _ = sender.calls[0]
    parts = [p.get_content_type() for p in message.walk() if not p.is_multipart()]
    assert parts == ["text/plain", "text/html"]


async def test_text_only_message_sends_without_an_html_part():
    sender = RecordingSender()
    message = EmailMessage(to=RECIPIENT, subject="s", text_body="body", html_body=None)

    await SmtpMailer(_settings(), send_fn=sender).send(message)

    sent, _ = sender.calls[0]
    parts = [p.get_content_type() for p in sent.walk() if not p.is_multipart()]
    assert parts == ["text/plain"]


async def test_smtps_uses_implicit_tls():
    sender = RecordingSender()

    await SmtpMailer(_settings(SMTP_PROTOCOL="smtps"), send_fn=sender).send(_message())

    _, kwargs = sender.calls[0]
    assert kwargs["use_tls"] is True
    assert kwargs["start_tls"] is False


async def test_plain_smtp_can_disable_starttls_for_local_mailpit():
    sender = RecordingSender()

    await SmtpMailer(_settings(), send_fn=sender).send(_message())

    _, kwargs = sender.calls[0]
    assert kwargs["use_tls"] is False
    assert kwargs["start_tls"] is False


async def test_starttls_is_requested_when_not_disabled():
    sender = RecordingSender()

    await SmtpMailer(_settings(SMTP_DISABLE_STARTTLS=False), send_fn=sender).send(_message())

    _, kwargs = sender.calls[0]
    assert kwargs["start_tls"] is True


async def test_anonymous_smtp_omits_credentials():
    sender = RecordingSender()

    await SmtpMailer(_settings(SMTP_USERNAME="", SMTP_PASSWORD=""), send_fn=sender).send(_message())

    _, kwargs = sender.calls[0]
    assert kwargs["username"] is None
    assert kwargs["password"] is None


async def test_send_failures_propagate_to_the_caller():
    """The mailer does not decide what a failed send means — the caller does."""
    sender = RecordingSender(error=OSError("connection refused"))

    with pytest.raises(OSError, match="connection refused"):
        await SmtpMailer(_settings(), send_fn=sender).send(_message())


# --------------------------------------------------------------------------
# build_mailer — "configured" is a deliberate, checkable state
# --------------------------------------------------------------------------


def test_no_mailer_without_a_host():
    assert build_mailer(_settings(SMTP_HOST="")) is None


def test_no_mailer_without_a_from_address():
    """Sending from an empty envelope address is rejected by real servers."""
    assert build_mailer(_settings(SMTP_FROM_EMAIL="")) is None


def test_mailer_when_configured():
    assert isinstance(build_mailer(_settings()), SmtpMailer)


# --------------------------------------------------------------------------
# One connection URI configures both our mail and Kratos' courier
# --------------------------------------------------------------------------


async def test_connection_uri_supplies_host_port_and_credentials():
    sender = RecordingSender()
    settings = _settings(
        SMTP_HOST="",
        SMTP_CONNECTION_URI="smtps://alice%40corp:p%40ss@mail.example.com:2525/",
    )

    await SmtpMailer(settings, send_fn=sender).send(_message())

    _, kwargs = sender.calls[0]
    assert kwargs["hostname"] == "mail.example.com"
    assert kwargs["port"] == 2525
    # Credentials are percent-decoded — an @ in a username is legal.
    assert kwargs["username"] == "alice@corp"
    assert kwargs["password"] == "p@ss"  # noqa: S105 — fixture credential
    assert kwargs["use_tls"] is True


async def test_connection_uri_honours_kratos_query_flags():
    sender = RecordingSender()
    settings = _settings(
        SMTP_HOST="",
        SMTP_CONNECTION_URI="smtp://mailpit:1025/?disable_starttls=true&skip_ssl_verify=true",
    )

    await SmtpMailer(settings, send_fn=sender).send(_message())

    _, kwargs = sender.calls[0]
    assert kwargs["start_tls"] is False
    assert kwargs["validate_certs"] is False


async def test_connection_uri_defaults_the_port_per_scheme():
    assert _settings(SMTP_CONNECTION_URI="smtps://mail.example.com/").connection().port == 465
    assert _settings(SMTP_CONNECTION_URI="smtp://mail.example.com/").connection().port == 25


def test_connection_uri_wins_over_discrete_values():
    settings = _settings(SMTP_CONNECTION_URI="smtp://other.example.com:2525/")

    assert settings.connection().host == "other.example.com"


def test_a_uri_without_a_host_is_not_configuration():
    assert build_mailer(_settings(SMTP_HOST="", SMTP_CONNECTION_URI="not-a-uri")) is None
