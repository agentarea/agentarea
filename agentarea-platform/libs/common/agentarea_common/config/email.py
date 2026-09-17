"""Outbound email settings for the platform's own transactional mail.

These read the deployment-level ``SMTP_*`` values, the same ones compose maps
into Kratos as ``COURIER_SMTP_*``. Sharing one server keeps a single sender
domain and one deliverability reputation to look after; reading our own keys
rather than Kratos' ``COURIER_*`` namespace keeps the two independent, so
reconfiguring one cannot silently break the other.

A deployment that never sets ``SMTP_HOST`` simply has no transactional mail —
callers must handle that explicitly rather than assume a send happened.
"""

from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import parse_qs, unquote, urlparse

from .base import BaseAppSettings


@dataclass(frozen=True)
class SmtpConnection:
    """Everything needed to open one SMTP session."""

    host: str
    port: int
    username: str | None
    password: str | None
    use_tls: bool
    start_tls: bool
    validate_certs: bool


def _is_true(values: dict[str, list[str]], key: str) -> bool:
    return values.get(key, ["false"])[0].lower() in ("1", "true", "yes")


class EmailSettings(BaseAppSettings):
    # Discrete values (how compose configures it) …
    SMTP_HOST: str = ""
    SMTP_PORT: int = 1025
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    # "smtp" (optionally upgraded with STARTTLS) or "smtps" (implicit TLS).
    SMTP_PROTOCOL: str = "smtp"
    SMTP_DISABLE_STARTTLS: bool = True
    SMTP_SKIP_SSL_VERIFY: bool = True
    # … or one URI, the shape the chart already uses for Kratos' courier, so a
    # deployment configures SMTP once and both senders read the same value.
    SMTP_CONNECTION_URI: str = ""

    SMTP_FROM_EMAIL: str = ""
    SMTP_FROM_NAME: str = "AgentArea"

    def connection(self) -> SmtpConnection | None:
        """Resolve the effective connection, or None when SMTP is not set up."""
        if self.SMTP_CONNECTION_URI.strip():
            return self._from_uri(self.SMTP_CONNECTION_URI.strip())
        if not self.SMTP_HOST.strip():
            return None
        implicit_tls = self.SMTP_PROTOCOL.strip().lower() == "smtps"
        return SmtpConnection(
            host=self.SMTP_HOST.strip(),
            port=self.SMTP_PORT,
            username=self.SMTP_USERNAME or None,
            password=self.SMTP_PASSWORD or None,
            use_tls=implicit_tls,
            start_tls=not implicit_tls and not self.SMTP_DISABLE_STARTTLS,
            validate_certs=not self.SMTP_SKIP_SSL_VERIFY,
        )

    def _from_uri(self, uri: str) -> SmtpConnection | None:
        parsed = urlparse(uri)
        if not parsed.hostname:
            return None
        implicit_tls = parsed.scheme.lower() == "smtps"
        query = parse_qs(parsed.query)
        return SmtpConnection(
            host=parsed.hostname,
            port=parsed.port or (465 if implicit_tls else 25),
            username=unquote(parsed.username) if parsed.username else None,
            password=unquote(parsed.password) if parsed.password else None,
            use_tls=implicit_tls,
            start_tls=not implicit_tls and not _is_true(query, "disable_starttls"),
            validate_certs=not _is_true(query, "skip_ssl_verify"),
        )

    @property
    def is_configured(self) -> bool:
        return self.connection() is not None and bool(self.SMTP_FROM_EMAIL.strip())

    @property
    def from_header(self) -> str:
        name = self.SMTP_FROM_NAME.strip()
        return f"{name} <{self.SMTP_FROM_EMAIL}>" if name else self.SMTP_FROM_EMAIL


@lru_cache
def get_email_settings() -> EmailSettings:
    return EmailSettings()
