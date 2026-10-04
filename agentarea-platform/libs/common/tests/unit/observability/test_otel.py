"""Tests for OpenTelemetry bootstrap behavior."""

from agentarea_common.config import ObservabilitySettings
from agentarea_common.observability.otel import setup_otel


def test_setup_otel_returns_false_when_disabled():
    settings = ObservabilitySettings(ENABLED=False)

    assert setup_otel("agentarea-test", settings) is False


def test_enabled_is_read_from_the_prefixed_name(monkeypatch):
    monkeypatch.setenv("AGENTAREA_OTEL_ENABLED", "true")

    assert ObservabilitySettings(_env_file=None).ENABLED is True  # pyright: ignore[reportCallIssue]
