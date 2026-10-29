"""Temporal OpenTelemetry integration helpers."""

from agentarea_common.config import ObservabilitySettings


def get_temporal_plugins(settings: ObservabilitySettings | None = None):
    """Return Temporal client plugins for enabled integrations."""
    settings = settings or ObservabilitySettings()
    if not settings.ENABLED:
        return []

    from temporalio.contrib.opentelemetry import TracingInterceptor
    from temporalio.plugin import SimplePlugin

    # Not OpenTelemetryPlugin: it requires temporalio's replay-safe global
    # provider, whose tracer raises for any span started outside a workflow
    # (every request in the API, every activity's HTTP call). TracingInterceptor
    # works with the ordinary provider setup_telemetry installs.
    return [SimplePlugin("agentarea-tracing", interceptors=[TracingInterceptor()])]
