---
title: Collect logs and traces
type: guide
summary: Read AgentArea's structured JSON logs, enable OpenTelemetry tracing, and understand which parts of the monitoring surface do not exist yet.
prerequisites:
  - /self-host/configuration
related:
  - /self-host/troubleshooting
  - /self-host/configuration
  - /self-host/kubernetes
last_updated: 2026-07-29
---

# Collect logs and traces

AgentArea emits structured JSON logs on stdout from every Python service, and
optional OpenTelemetry traces over OTLP. Both are real and configurable.

Metrics are not. There is no `/metrics` endpoint on the API, the worker, or the
MCP Manager, and no Prometheus exposition of any kind. The chart renders
`METRICS_ENABLED` and `METRICS_PORT` into the backend and frontend ConfigMaps,
but nothing in the source reads either variable. Plan your monitoring around
logs, traces, and health checks, and read the section below before wiring a
scrape config against something that will never answer.

## Prerequisites

- A running deployment
- A log collector that reads container stdout — Loki, Elasticsearch, CloudWatch, or `kubectl logs` for one-off work
- For tracing: an OTLP collector endpoint

## Steps

### 1. Read the log format

Every Python service calls `setup_logging(enable_structured_logging=True)` at
import time, which installs `WorkspaceContextFormatter`. Each record is one line
of JSON.

| Field | Always present | Meaning |
|---|---|---|
| `timestamp` | yes | Formatted by the standard library formatter |
| `level` | yes | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `logger` | yes | Logger name, for example `agentarea.audit` |
| `message` | yes | The rendered message |
| `user_id` | when a user context is bound | |
| `workspace_id` | when a user context is bound | |
| `trace_id` | when a valid OpenTelemetry span is current | 32 hex characters |
| `span_id` | when a valid OpenTelemetry span is current | 16 hex characters |
| `exception` | on `logger.exception()` or `exc_info=True` | Full traceback, newlines JSON-escaped so the record stays one physical line |
| `stack` | when `stack_info=True` | |
| `audit_event` | on audit records | |

Any other keyword passed as `extra=` is merged in at the top level, so
service-specific fields appear alongside these without further configuration.

Two named loggers exist: `agentarea` and `agentarea.audit`. Both write to stdout
with `propagate=False`. `agentarea.audit` is pinned to `INFO` when audit logging
is enabled and demoted to `WARNING` when it is not.

### 2. Rely on the redaction filters, and know their scope

Two filters run on every handler: `SecretRedactingFilter` then
`LogSanitizerFilter`. The first strips credentials out of messages, including
out of cached exception text; the second removes CR and LF, which is what stops
an attacker forging log lines by embedding newlines in user-controlled input.

`install_log_filters()` walks every logger that exists at call time and
normalizes the filter list on each of its handlers. This matters because handler
filters only run for records reaching that handler — uvicorn gives
`uvicorn.access` and `uvicorn.error` their own handlers with `propagate=False`,
so without this pass those records would bypass both filters entirely.

The limit: `install_log_filters()` runs once, during `setup_logging()`. Any
library that adds a handler afterwards is unprotected until it is called again.

### 3. Set the log level

| Service | Variable | Default |
|---|---|---|
| Backend | `LOG_LEVEL` | `info` (chart), `info` (Compose) |
| MCP Manager | `LOG_LEVEL` | `INFO` |
| Worker | not configurable by environment | `DEBUG` — `main.py` calls `setup_logging(level="DEBUG")` |
| Keto | `keto.config.log.level` | `info` |
| OpenFGA | `openfga.log.level` / `openfga.log.format` | `info` / `json` |

The worker's level is hardcoded at its call site, so a `LOG_LEVEL` set on the
worker deployment has no effect. Worker output is verbose by design; budget log
storage accordingly.

### 4. Ship the logs

Nothing to configure in AgentArea. Every service writes JSON to stdout, so the
container runtime collects it.

```bash
# All components of a release
kubectl logs -n agentarea -l app.kubernetes.io/instance=agentarea --all-containers=true -f

# One component
kubectl logs -n agentarea -l app.kubernetes.io/component=backend -f

# Compose
docker compose -f docker-compose.yaml logs -f app agentarea-worker
```

Because the format is JSON, filter on fields rather than grepping text:

```bash
kubectl logs -n agentarea -l app.kubernetes.io/component=backend \
  | jq -c 'select(.workspace_id == "<workspace-uuid>" and .level == "ERROR")'
```

### 5. Enable tracing

Tracing is off by default and gated by one variable. `setup_otel()` returns
immediately when `OTEL_ENABLED` is false, so the SDK is never installed.

```yaml
backend:
  extraEnv:
    - name: OTEL_ENABLED
      value: "true"
    - name: OTEL_EXPORTER_OTLP_ENDPOINT
      value: http://otel-collector.observability:4317
    - name: OTEL_EXPORTER_OTLP_PROTOCOL
      value: grpc

worker:
  extraEnv:
    - name: OTEL_ENABLED
      value: "true"
    - name: OTEL_EXPORTER_OTLP_ENDPOINT
      value: http://otel-collector.observability:4317
    - name: OTEL_EXPORTER_OTLP_PROTOCOL
      value: grpc
```

| Variable | Default | Meaning |
|---|---|---|
| `OTEL_ENABLED` | `false` | AgentArea's own gate. Nothing is installed unless this is true. |
| `OTEL_SERVICE_NAME` | `""` | Overrides the built-in name — `agentarea-api` or `agentarea-worker`. |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | `grpc`, or `http/protobuf` to use the HTTP exporter. |

