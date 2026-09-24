"""Observability configuration."""

from pydantic import Field

from .base import BaseAppSettings


class ObservabilitySettings(BaseAppSettings):
    """OpenTelemetry configuration.

    ``OTEL_SERVICE_NAME`` and ``OTEL_EXPORTER_OTLP_PROTOCOL`` are read by the
    OpenTelemetry SDK itself, so they keep their spec names. Only the on/off
    switch is ours.
    """

    ENABLED: bool = Field(default=False, validation_alias="AGENTAREA_OTEL_ENABLED")
    OTEL_SERVICE_NAME: str = "agentarea"
    OTEL_EXPORTER_OTLP_PROTOCOL: str = "http/protobuf"
