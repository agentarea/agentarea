"""One OpenTelemetry setup per process: traces and metrics under one Resource (ADR-0048).

AGENTAREA_OTEL_ENABLED is the gate; everything else is the specification's own
OTEL_* variables. Modules own their instruments through ``metrics.get_meter``;
those record nothing until ``setup_telemetry`` installs a provider. Every
instrument the process exports has a View here that names its attribute keys
and buckets; an instrument without one is dropped.
"""

from __future__ import annotations

import logging
import os
import socket
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from threading import Lock
from typing import TYPE_CHECKING

from opentelemetry.semconv._incubating.attributes.gen_ai_attributes import (
    GEN_AI_OPERATION_NAME,
    GEN_AI_PROVIDER_NAME,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_TOKEN_TYPE,
)
from opentelemetry.semconv._incubating.attributes.mcp_attributes import MCP_METHOD_NAME
from opentelemetry.semconv._incubating.metrics.gen_ai_metrics import (
    GEN_AI_CLIENT_OPERATION_DURATION,
    GEN_AI_CLIENT_OPERATION_TIME_TO_FIRST_CHUNK,
    GEN_AI_CLIENT_TOKEN_USAGE,
)
from opentelemetry.semconv._incubating.metrics.mcp_metrics import MCP_CLIENT_OPERATION_DURATION
from opentelemetry.semconv.attributes.deployment_attributes import DEPLOYMENT_ENVIRONMENT_NAME
from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE
from opentelemetry.semconv.attributes.http_attributes import (
    HTTP_REQUEST_METHOD,
    HTTP_RESPONSE_STATUS_CODE,
    HTTP_ROUTE,
)
from opentelemetry.semconv.attributes.k8s_attributes import K8S_NAMESPACE_NAME, K8S_POD_NAME
from opentelemetry.semconv.attributes.service_attributes import (
    SERVICE_INSTANCE_ID,
    SERVICE_NAME,
    SERVICE_NAMESPACE,
    SERVICE_VERSION,
)
from opentelemetry.semconv.metrics.http_metrics import (
    HTTP_CLIENT_REQUEST_DURATION,
    HTTP_SERVER_REQUEST_DURATION,
)

from agentarea_common.config import ObservabilitySettings

if TYPE_CHECKING:
    from opentelemetry.sdk.metrics.view import View
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace.export import SpanExporter

logger = logging.getLogger(__name__)

SERVICE_NAMESPACE_VALUE = "agentarea"
METRICS_EXPORTERS = ("otlp", "prometheus", "none")
OTLP_PROTOCOLS = ("http/protobuf", "grpc")
DEFAULT_EXPORT_INTERVAL_MS = 15_000
SEMCONV_OPT_IN = "OTEL_SEMCONV_STABILITY_OPT_IN"

HTTP_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)
GEN_AI_BUCKETS = (0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300, 600)
FIRST_CHUNK_BUCKETS = (0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60)
TOOL_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 900, 1800)
RUN_BUCKETS = (5, 15, 30, 60, 120, 300, 600, 1800, 3600, 7200, 21600)
TOKEN_BUCKETS = (1, 4, 16, 64, 256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304)

_GEN_AI_CALL = (
    GEN_AI_PROVIDER_NAME,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_OPERATION_NAME,
    "agentarea.llm.purpose",
)
_TOOL = ("agentarea.tool.kind", "path")
_GROUP = ("stream", "group")


@dataclass(frozen=True)
class InstrumentPolicy:
    """The attribute keys an instrument keeps and, for a histogram, its buckets."""

    attributes: tuple[str, ...] = ()
    buckets: tuple[float, ...] | None = None


