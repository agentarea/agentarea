"""Tests for the process telemetry setup (ADR-0048)."""

import pytest
from agentarea_common.config import ObservabilitySettings
from agentarea_common.observability import telemetry
from agentarea_common.observability.telemetry import (
    InstrumentPolicy,
    identity_attributes,
    metric_views,
    metrics_exporter,
    missing_otlp_endpoint,
    otlp_protocol,
    semconv_opt_in,
    setup_telemetry,
    temporal_metrics_url,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader


def test_setup_returns_false_when_disabled():
    assert setup_telemetry("agentarea-test", ObservabilitySettings(ENABLED=False)) is False


def test_enabled_is_read_from_the_prefixed_name(monkeypatch):
    monkeypatch.setenv("AGENTAREA_OTEL_ENABLED", "true")

    assert ObservabilitySettings(_env_file=None).ENABLED is True  # pyright: ignore[reportCallIssue]


def test_enabled_without_an_endpoint_refuses_to_start(monkeypatch):
    for name in (
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
        "OTEL_METRICS_EXPORTER",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(telemetry, "_CONFIGURED_SERVICE", None)

    with pytest.raises(RuntimeError, match="OTEL_EXPORTER_OTLP_ENDPOINT"):
        setup_telemetry("agentarea-test", ObservabilitySettings(ENABLED=True))


def test_the_shared_endpoint_serves_every_signal():
    env = {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://gateway:4318"}

    assert missing_otlp_endpoint(env, metrics_otlp=True) is None


def test_signal_endpoints_must_cover_every_exporting_signal():
    traces_only = {"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://tempo:4318/v1/traces"}

    assert missing_otlp_endpoint(traces_only, metrics_otlp=False) is None
    problem = missing_otlp_endpoint(traces_only, metrics_otlp=True)
    assert problem is not None and "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT" in problem


def test_both_signal_endpoints_serve_without_the_shared_one():
    env = {
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://tempo:4318/v1/traces",
        "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "http://gateway:4318/v1/metrics",
    }

    assert missing_otlp_endpoint(env, metrics_otlp=True) is None


def test_a_traces_only_endpoint_names_the_missing_metrics_one():
    traces_only = {"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://tempo:4318/v1/traces"}

    problem = missing_otlp_endpoint(traces_only, metrics_otlp=True)

    assert problem is not None
    assert "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT is not" in problem


def test_the_http_opt_in_is_pinned_unless_set():
    assert semconv_opt_in({}) == "http"
    assert semconv_opt_in({"OTEL_SEMCONV_STABILITY_OPT_IN": " "}) == "http"
    assert semconv_opt_in({"OTEL_SEMCONV_STABILITY_OPT_IN": "http,database"}) == "http,database"


def test_a_conflicting_opt_in_is_refused_by_name():
    for value in ("http/dup", "database", "gen_ai_latest_experimental"):
        with pytest.raises(RuntimeError, match="OTEL_SEMCONV_STABILITY_OPT_IN"):
            semconv_opt_in({"OTEL_SEMCONV_STABILITY_OPT_IN": value})


def test_a_conflicting_opt_in_stops_setup_before_any_provider(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://gateway:4318")
    monkeypatch.setenv("OTEL_SEMCONV_STABILITY_OPT_IN", "http/dup")
    monkeypatch.setattr(telemetry, "_CONFIGURED_SERVICE", None)
    configured = []
    monkeypatch.setattr(telemetry, "_configure_tracing", lambda *args: configured.append(args))

    with pytest.raises(RuntimeError, match="http/dup"):
        setup_telemetry("agentarea-test", ObservabilitySettings(ENABLED=True))
    assert configured == []


def test_an_operator_service_version_is_kept(monkeypatch):
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "service.version=2026.10.29-abc123")

    resource = telemetry._resource("agentarea-test")

    assert resource.attributes["service.version"] == "2026.10.29-abc123"


def test_a_blank_endpoint_counts_as_unset():
    problem = missing_otlp_endpoint({"OTEL_EXPORTER_OTLP_ENDPOINT": "  "}, metrics_otlp=False)

    assert problem is not None and "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT" in problem


def test_metrics_exporter_defaults_to_otlp_and_rejects_the_unknown():
    assert metrics_exporter({}) == "otlp"
    assert metrics_exporter({"OTEL_METRICS_EXPORTER": "Prometheus"}) == "prometheus"
    with pytest.raises(RuntimeError, match="OTEL_METRICS_EXPORTER"):
        metrics_exporter({"OTEL_METRICS_EXPORTER": "console"})


def test_protocol_prefers_the_signal_variable_and_names_the_bad_one():
    env = {"OTEL_EXPORTER_OTLP_PROTOCOL": "grpc", "OTEL_EXPORTER_OTLP_METRICS_PROTOCOL": ""}

    assert otlp_protocol({}, "METRICS") == "http/protobuf"
    assert otlp_protocol(env, "METRICS") == "grpc"
    with pytest.raises(RuntimeError, match="OTEL_EXPORTER_OTLP_TRACES_PROTOCOL"):
        otlp_protocol({"OTEL_EXPORTER_OTLP_TRACES_PROTOCOL": "http/json"}, "TRACES")


def test_temporal_gets_the_metrics_path_the_core_does_not_append():
    base = {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel-gateway.monitoring:4318/"}

    assert (
        temporal_metrics_url(base, "http/protobuf")
        == "http://otel-gateway.monitoring:4318/v1/metrics"
    )
    assert temporal_metrics_url(base, "grpc") == "http://otel-gateway.monitoring:4318/"
    specific = {**base, "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "http://m:4318/custom"}
    assert temporal_metrics_url(specific, "http/protobuf") == "http://m:4318/custom"


def test_each_process_of_a_pod_has_its_own_instance_id():
    first = identity_attributes(
        "agentarea-api", version="1.0.0", environment="production", pod_name="api-0", pid=7
    )
    second = identity_attributes(
        "agentarea-api", version="1.0.0", environment="production", pod_name="api-0", pid=8
    )

    assert first["service.instance.id"] == "api-0-7"
    assert first["service.instance.id"] != second["service.instance.id"]
    assert first["service.namespace"] == "agentarea"


def _collect(policies, record):
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader], views=metric_views(policies))
    record(provider.get_meter("test"))
    data = reader.get_metrics_data()
    return {
        metric.name: metric.data.data_points
        for resource in (data.resource_metrics if data else [])
        for scope in resource.scope_metrics
        for metric in scope.metrics
    }


def test_views_keep_only_allowed_attributes_and_drop_unknown_instruments():
    def record(meter):
        meter.create_histogram("http.client.request.duration").record(
            0.2,
            {
                "http.request.method": "POST",
                "http.response.status_code": 200,
                "server.address": "instance-1234.mcp.example.com",
                "server.port": 443,
            },
        )
        meter.create_counter("agentarea.unlisted").add(1, {"tool": "anything"})

    points = _collect(telemetry.INSTRUMENTS, record)

    assert set(points) == {"http.client.request.duration"}
    [point] = points["http.client.request.duration"]
    assert dict(point.attributes or {}) == {
        "http.request.method": "POST",
        "http.response.status_code": 200,
    }


def test_views_apply_the_declared_buckets():
    policies = {"agentarea.run.duration": InstrumentPolicy(("status",), (5, 15))}

    points = _collect(
        policies,
        lambda meter: meter.create_histogram("agentarea.run.duration").record(
            7, {"status": "completed", "task_id": "t-1"}
        ),
    )

    [point] = points["agentarea.run.duration"]
    assert tuple(point.explicit_bounds) == (5, 15)
    assert dict(point.attributes or {}) == {"status": "completed"}


def test_a_span_started_outside_any_workflow_does_not_raise(monkeypatch):
    # The API's FastAPI and httpx instrumentation start spans on every request.
    # temporalio's replay-safe tracer raises there (it reads workflow time), and
    # the API failed its health check on every request.
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    installed = []
    monkeypatch.setattr(trace, "set_tracer_provider", installed.append)
    monkeypatch.setattr(telemetry, "_span_exporter", lambda _protocol: InMemorySpanExporter())

    telemetry._configure_tracing(Resource.create({}), "http/protobuf")
    installed[0].get_tracer("agentarea-test").start_span("GET /health").end()
    installed[0].shutdown()
