"""Observability configuration."""

from pydantic_settings import SettingsConfigDict

from .base import BaseAppSettings


class ObservabilitySettings(BaseAppSettings):
    """OpenTelemetry traces and metrics.

    AGENTAREA_OTEL_ENABLED is our process-level gate for installing
    instrumentation. Everything else is the OpenTelemetry spec's own OTEL_*
    variables, which keep their names and are read where they are used.
    """

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_OTEL_")

    ENABLED: bool = False
