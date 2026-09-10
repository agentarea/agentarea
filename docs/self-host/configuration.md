---
title: Configuration
type: reference
summary: Every environment variable each AgentArea service reads, and the Helm value that sets it.
prerequisites:
  - /self-host/requirements
related:
  - /self-host/env-migration
  - /self-host/kubernetes
  - /self-host/docker-compose
  - /self-host/secrets-backends
  - /self-host/networking
last_updated: 2026-09-10
---

# Configuration

The environment variables each service reads, grouped by service, with the Helm
value that produces each one.

## Synopsis

Configuration has two layers, and which one you edit depends on the deployment
target.

| Target | You edit | Which produces |
|---|---|---|
| Kubernetes | `values.yaml` | ConfigMaps and Secrets, via `charts/agentarea/config.yaml` |
| Docker Compose | `.env` | The `environment:` blocks in `docker-compose.yaml` |

On Kubernetes, `charts/agentarea/config.yaml` is the source of truth. It declares
one group per service; each group lists `configVars` (plain values),
`secrets` (pulled from a Secret by name and key), and `envExtras` (values
composed from other variables). `make helm-gen` regenerates the per-group
templates under `charts/agentarea/templates/configs/` from it, and CI fails if
the generated files drift from `config.yaml`.

Every group below maps to a generated ConfigMap named
`<release>-env-<group>`.

### Naming

Every variable AgentArea reads is `AGENTAREA_<DOMAIN>_<KEY>`, at most 34
characters, with at most three segments after the domain. The domain comes from
a closed list: `DB` `S3` `AUTH` `AUTHZ` `SECRET` `MCP` `SBX` `WF` `TASK` `TRIG`
`CHAN` `EVT` `CORS` `LOG` `REDIS` `KAFKA` `TOOL` `K8S`. A handful of app-level
names carry no domain — `AGENTAREA_ENV`, `AGENTAREA_API_URL`,
`AGENTAREA_APP_URL`, `AGENTAREA_EDITION`.

Durations carry their unit in the value, not the name: `30s`, `500ms`, `5m`,
`2h`, `7d`. A bare number is rejected rather than assumed to be seconds. Two
exceptions are named `..._SECONDS` and take plain integers, listed below.

An unprefixed name belongs to somebody else and keeps the name its owner
expects: the postgres image (`POSTGRES_USER`), the AWS SDK
(`AWS_ACCESS_KEY_ID`), OpenTelemetry (`OTEL_*`), the Ory SDK (`ORY_SDK_URL`),
the Next.js build (`NEXT_PUBLIC_*`), and the platform that starts the process
(`PORT`, `HOST`). `scripts/check_env_naming.py` enforces the split and runs in
CI; a name owned by a third party goes in that script's whitelist.

## Parameters

### Database (group `database`)

Consumed by the backend, worker, and event service.

| Variable | Helm value | Default |
|---|---|---|
| `AGENTAREA_DB_HOST` | `global.database.host`, or the bundled service when empty | derived |
| `AGENTAREA_DB_PORT` | `global.database.port` | `5432` |
| `AGENTAREA_DB_NAME` | `global.database.name` | `agentarea` |
| `AGENTAREA_DB_SSLMODE` | `global.database.sslMode` | `disable` |
| `AGENTAREA_DB_USER` | Secret `global.secrets.postgresql`, key `username` | generated |
| `AGENTAREA_DB_PASSWORD` | Secret `global.secrets.postgresql`, key `password` | generated |
| `AGENTAREA_DB_URL` | composed from the five above | `postgresql://$(AGENTAREA_DB_USER):$(AGENTAREA_DB_PASSWORD)@$(AGENTAREA_DB_HOST):$(AGENTAREA_DB_PORT)/$(AGENTAREA_DB_NAME)?sslmode=<sslMode>` |

`global.database.maxConnections` and `global.database.connectionTimeout` exist in
`values.yaml` but are not rendered into any environment variable by
`config.yaml`. Setting them changes nothing.

### Redis (group `redis`)

