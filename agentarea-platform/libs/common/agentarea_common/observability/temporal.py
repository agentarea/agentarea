"""Temporal OpenTelemetry integration helpers."""

from agentarea_common.config import ObservabilitySettings


def get_temporal_plugins(settings: ObservabilitySettings | None = None):
    """Return Temporal client plugins for enabled integrations."""
    settings = settings or ObservabilitySettings()
    if not settings.OTEL_ENABLED:
        return []

    from temporalio.contrib.opentelemetry import OpenTelemetryPlugin

    return [OpenTelemetryPlugin()]
