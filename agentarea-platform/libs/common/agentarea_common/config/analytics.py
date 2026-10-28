"""Anonymous usage analytics (wiki ADR-0041)."""

from pydantic_settings import SettingsConfigDict

from .base import BaseAppSettings


class AnalyticsSettings(BaseAppSettings):
    """Whether this installation reports anonymous usage statistics to AgentArea.

    Analytics, not telemetry: OpenTelemetry and Prometheus (AGENTAREA_OTEL_*,
    AGENTAREA_METRICS_*) go to the operator's own monitoring. Off, nothing leaves
    the installation.
    """

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_ANALYTICS_")

    ENABLED: bool = True
    #: The key Kratos's after-registration hook presents on /internal/analytics/signups
    #: (ADR-0047). Unset, that endpoint does not exist.
    SIGNUP_HOOK_KEY: str | None = None