INSTRUMENTS: dict[str, InstrumentPolicy] = {
    HTTP_SERVER_REQUEST_DURATION: InstrumentPolicy(
        (HTTP_REQUEST_METHOD, HTTP_ROUTE, HTTP_RESPONSE_STATUS_CODE), HTTP_BUCKETS
    ),
    HTTP_CLIENT_REQUEST_DURATION: InstrumentPolicy(
        (HTTP_REQUEST_METHOD, HTTP_RESPONSE_STATUS_CODE, ERROR_TYPE), HTTP_BUCKETS
    ),
    "agentarea.process.uptime": InstrumentPolicy(),
    "agentarea.authz.duration": InstrumentPolicy(("operation",), HTTP_BUCKETS),
    "agentarea.broker.group.lag": InstrumentPolicy(_GROUP),
    "agentarea.broker.group.pending": InstrumentPolicy(_GROUP),
    "agentarea.broker.group.oldest_pending": InstrumentPolicy(_GROUP),
    "agentarea.broker.dlq.length": InstrumentPolicy(("stream",)),
    "agentarea.broker.health": InstrumentPolicy(),
    "agentarea.run.transitions": InstrumentPolicy(("status", "failure_reason")),
    "agentarea.run.duration": InstrumentPolicy(("status",), RUN_BUCKETS),
    GEN_AI_CLIENT_OPERATION_DURATION: InstrumentPolicy((*_GEN_AI_CALL, ERROR_TYPE), GEN_AI_BUCKETS),
    GEN_AI_CLIENT_TOKEN_USAGE: InstrumentPolicy((*_GEN_AI_CALL, GEN_AI_TOKEN_TYPE), TOKEN_BUCKETS),
    GEN_AI_CLIENT_OPERATION_TIME_TO_FIRST_CHUNK: InstrumentPolicy(
        _GEN_AI_CALL, FIRST_CHUNK_BUCKETS
    ),
    "agentarea.llm.in_flight": InstrumentPolicy(_GEN_AI_CALL),
    "agentarea.tool.calls": InstrumentPolicy((*_TOOL, "outcome")),
    "agentarea.tool.call.duration": InstrumentPolicy((*_TOOL, "outcome"), TOOL_BUCKETS),
    "agentarea.tool.in_flight": InstrumentPolicy(_TOOL),
    "agentarea.tool.oldest_in_flight": InstrumentPolicy(_TOOL),
    MCP_CLIENT_OPERATION_DURATION: InstrumentPolicy((MCP_METHOD_NAME, ERROR_TYPE), TOOL_BUCKETS),
    "agentarea.mcp.client.era_renegotiated": InstrumentPolicy((ERROR_TYPE,)),
    "agentarea.mcp.dispatch_stamp.dropped": InstrumentPolicy(),
}

_SETUP_LOCK = Lock()
_CONFIGURED_SERVICE: str | None = None
_STARTED = time.monotonic()


def metric_views(instruments: Mapping[str, InstrumentPolicy] = INSTRUMENTS) -> list[View]:
    """A View per allowed instrument, and one that drops every other instrument."""
    from opentelemetry.sdk.metrics.view import (
        DropAggregation,
        ExplicitBucketHistogramAggregation,
        View,
    )

    views = [View(instrument_name="*", aggregation=DropAggregation())]
    for name, policy in instruments.items():
        aggregation = ExplicitBucketHistogramAggregation(policy.buckets) if policy.buckets else None
        views.append(
            View(
                instrument_name=name,
                attribute_keys=set(policy.attributes),
                aggregation=aggregation,
            )
        )
    return views


def metrics_exporter(env: Mapping[str, str]) -> str:
    """OTEL_METRICS_EXPORTER: ``otlp`` unless the process says otherwise."""
    value = env.get("OTEL_METRICS_EXPORTER", "").strip().lower() or "otlp"
    if value not in METRICS_EXPORTERS:
        raise RuntimeError(
            f"OTEL_METRICS_EXPORTER={value!r} is not supported; use one of "
            f"{', '.join(METRICS_EXPORTERS)}"
        )
    return value


def otlp_protocol(env: Mapping[str, str], signal: str) -> str:
    """The OTLP protocol of ``signal`` (TRACES or METRICS); the spec's default is http/protobuf."""
    specific = f"OTEL_EXPORTER_OTLP_{signal}_PROTOCOL"
    name = specific if env.get(specific, "").strip() else "OTEL_EXPORTER_OTLP_PROTOCOL"
    value = env.get(name, "").strip().lower() or "http/protobuf"
    if value not in OTLP_PROTOCOLS:
        raise RuntimeError(
            f"{name}={value!r} is not supported; use one of {', '.join(OTLP_PROTOCOLS)}"
        )
    return value