| Variable | Helm value | Default |
|---|---|---|
| `AGENTAREA_REDIS_HOST` | `global.redis.host`, or the bundled Valkey service when empty | derived |
| `AGENTAREA_REDIS_PORT` | `global.redis.port` | `6379` |
| `AGENTAREA_REDIS_PASSWORD` | Secret `global.secrets.redis`, key `redis-password` | generated |
| `AGENTAREA_REDIS_URL` | see precedence below | derived |

`AGENTAREA_REDIS_URL` is emitted by `templates/_redis-url.tpl`, not by the `redis` group,
in this order:

1. `global.redis.existingSecret` set — read from that Secret's
   `global.redis.existingSecretKey` (default `url`). Use this in production;
   managed Redis URLs carry credentials.
2. `global.redis.url` set — used literally.
3. Neither — derived as
   `redis://:$(AGENTAREA_REDIS_PASSWORD)@$(AGENTAREA_REDIS_HOST):$(AGENTAREA_REDIS_PORT)` against the bundled
   Valkey subchart.

`global.redis.database`, `ssl`, `maxConnections`, and `connectionTimeout` are
present in `values.yaml` but are not rendered into environment variables.

### Object storage (group `storage`)

Rendered only when `rustfs.enabled` is true.

| Variable | Helm value | Default |
|---|---|---|
| `AGENTAREA_S3_REGION` | `global.storage.region` | `us-east-1` |
| `AGENTAREA_S3_BUCKET` | `global.storage.bucket` | `agentarea-documents` |
| `AGENTAREA_S3_ARTIFACTS_BUCKET` | `global.storage.bucket` | `agentarea-documents` |
| `AGENTAREA_S3_ENDPOINT` | the RustFS service host, port 9000 | derived |
| `AGENTAREA_S3_ACCESS_KEY` | Secret `global.secrets.rustfs`, key `root-user` | generated |
| `AGENTAREA_S3_SECRET_KEY` | Secret `global.secrets.rustfs`, key `root-password` | generated |

`global.storage.publicEndpoint` is rendered in the `backend` group as
`AGENTAREA_S3_PUBLIC_ENDPOINT`, not here.

### Backend API (group `backend`)

| Variable | Helm value | Default |
|---|---|---|
| `PORT` | fixed | `8000` |
| `AGENTAREA_LOG_LEVEL` | fixed in `config.yaml` | `info` |
| `API_HOST` | `global.api.host` | `0.0.0.0` |
| `API_PORT` | `global.api.port` | `8000` |
| `AGENTAREA_API_URL` | `global.api.publicUrl`, else derived from `ingress.hosts.backend.host`, else the ClusterIP service URL | derived |
| `API_AUTH_ENABLED` | `global.api.auth.enabled` | `false` |
| `API_AUTH_HEADER_NAME` | `global.api.auth.headerName` | `""` |
| `API_AUTH_HEADER_VALUE` | Secret `global.secrets.application`, key `api-auth-header-value` | generated |
| `AGENTAREA_MCP_MANAGER_URL` | the MCP Manager service and `mcpManager.service.port` | derived |
| `AGENTAREA_MCP_TIMEOUT` | fixed | `30` |
| `MCP_LAZY_PROVISIONING_ENABLED` | `mcpManager.serverless.enabled` | `false` |
| `AGENTAREA_S3_PUBLIC_ENDPOINT` | `global.storage.publicEndpoint` | `""` |
| `METRICS_ENABLED` | `global.monitoring.prometheus.enabled` | `true` |
| `METRICS_PORT` | `global.monitoring.prometheus.port` | `9090` |
| `HEALTH_CHECK_ENABLED` | `global.monitoring.health.enabled` | `true` |
| `HEALTH_CHECK_PORT` | `global.monitoring.health.port` | `8001` |
| `AGENTAREA_AUTH_ISSUER` | `kratos.jwt.issuer` | `https://agentarea.dev` |
| `AGENTAREA_AUTH_AUDIENCE` | `kratos.jwt.audience` | `agentarea-api` |
| `AGENTAREA_AUTH_JWKS_B64` | Secret `<release>-kratos-jwks` or `kratos.secretName`, key `jwks_b64` | generated |

`METRICS_ENABLED`, `METRICS_PORT`, `HEALTH_CHECK_ENABLED`, and
`HEALTH_CHECK_PORT` are rendered by the chart but have no reader in the Python
source. The API serves `/health` on its normal port unconditionally and exposes
no `/metrics` endpoint. See [observability](/self-host/observability).

