"""Observability configuration."""

from pydantic_settings import SettingsConfigDict

from .base import BaseAppSettings


class ObservabilitySettings(BaseAppSettings):
    """OpenTelemetry tracing.

    AGENTAREA_OTEL_ENABLED is our process-level gate for installing
    instrumentation. Everything else is the OpenTelemetry spec's own OTEL_*
    variables, which keep their names and are read where they are used.
    """

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_OTEL_")

    ENABLED: bool = False


class MetricsSettings(BaseAppSettings):
    """Prometheus metrics.

    Served on a listener of their own so the public API port never answers
    ``/metrics``.
    """

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_METRICS_")

    ENABLED: bool = False
    PORT: int = 9090
