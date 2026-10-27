"""Tests for OpenTelemetry bootstrap behavior."""

from agentarea_common.config import ObservabilitySettings
from agentarea_common.observability.otel import setup_otel


def test_setup_otel_returns_false_when_disabled():
    settings = ObservabilitySettings(ENABLED=False)

    assert setup_otel("agentarea-test", settings) is False


def test_enabled_is_read_from_the_prefixed_name(monkeypatch):
    monkeypatch.setenv("AGENTAREA_OTEL_ENABLED", "true")

    assert ObservabilitySettings(_env_file=None).ENABLED is True  # pyright: ignore[reportCallIssue]


def test_enabled_installs_a_provider_temporals_plugin_accepts(monkeypatch):
    # The worker's OpenTelemetryPlugin refuses any global provider that is not
    # replay-safe, and the worker exits on start.
    from opentelemetry import trace
    from temporalio.contrib.opentelemetry._tracer_provider import ReplaySafeTracerProvider

    from agentarea_common.observability import otel

    installed = []
    monkeypatch.setattr(trace, "set_tracer_provider", installed.append)
    monkeypatch.setattr(otel, "_CONFIGURED_SERVICE", None)

    assert otel.setup_otel("agentarea-test", ObservabilitySettings(ENABLED=True)) is True
    assert isinstance(installed[0], ReplaySafeTracerProvider)