def missing_otlp_endpoint(env: Mapping[str, str], *, metrics_otlp: bool) -> str | None:
    """Why the OTLP endpoint is unusable, or None when every exporting signal has one.

    The SDK silently falls back to localhost:4318 when nothing is set, so an
    enabled process with no endpoint would export into the void.
    """
    if env.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip():
        return None
    traces = bool(env.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "").strip())
    metrics = bool(env.get("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "").strip())
    if traces and (metrics or not metrics_otlp):
        return None
    if traces:
        return (
            "AGENTAREA_OTEL_ENABLED is true and OTEL_EXPORTER_OTLP_TRACES_ENDPOINT is set, but "
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT is not: set it too, or set "
            "OTEL_EXPORTER_OTLP_ENDPOINT for every signal"
        )
    return (
        "AGENTAREA_OTEL_ENABLED is true but OTEL_EXPORTER_OTLP_ENDPOINT is not set "
        "(nor OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"
        + (" and OTEL_EXPORTER_OTLP_METRICS_ENDPOINT)" if metrics_otlp else ")")
    )


def semconv_opt_in(env: Mapping[str, str]) -> str:
    """The OTEL_SEMCONV_STABILITY_OPT_IN this process runs with; it must report stable HTTP.

    Without ``http`` the HTTP instrumentation emits the old millisecond metric
    names, which no View keeps. Any other value set is refused, not overridden.
    """
    value = env.get(SEMCONV_OPT_IN, "").strip()
    if not value:
        return "http"
    tokens = {token.strip() for token in value.split(",")}
    if "http" in tokens and "http/dup" not in tokens:
        return value
    raise RuntimeError(
        f"{SEMCONV_OPT_IN}={value!r} conflicts with the stable HTTP metrics telemetry exports; "
        "unset it or include 'http'"
    )


def export_interval_ms(env: Mapping[str, str]) -> int:
    raw = env.get("OTEL_METRIC_EXPORT_INTERVAL", "").strip()
    if not raw:
        return DEFAULT_EXPORT_INTERVAL_MS
    try:
        interval = int(raw)
    except ValueError:
        raise RuntimeError(f"OTEL_METRIC_EXPORT_INTERVAL={raw!r} is not milliseconds") from None
    if interval <= 0:
        raise RuntimeError(f"OTEL_METRIC_EXPORT_INTERVAL={raw!r} must be positive")
    return interval


def temporal_metrics_url(env: Mapping[str, str], protocol: str) -> str:
    """The URL Temporal's core exports metrics to; it uses the URL verbatim.

    Unlike the Python exporter, the core does not append ``/v1/metrics`` over HTTP.
    """
    specific = env.get("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "").strip()
    if specific:
        return specific
    base = env["OTEL_EXPORTER_OTLP_ENDPOINT"].strip()
    return base if protocol == "grpc" else f"{base.rstrip('/')}/v1/metrics"


def identity_attributes(
    service_name: str,
    *,
    version: str,
    environment: str,
    pod_name: str,
    pid: int,
) -> dict[str, str]:
    """The resource identity of one process; two replicas never share an instance id."""
    return {
        SERVICE_NAME: service_name,
        SERVICE_NAMESPACE: SERVICE_NAMESPACE_VALUE,
        SERVICE_VERSION: version,
        SERVICE_INSTANCE_ID: f"{pod_name}-{pid}",
        DEPLOYMENT_ENVIRONMENT_NAME: environment,
    }


def temporal_global_tags(attributes: Mapping[str, object]) -> dict[str, str]:
    """The identity Temporal's core merges into its own Resource."""
    keys = (
        SERVICE_NAME,
        SERVICE_NAMESPACE,
        SERVICE_VERSION,
        SERVICE_INSTANCE_ID,
        DEPLOYMENT_ENVIRONMENT_NAME,
        K8S_POD_NAME,
        K8S_NAMESPACE_NAME,
    )
    return {key: str(attributes[key]) for key in keys if key in attributes}


def setup_telemetry(service_name: str, settings: ObservabilitySettings | None = None) -> bool:
    """Install tracing and metrics for this process when AGENTAREA_OTEL_ENABLED is set.

    True when telemetry is on. Idempotent: the first call configures the process.
    Raises when telemetry is on and its configuration is incomplete.
    """
    settings = settings or ObservabilitySettings()
    if not settings.ENABLED:
        return False

    with _SETUP_LOCK:
        global _CONFIGURED_SERVICE
        if _CONFIGURED_SERVICE is not None:
            return True

        env = os.environ
        exporter = metrics_exporter(env)
        problem = missing_otlp_endpoint(env, metrics_otlp=exporter == "otlp")
        if problem is not None:
            raise RuntimeError(problem)
        traces_protocol = otlp_protocol(env, "TRACES")
        if exporter == "otlp":
            otlp_protocol(env, "METRICS")
            export_interval_ms(env)
        # Read by the instrumentations when they first instrument, after this.
        env[SEMCONV_OPT_IN] = semconv_opt_in(env)

        resource = _resource(env.get("OTEL_SERVICE_NAME") or service_name)
        _configure_tracing(resource, traces_protocol)
        _configure_metrics(resource, exporter, env)
        if exporter == "otlp":
            _configure_temporal_metrics(resource, env)
        _CONFIGURED_SERVICE = str(resource.attributes[SERVICE_NAME])
        logger.info(
            "OpenTelemetry enabled for %s (metrics exporter: %s)", _CONFIGURED_SERVICE, exporter
        )
        return True


def _resource(service_name: str) -> Resource:
    from opentelemetry.sdk.resources import Resource

    from agentarea_common import __version__
    from agentarea_common.config.app import get_app_settings

    detected = Resource.create({SERVICE_NAME: service_name})
    pod_name = str(detected.attributes.get(K8S_POD_NAME) or socket.gethostname())
    return detected.merge(
        Resource(
            identity_attributes(
                service_name,
                version=str(detected.attributes.get(SERVICE_VERSION) or __version__),
                environment=get_app_settings().ENV,
                pod_name=pod_name,
                pid=os.getpid(),
            )
        )
    )


def _span_exporter(protocol: str) -> SpanExporter:
    """The OTLP span exporter; it reads the standard OTEL_EXPORTER_OTLP_* variables itself."""
    if protocol == "grpc":
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    else:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    return OTLPSpanExporter()


def _configure_tracing(resource: Resource, protocol: str) -> None:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=resource, shutdown_on_exit=True)
    provider.add_span_processor(BatchSpanProcessor(_span_exporter(protocol)))
    trace.set_tracer_provider(provider)


def _configure_metrics(resource: Resource, exporter: str, env: Mapping[str, str]) -> None:
    from opentelemetry import metrics
    from opentelemetry.metrics import CallbackOptions, Observation
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader

    readers: list[MetricReader] = []
    if exporter == "otlp":
        if otlp_protocol(env, "METRICS") == "grpc":
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )
        else:
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter,
            )
        readers.append(
            PeriodicExportingMetricReader(
                OTLPMetricExporter(), export_interval_millis=export_interval_ms(env)
            )
        )
    elif exporter == "prometheus":
        from opentelemetry.exporter.prometheus import PrometheusMetricReader
        from prometheus_client import start_http_server

        readers.append(PrometheusMetricReader())
        port = int(env.get("OTEL_EXPORTER_PROMETHEUS_PORT", "").strip() or "9464")
        host = env.get("OTEL_EXPORTER_PROMETHEUS_HOST", "").strip() or "localhost"
        start_http_server(port=port, addr=host)
        logger.info("Prometheus metrics served on %s:%s/metrics", host, port)

    provider = MeterProvider(
        resource=resource,
        metric_readers=readers,
        views=metric_views(),
        shutdown_on_exit=True,
    )
    metrics.set_meter_provider(provider)

    def uptime(_options: CallbackOptions) -> Iterable[Observation]:
        yield Observation(time.monotonic() - _STARTED)

    metrics.get_meter("agentarea.process").create_observable_gauge(
        "agentarea.process.uptime",
        callbacks=[uptime],
        unit="s",
        description="Seconds since the process started; the heartbeat of its telemetry.",
    )


