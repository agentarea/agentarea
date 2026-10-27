"""Tests for OpenTelemetry bootstrap behavior."""

from agentarea_common.config import ObservabilitySettings
from agentarea_common.observability.otel import setup_otel


def test_setup_otel_returns_false_when_disabled():
    settings = ObservabilitySettings(ENABLED=False)

    assert setup_otel("agentarea-test", settings) is False


def test_enabled_is_read_from_the_prefixed_name(monkeypatch):
    monkeypatch.setenv("AGENTAREA_OTEL_ENABLED", "true")

    assert ObservabilitySettings(_env_file=None).ENABLED is True  # pyright: ignore[reportCallIssue]


def test_a_span_started_outside_any_workflow_does_not_raise(monkeypatch):
    # The API's FastAPI and httpx instrumentation start spans on every request.
    # temporalio's replay-safe tracer raises there (it reads workflow time), and
    # the API failed its health check on every request.
    from opentelemetry import trace

    from agentarea_common.observability import otel

    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    installed = []
    monkeypatch.setattr(trace, "set_tracer_provider", installed.append)
    monkeypatch.setattr(otel, "_CONFIGURED_SERVICE", None)
    monkeypatch.setattr(otel, "_create_otlp_span_exporter", InMemorySpanExporter)

    assert otel.setup_otel("agentarea-test", ObservabilitySettings(ENABLED=True)) is True
    installed[0].get_tracer("agentarea-test").start_span("GET /health").end()
