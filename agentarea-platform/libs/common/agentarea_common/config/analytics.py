"""Anonymous usage analytics (wiki ADR-0041)."""

import re
from typing import Annotated

from pydantic import BeforeValidator
from pydantic_settings import NoDecode, SettingsConfigDict

from .base import BaseAppSettings

_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def parse_domains(value: object) -> tuple[str, ...]:
    """``example.com,example.org`` as lower-case domain names; empty is none."""
    if isinstance(value, str):
        value = value.split(",") if value.strip() else []
    if not isinstance(value, list | tuple):
        raise ValueError("AGENTAREA_ANALYTICS_OWN_DOMAINS must be comma-separated domain names")
    domains: list[str] = []
    for entry in value:
        domain = entry.strip().lower() if isinstance(entry, str) else ""
        labels = domain.split(".")
        if (
            len(labels) < 2
            or not all(_LABEL.fullmatch(label) for label in labels)
            or not labels[-1][0].isalpha()
        ):
            raise ValueError(
                f"AGENTAREA_ANALYTICS_OWN_DOMAINS: {entry!r} is not a domain name such as example.com"
            )
        domains.append(domain)
    return tuple(domains)


class AnalyticsSettings(BaseAppSettings):
    """Whether this installation reports anonymous usage statistics to AgentArea.

    Analytics, not telemetry: OpenTelemetry (AGENTAREA_OTEL_ENABLED, OTEL_*) goes
    to the operator's own monitoring. Off, nothing leaves the installation.
    """

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_ANALYTICS_")

    ENABLED: bool = True
    #: The key Kratos's after-registration hook presents on /internal/analytics/signups
    #: (ADR-0047). Unset, that endpoint does not exist.
    SIGNUP_HOOK_KEY: str | None = None
    #: The installation's own sites (ADR-0047): a referrer equal to one of these
    #: domains or below it is not an acquisition channel. Empty: none.
    OWN_DOMAINS: Annotated[tuple[str, ...], NoDecode, BeforeValidator(parse_domains)] = ()
