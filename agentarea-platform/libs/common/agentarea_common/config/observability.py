"""Observability configuration."""

from pydantic_settings import BaseSettings


class ObservabilitySettings(BaseSettings):
    """OpenTelemetry configuration.

    The OpenTelemetry SDK reads standard OTEL_* variables itself. OTEL_ENABLED
    is AgentArea's explicit process-level gate for installing instrumentation.
    """

    OTEL_ENABLED: bool = False
    OTEL_SERVICE_NAME: str = ""
    OTEL_EXPORTER_OTLP_PROTOCOL: str = "grpc"

    model_config = {"env_file": ".env", "extra": "ignore"}