Every other `OTEL_EXPORTER_OTLP_*` variable is read by the OpenTelemetry SDK
itself, not by AgentArea. `OTEL_EXPORTER_OTLP_ENDPOINT` in particular is the
SDK's, which is why it does not appear in the chart.

When enabled on the API, FastAPI, asyncpg, redis, and httpx are instrumented, so
spans cover inbound requests, database queries, cache calls, and outbound HTTP.
The worker additionally registers the Temporal OpenTelemetry plugin, which
propagates context across workflow and activity boundaries — that is what makes
a trace survive a durable execution rather than stopping at the workflow start.

Once tracing is on, `trace_id` and `span_id` appear in the log records, so a
trace in your collector and the logs for the same request join on those two
fields.

### 6. Use the health endpoints

| Service | Path | Port |
|---|---|---|
| Backend API | `/health` | 8000 |
| MCP Manager | `/health` | 80 in-cluster, 7999 under Compose |

The API response carries connection health, which is the useful part:

```json
{"status":"healthy","service":"agentarea-api","version":"0.1.0","connections":{},"timestamp":"..."}
```

The chart's `global.monitoring.health.port` (8001) does not move this endpoint.
It is rendered as `HEALTH_CHECK_PORT` and has no reader; the API serves `/health`
on its normal port.

The chart's liveness and readiness probes for the backend, frontend, and event
service are configurable under `<service>.livenessProbe` and
`<service>.readinessProbe`. RustFS is the exception: its probes are TCP, because
the `rustfs` image returns 403 on its health path.

### 7. Watch workflow execution in Temporal UI

Task execution is Temporal workflows, so the Temporal UI is the real execution
view — retries, failures, activity history.

```bash
kubectl port-forward -n agentarea svc/agentarea-temporal-ui 8080:8080
```

Under Compose the UI is in `docker-compose.dev.yaml` only, on port 8080.

### What does not exist

State this plainly before building on it:

- **No Prometheus metrics.** No service exposes `/metrics`. `METRICS_ENABLED` and `METRICS_PORT` are rendered by the chart and read by nothing.
- **Two Prometheus counters are defined but not exported.** `mcp_last_dispatch_dropped_total` and `mcp_dispatch_failed_total` (labelled by `reason`) are declared in the execution library and incremented at runtime, but no process serves the `prometheus_client` registry over HTTP. They are unreachable without adding an exposition endpoint yourself.
- **No first-party Go metrics.** `prometheus/client_golang` is an indirect dependency of the MCP Manager. There is no `promhttp` handler.
- **No bundled Grafana, Prometheus, Alertmanager, or Jaeger.** The chart deploys none of these and has no `monitoring.enabled` switch that does.
- **No shipped dashboards or alert rules.**

Third-party components in the stack do expose metrics on their own ports:
OpenFGA on `openfga.service.metricsPort` (2112) and Keto on 4468. Those are
genuine and scrapeable.

## Verify

Confirm the logs are structured, not plain text. A line that does not parse as
JSON means `setup_logging` did not run or something reconfigured logging after
it:

```bash
kubectl logs -n agentarea -l app.kubernetes.io/component=backend --tail=1 | jq .
```

Confirm the workspace context is present on request-scoped records:

```bash
kubectl logs -n agentarea -l app.kubernetes.io/component=backend \
  | jq -c 'select(.workspace_id != null) | {level, logger, workspace_id}' | head
```

Confirm tracing initialized. `setup_otel` logs once when it succeeds:

```bash
kubectl logs -n agentarea -l app.kubernetes.io/component=backend | grep "OpenTelemetry tracing enabled"
```

```
OpenTelemetry tracing enabled for agentarea-api
```

Absence of that line with `OTEL_ENABLED=true` means the variable did not reach
the process. Then send a request and confirm `trace_id` appears in the logs and
the matching trace arrives in your collector.

Confirm health:

```bash
kubectl port-forward -n agentarea svc/agentarea-backend 8000:8000 &
curl -s http://localhost:8000/health | jq .
```

## Troubleshooting

**Logs are plain text instead of JSON.** Something called `logging.basicConfig`
after `setup_logging`. Use `setup_logging` from `agentarea_common.logging`; it is
the only supported entry point, and `basicConfig` replaces the handler that
carries the formatter and the filters.

**Uvicorn access logs appear without redaction or with the workspace fields
missing.** `install_log_filters()` runs during `setup_logging()`. A handler added
after that point is not covered. Call it again after whatever added the handler.

**`OTEL_ENABLED=true` and no spans arrive.** Check the startup line first — if
`OpenTelemetry tracing enabled` is absent, the process never got the variable. If
it is present, the exporter is failing: the endpoint comes from
`OTEL_EXPORTER_OTLP_ENDPOINT`, which the SDK reads directly, and a mismatch
between `OTEL_EXPORTER_OTLP_PROTOCOL` and your collector's port is the usual
cause — 4317 for gRPC, 4318 for `http/protobuf`.

**Traces stop at the workflow boundary.** The worker does not have `OTEL_ENABLED`
set. Context propagation across activities comes from the Temporal plugin, which
is only registered on the worker.

**A Prometheus scrape of the API returns 404.** Expected. There is no `/metrics`
endpoint. See "What does not exist" above.

**Setting `global.monitoring.health.port` did not move the health endpoint.**
That value renders `HEALTH_CHECK_PORT`, which nothing reads. `/health` stays on
the service port.

**Worker logs are overwhelming.** The worker hardcodes `DEBUG` at its
`setup_logging` call. `LOG_LEVEL` on the deployment does not change it. Filter
at the collector.

## Related

- [Configuration](/self-host/configuration)
- [Troubleshoot a self-hosted deployment](/self-host/troubleshooting)
- [Deploy on Kubernetes with Helm](/self-host/kubernetes)