def _configure_temporal_metrics(resource: Resource, env: Mapping[str, str]) -> None:
    """Temporal's core exports its own metrics; set before any Temporal client exists."""
    from opentelemetry.util.re import parse_env_headers
    from temporalio.runtime import (
        OpenTelemetryConfig,
        OpenTelemetryMetricTemporality,
        Runtime,
        TelemetryConfig,
    )

    protocol = otlp_protocol(env, "METRICS")
    headers = (
        env.get("OTEL_EXPORTER_OTLP_METRICS_HEADERS", "").strip()
        or env.get("OTEL_EXPORTER_OTLP_HEADERS", "").strip()
    )
    Runtime.set_default(
        Runtime(
            telemetry=TelemetryConfig(
                metrics=OpenTelemetryConfig(
                    url=temporal_metrics_url(env, protocol),
                    headers=dict(parse_env_headers(headers, liberal=True)) if headers else None,
                    http=protocol != "grpc",
                    metric_periodicity=timedelta(milliseconds=export_interval_ms(env)),
                    metric_temporality=OpenTelemetryMetricTemporality.CUMULATIVE,
                    durations_as_seconds=True,
                ),
                global_tags=temporal_global_tags(resource.attributes),
                attach_service_name=False,
            )
        ),
        error_if_already_set=True,
    )
