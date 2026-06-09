"""Tests for OpenTelemetry bootstrap behavior."""

from agentarea_common.config import ObservabilitySettings
from agentarea_common.observability.otel import setup_otel


def test_setup_otel_returns_false_when_disabled():
    settings = ObservabilitySettings(OTEL_ENABLED=False)

    assert setup_otel("agentarea-test", settings) is False


def test_otel_service_name_can_override_default(monkeypatch):
    monkeypatch.setenv("OTEL_SERVICE_NAME", "custom-service")

    settings = ObservabilitySettings()

    assert settings.OTEL_SERVICE_NAME == "custom-service"