`AGENTAREA_API_URL` is the URL the backend advertises for itself — provider icon URLs,
OAuth protected-resource metadata, and the MCP `WWW-Authenticate` header. It must
be reachable by the client, not by the pod.

### Worker (group `worker`)

| Variable | Helm value | Default |
|---|---|---|
| `AGENTAREA_WF_MAX_ACTIVITIES` | fixed in `config.yaml` | `10` |
| `AGENTAREA_WF_MAX_WORKFLOWS` | fixed in `config.yaml` | `5` |
| `AGENTAREA_TASK_DISCOVERY_ENABLED` | fixed | `true` |
| `AGENTAREA_DEBUG` | fixed | `false` |
| `AGENTAREA_ENV` | fixed | `production` |
| `AGENTAREA_MCP_MANAGER_URL` | derived | — |
| `MCP_LAZY_PROVISIONING_ENABLED` | `mcpManager.serverless.enabled` | `false` |

`global.temporal.worker.maxConcurrentActivityExecutions`,
`maxConcurrentWorkflowTaskExecutions`, and `maxConcurrentSessionExecutions` in
`values.yaml` do not feed these variables — `config.yaml` hardcodes 10 and 5. To
change worker concurrency, use `worker.extraEnv`.

The worker must agree with the API on `MCP_LAZY_PROVISIONING_ENABLED`. The worker
dispatches agent tool calls, so it is a provisioning trigger in its own right;
without it a reclaimed instance stays down for agents.

### Temporal client (group `temporal`)

Consumed by the backend and the worker.

| Variable | Helm value | Default |
|---|---|---|
| `AGENTAREA_WF_TEMPORAL_URL` | `global.temporal.host` and `global.temporal.port` | derived, port `7233` |
| `AGENTAREA_WF_NAMESPACE` | `global.temporal.namespace` | `default` |
| `AGENTAREA_WF_QUEUE` | `global.temporal.taskQueue` | `agent-tasks` |

`global.temporal.client.connectionTimeout`, `rpcTimeout`, and `longPollTimeout`
are not rendered into environment variables.

### Temporal server (group `temporalServer`)

| Variable | Helm value | Default |
|---|---|---|
| `DB` | fixed | `postgres12` |
| `DB_PORT` | fixed | `5432` |
| `POSTGRES_SEEDS` | the database host | derived |
| `DBNAME` | `temporal.database.name` | `temporal` |
| `BIND_ON_IP` | fixed | `0.0.0.0` |
| `AGENTAREA_DB_USER` | Secret `global.secrets.postgresql`, key `username` | generated |
| `POSTGRES_PWD` | Secret `global.secrets.postgresql`, key `password` | generated |

### MCP Manager (group `mcpManager`)

| Variable | Helm value | Default |
|---|---|---|
| `AGENTAREA_LOG_LEVEL` | fixed | `INFO` |
| `AGENTAREA_API_URL` | the backend service, port 8000 | derived |
| `HOST` | fixed | `0.0.0.0` |
| `PORT` | fixed | `80` |
| `AGENTAREA_MCP_BACKEND` | fixed to `kubernetes` in `config.yaml` | `kubernetes` |
| `AGENTAREA_K8S_ENABLED` | fixed | `true` |
| `AGENTAREA_K8S_NAMESPACE` | the release namespace | derived |
| `AGENTAREA_K8S_DOMAIN` | `mcpManager.domain` | `mcp.local` |
| `AGENTAREA_K8S_GATEWAY` | `mcpManager.gateway.name` | `envoy-gateway` |
| `AGENTAREA_K8S_GATEWAY_NS` | `mcpManager.gateway.namespace` | `envoy-gateway-system` |
| `AGENTAREA_K8S_RUNTIME_CLASS` | `mcpManager.runtimeClass` | `""` |
| `AGENTAREA_K8S_SERVICE_ACCOUNT` | the zero-RBAC runtime ServiceAccount | derived |
| `AGENTAREA_K8S_CPU_REQUEST` | fixed | `100m` |
| `AGENTAREA_K8S_CPU_LIMIT` | fixed | `500m` |
| `AGENTAREA_K8S_MEMORY_REQUEST` | fixed | `128Mi` |
| `AGENTAREA_K8S_MEMORY_LIMIT` | fixed | `512Mi` |
| `AGENTAREA_MCP_FEATURES` | `mcpManager.features.enabled`, comma-joined | `gateway_api,state_reconciler` |
| `AGENTAREA_MCP_IDLE_TIMEOUT` | `mcpManager.serverless.idleTimeout` when `serverless.enabled`, else `0` | `0` |
| `AGENTAREA_MCP_SWEEP_INTERVAL` | `mcpManager.serverless.sweepInterval` | `60s` |

