"""Observability configuration."""

from pydantic_settings import BaseSettings


class ObservabilitySettings(BaseSettings):
    """OpenTelemetry and Prometheus configuration.

    The OpenTelemetry SDK reads standard OTEL_* variables itself. OTEL_ENABLED
    is AgentArea's explicit process-level gate for installing instrumentation.
    METRICS_ENABLED serves Prometheus metrics on METRICS_PORT, a listener of its
    own so that the public API port never answers ``/metrics``.
    """

    OTEL_ENABLED: bool = False
    OTEL_SERVICE_NAME: str = ""
    OTEL_EXPORTER_OTLP_PROTOCOL: str = "grpc"
    METRICS_ENABLED: bool = False
    METRICS_PORT: int = 9464

    model_config = {"env_file": ".env", "extra": "ignore"}
