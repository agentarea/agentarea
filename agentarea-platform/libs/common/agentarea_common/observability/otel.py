"""OpenTelemetry bootstrap."""

import logging
from threading import Lock

from agentarea_common.config import ObservabilitySettings

logger = logging.getLogger(__name__)

_SETUP_LOCK = Lock()
_CONFIGURED_SERVICE: str | None = None


def setup_otel(service_name: str, settings: ObservabilitySettings | None = None) -> bool:
    """Configure OpenTelemetry for the current process when enabled.

    Returns True when OpenTelemetry is enabled for the process. The function is
    idempotent per service name so API/worker startup can call it freely.
    """
    settings = settings or ObservabilitySettings()
    if not settings.OTEL_ENABLED:
        return False

    resolved_service_name = settings.OTEL_SERVICE_NAME or service_name

    with _SETUP_LOCK:
        global _CONFIGURED_SERVICE
        if _CONFIGURED_SERVICE is not None:
            return True

        _configure_tracing(resolved_service_name, settings)
        _CONFIGURED_SERVICE = resolved_service_name
        logger.info("OpenTelemetry tracing enabled for %s", resolved_service_name)
        return True


def _configure_tracing(service_name: str, settings: ObservabilitySettings) -> None:
    """Install the tracer provider and OTLP span exporter."""
    from opentelemetry import trace
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    exporter = _create_otlp_span_exporter(settings)
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def _create_otlp_span_exporter(settings: ObservabilitySettings):
    """Create an OTLP exporter matching OTEL_EXPORTER_OTLP_PROTOCOL."""
    protocol = settings.OTEL_EXPORTER_OTLP_PROTOCOL.lower()
    if protocol == "http/protobuf":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    else:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    # Exporter constructors read standard OTEL_EXPORTER_OTLP_* env vars.
    return OTLPSpanExporter()