`AGENTAREA_MCP_IDLE_TIMEOUT` is derived from `serverless.enabled` rather than configured
separately. Only instances created as lazy are eligible for reclaim, so a timeout
without lazy start reclaims nothing, and lazy start without a timeout leaves
instances up forever. One switch makes both half-configured states unreachable.

`mcpManager.instancePod` (labels, annotations, nodeSelector, tolerations,
affinity, imagePullSecrets, priorityClassName) is passed to the manager as a
single JSON environment variable, `AGENTAREA_K8S_INSTANCE_POD`. Platform security
invariants — the managed-by label, securityContext and seccomp, the withheld
ServiceAccount token, and the RuntimeClass clamp — are applied on top and cannot
be weakened from these values.

### Frontend (group `frontend`)

| Variable | Helm value | Default |
|---|---|---|
| `PORT` | fixed | `3000` |
| `NODE_ENV` | fixed | `production` |
| `AGENTAREA_API_URL` | the backend service URL | derived |
| `ORY_SDK_URL` | `kratos.urls.public`, else the internal service | derived |
| `NEXT_PUBLIC_ORY_SDK_URL` | `kratos.urls.publicBrowser`, else `kratos.urls.public` | derived |
| `AGENTAREA_AUTH_KRATOS_ADMIN_URL` | `kratos.urls.admin`, else the internal service | derived |
| `METRICS_ENABLED` | `global.monitoring.prometheus.enabled` | `true` |
| `HEALTH_CHECK_ENABLED` | `global.monitoring.health.enabled` | `true` |

`ORY_SDK_URL` is used for server-side calls from the frontend container;
`NEXT_PUBLIC_ORY_SDK_URL` is what the browser is redirected to. Set
`kratos.urls.publicBrowser` separately whenever pods cannot resolve the public
domain.

### Application secrets (group `application`)

| Variable | Helm value | Default |
|---|---|---|
| `AGENTAREA_SECRET_ENCRYPTION_KEY` | Secret `global.secrets.application`, key `encryption-key` | generated |

### Secret manager (not in `config.yaml`)

Read by `SecretManagerSettings` in the platform. On Kubernetes, set these through
`backend.extraEnv` and `worker.extraEnv`.

| Variable | Type | Default | Description |
|---|---|---|---|
| `AGENTAREA_SECRET_BACKEND` | string | `database` | `database` or `infisical`. Any other value raises at startup. |
| `AGENTAREA_SECRET_ENCRYPTION_KEY` | string | unset | Fernet key. Required when type is `database`. |
| `AGENTAREA_SECRET_ENDPOINT` | string | unset | Infisical host. Defaults to `https://app.infisical.com` when unset. |
| `AGENTAREA_SECRET_CLIENT_ID` | string | unset | Infisical client ID. Required when type is `infisical`. |
| `AGENTAREA_SECRET_CLIENT_SECRET` | string | unset | Infisical client secret. Required when type is `infisical`. |

### Event service (group `eventService` values, chart keys only)

| Setting | Helm value | Default |
|---|---|---|
| Port | `eventService.port` | `8002` |
| Poll interval | `eventService.pollInterval` | `30s` |
| Max pollers | `eventService.maxPollers` | `10` |
| Inbound stream | `eventService.inboundStream` | `agentarea.channel.inbound` |
| Telegram long-polling | `eventService.telegramPolling.enabled` | `false` |

Telegram long-polling is a development fallback. Production Telegram ingress
uses webhooks.

### Sandbox runner (`mcpSandboxRunner`)

| Setting | Helm value | Default |
|---|---|---|
| Consumer group | `mcpSandboxRunner.consumerGroup` | `agentarea-sandbox-runners` |
| Batch size | `mcpSandboxRunner.batchSize` | `1` |
| Image | `mcpSandboxRunner.image` | falls back to `mcpManager.image` |
| Max command duration | `mcpManager.warmPool.maxExecutionTimeoutSeconds` | `1800` |

The runner consumes sandbox execution requests from Redis Streams. In Docker
Compose there is no separate runner: the manager runs it in-process
(`AGENTAREA_SBX_EMBEDDED_RUNNER=true`) and delegates execution to the
`sandbox-executor` container over `AGENTAREA_SBX_EXECUTOR_URL`.

### Docker Compose variables

Read from `.env` by `docker-compose.yaml`. Only the ones with no Kubernetes
equivalent are listed; the rest map onto the groups above.

| Variable | Required | Default in `.env.example` |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | yes | `postgres` / `postgres` / `agentarea` |
| `TEMPORAL_DB` | no | `temporal` |
| `KRATOS_DB` | no | `kratos` |
| `RUSTFS_ACCESS_KEY` / `RUSTFS_SECRET_KEY` / `RUSTFS_REGION` | yes | `minioadmin` / `minioadmin` / `us-east-1` |
| `DOCUMENTS_BUCKET` | yes | `ai-agents-bucket` |
| `ARTIFACTS_BUCKET` | no | `artifacts` |
| `AGENTAREA_SECRET_ENCRYPTION_KEY` | yes | a shipped development key |
| `AGENTAREA_SBX_ACTIVATION_SECRET` | yes, no default | development placeholder |
| `AGENTAREA_SBX_CLEANUP_SECRET` | yes, no default | development placeholder |
| `AGENTAREA_AUTH_JWKS_B64` / `AGENTAREA_AUTH_ISSUER` / `AGENTAREA_AUTH_AUDIENCE` | yes | a published test key |
| `SMTP_*` | for email delivery | targets the bundled Mailpit |
| `OIDC_GOOGLE_*` / `OIDC_GITHUB_*` | for social login | empty |
| `VERSION` | no | `latest` |
| `AGENTAREA_API_WORKERS` / `RELOAD` / `PORT` / `AGENTAREA_LOG_LEVEL` | no | `1` / `false` / `8000` / `info` |

The two sandbox secrets are declared `${VAR:?message}`, so Compose aborts rather
than starting with them empty.

## Errors

| Symptom | Cause | Action |
|---|---|---|
| Startup raises `AGENTAREA_SECRET_ENCRYPTION_KEY environment variable must be set` | `AGENTAREA_SECRET_BACKEND=database` with no key | Generate a Fernet key |
| Startup raises `Invalid AGENTAREA_SECRET_BACKEND` | Value is neither `database` nor `infisical` | Correct the value |
| Startup raises `Infisical credentials not configured` | Type is `infisical` without both keys | Set `AGENTAREA_SECRET_CLIENT_ID` and `AGENTAREA_SECRET_CLIENT_SECRET` |
| `docker compose` aborts before starting anything | A `${VAR:?}` variable is empty | Set the sandbox secrets |
| Presigned upload URLs point at an unreachable host | `AGENTAREA_S3_PUBLIC_ENDPOINT` empty with a cluster-only object store | Set `global.storage.publicEndpoint` |
| CI fails on a Helm change with a configs diff | `templates/configs/` is stale relative to `config.yaml` | Run `make helm-gen` and commit |

## Example

Override a value that `config.yaml` hardcodes, using the per-service extension
point:

```yaml
worker:
  extraEnv:
    - name: AGENTAREA_WF_MAX_ACTIVITIES
      value: "40"

backend:
  extraEnv:
    - name: AGENTAREA_SECRET_BACKEND
      value: infisical
    - name: AGENTAREA_SECRET_ENDPOINT
      value: https://infisical.example.com
```

## Related

- [Requirements](/self-host/requirements)
- [Deploy on Kubernetes with Helm](/self-host/kubernetes)
- [Deploy with Docker Compose](/self-host/docker-compose)
- [Choose a secrets backend](/self-host/secrets-backends)
- [Collect logs and metrics](/self-host/observability)
