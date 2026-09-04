---
title: Configuration
type: reference
summary: Every environment variable each AgentArea service reads, and the Helm value that sets it.
prerequisites:
  - /self-host/requirements
related:
  - /self-host/kubernetes
  - /self-host/docker-compose
  - /self-host/secrets-backends
  - /self-host/networking
last_updated: 2026-07-29
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

## Parameters

### Database (group `database`)

Consumed by the backend, worker, and event service.

| Variable | Helm value | Default |
|---|---|---|
| `POSTGRES_HOST` | `global.database.host`, or the bundled service when empty | derived |
| `POSTGRES_PORT` | `global.database.port` | `5432` |
| `POSTGRES_DB` | `global.database.name` | `agentarea` |
| `POSTGRES_SSLMODE` | `global.database.sslMode` | `disable` |
| `POSTGRES_USER` | Secret `global.secrets.postgresql`, key `username` | generated |
| `POSTGRES_PASSWORD` | Secret `global.secrets.postgresql`, key `password` | generated |
| `DATABASE_URL` | composed from the five above | `postgresql://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@$(POSTGRES_HOST):$(POSTGRES_PORT)/$(POSTGRES_DB)?sslmode=<sslMode>` |

`global.database.maxConnections` and `global.database.connectionTimeout` exist in
`values.yaml` but are not rendered into any environment variable by
`config.yaml`. Setting them changes nothing.

### Redis (group `redis`)

| Variable | Helm value | Default |
|---|---|---|
| `REDIS_HOST` | `global.redis.host`, or the bundled Valkey service when empty | derived |
| `REDIS_PORT` | `global.redis.port` | `6379` |
| `REDIS_PASSWORD` | Secret `global.secrets.redis`, key `redis-password` | generated |
| `REDIS_URL` | see precedence below | derived |

`REDIS_URL` is emitted by `templates/_redis-url.tpl`, not by the `redis` group,
in this order:

1. `global.redis.existingSecret` set — read from that Secret's
   `global.redis.existingSecretKey` (default `url`). Use this in production;
   managed Redis URLs carry credentials.
2. `global.redis.url` set — used literally.
3. Neither — derived as
   `redis://:$(REDIS_PASSWORD)@$(REDIS_HOST):$(REDIS_PORT)` against the bundled
   Valkey subchart.

`global.redis.database`, `ssl`, `maxConnections`, and `connectionTimeout` are
present in `values.yaml` but are not rendered into environment variables.

### Object storage (group `storage`)

Rendered only when `rustfs.enabled` is true.

| Variable | Helm value | Default |
|---|---|---|
| `AWS_REGION` | `global.storage.region` | `us-east-1` |
| `S3_BUCKET_NAME` | `global.storage.bucket` | `agentarea-documents` |
| `ARTIFACTS_BUCKET_NAME` | `global.storage.bucket` | `agentarea-documents` |
| `AWS_ENDPOINT_URL` | the RustFS service host, port 9000 | derived |
| `AWS_ACCESS_KEY_ID` | Secret `global.secrets.rustfs`, key `root-user` | generated |
| `AWS_SECRET_ACCESS_KEY` | Secret `global.secrets.rustfs`, key `root-password` | generated |

`global.storage.publicEndpoint` is rendered in the `backend` group as
`PUBLIC_S3_ENDPOINT`, not here.

### Backend API (group `backend`)

| Variable | Helm value | Default |
|---|---|---|
| `PORT` | fixed | `8000` |
| `LOG_LEVEL` | fixed in `config.yaml` | `info` |
| `API_HOST` | `global.api.host` | `0.0.0.0` |
| `API_PORT` | `global.api.port` | `8000` |
| `API_BASE_URL` | `global.api.publicUrl`, else derived from `ingress.hosts.backend.host`, else the ClusterIP service URL | derived |
| `API_AUTH_ENABLED` | `global.api.auth.enabled` | `false` |
| `API_AUTH_HEADER_NAME` | `global.api.auth.headerName` | `""` |
| `API_AUTH_HEADER_VALUE` | Secret `global.secrets.application`, key `api-auth-header-value` | generated |
| `MCP_MANAGER_URL` | the MCP Manager service and `mcpManager.service.port` | derived |
| `MCP_CLIENT_TIMEOUT` | fixed | `30` |
| `MCP_LAZY_PROVISIONING_ENABLED` | `mcpManager.serverless.enabled` | `false` |
| `PUBLIC_S3_ENDPOINT` | `global.storage.publicEndpoint` | `""` |
| `METRICS_ENABLED` | `global.monitoring.prometheus.enabled` | `true` |
| `METRICS_PORT` | `global.monitoring.prometheus.port` | `9090` |
| `HEALTH_CHECK_ENABLED` | `global.monitoring.health.enabled` | `true` |
| `HEALTH_CHECK_PORT` | `global.monitoring.health.port` | `8001` |
| `KRATOS_ISSUER` | `kratos.jwt.issuer` | `https://agentarea.dev` |
| `KRATOS_AUDIENCE` | `kratos.jwt.audience` | `agentarea-api` |
| `KRATOS_JWKS_B64` | Secret `<release>-kratos-jwks` or `kratos.secretName`, key `jwks_b64` | generated |

`METRICS_ENABLED`, `METRICS_PORT`, `HEALTH_CHECK_ENABLED`, and
`HEALTH_CHECK_PORT` are rendered by the chart but have no reader in the Python
source. The API serves `/health` on its normal port unconditionally and exposes
no `/metrics` endpoint. See [observability](/self-host/observability).

`API_BASE_URL` is the URL the backend advertises for itself — provider icon URLs,
OAuth protected-resource metadata, and the MCP `WWW-Authenticate` header. It must
be reachable by the client, not by the pod.

### Worker (group `worker`)

| Variable | Helm value | Default |
|---|---|---|
| `WORKFLOW__USE_WORKFLOW_EXECUTION` | fixed | `true` |
| `WORKFLOW__WORKFLOW_ENGINE` | fixed | `temporal` |
| `WORKFLOW__TEMPORAL_MAX_CONCURRENT_ACTIVITIES` | fixed in `config.yaml` | `10` |
| `WORKFLOW__TEMPORAL_MAX_CONCURRENT_WORKFLOWS` | fixed in `config.yaml` | `5` |
| `TASK__ENABLE_DYNAMIC_ACTIVITY_DISCOVERY` | fixed | `true` |
| `DEBUG` | fixed | `false` |
| `ENVIRONMENT` | fixed | `production` |
| `MCP_MANAGER_URL` | derived | — |
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
| `WORKFLOW__TEMPORAL_SERVER_URL` | `global.temporal.host` and `global.temporal.port` | derived, port `7233` |
| `WORKFLOW__TEMPORAL_NAMESPACE` | `global.temporal.namespace` | `default` |
| `WORKFLOW__TEMPORAL_TASK_QUEUE` | `global.temporal.taskQueue` | `agent-tasks` |

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
| `POSTGRES_USER` | Secret `global.secrets.postgresql`, key `username` | generated |
| `POSTGRES_PWD` | Secret `global.secrets.postgresql`, key `password` | generated |

### MCP Manager (group `mcpManager`)

| Variable | Helm value | Default |
|---|---|---|
| `LOG_LEVEL` | fixed | `INFO` |
| `CORE_API_URL` | the backend service, port 8000 | derived |
| `SERVER_HOST` | fixed | `0.0.0.0` |
| `SERVER_PORT` | fixed | `80` |
| `BACKEND_TYPE` | fixed to `kubernetes` in `config.yaml` | `kubernetes` |
| `KUBERNETES_ENABLED` | fixed | `true` |
| `KUBERNETES_NAMESPACE` | the release namespace | derived |
| `KUBERNETES_DOMAIN` | `mcpManager.domain` | `mcp.local` |
| `KUBERNETES_GATEWAY_NAME` | `mcpManager.gateway.name` | `envoy-gateway` |
| `KUBERNETES_GATEWAY_NAMESPACE` | `mcpManager.gateway.namespace` | `envoy-gateway-system` |
| `KUBERNETES_RUNTIME_CLASS` | `mcpManager.runtimeClass` | `""` |
| `KUBERNETES_POD_SERVICE_ACCOUNT_NAME` | the zero-RBAC runtime ServiceAccount | derived |
| `KUBERNETES_SECURITY_RUN_AS_NON_ROOT` | fixed | `true` |
| `KUBERNETES_SECURITY_READ_ONLY_ROOT_FS` | fixed | `true` |
| `KUBERNETES_DEFAULT_CPU_REQUEST` | fixed | `100m` |
| `KUBERNETES_DEFAULT_CPU_LIMIT` | fixed | `500m` |
| `KUBERNETES_DEFAULT_MEMORY_REQUEST` | fixed | `128Mi` |
| `KUBERNETES_DEFAULT_MEMORY_LIMIT` | fixed | `512Mi` |
| `MCP_FEATURES_ENABLED` | `mcpManager.features.enabled`, comma-joined | `gateway_api,state_reconciler` |
| `MCP_IDLE_TIMEOUT` | `mcpManager.serverless.idleTimeout` when `serverless.enabled`, else `0` | `0` |
| `MCP_IDLE_SWEEP_INTERVAL` | `mcpManager.serverless.sweepInterval` | `60s` |

`MCP_IDLE_TIMEOUT` is derived from `serverless.enabled` rather than configured
separately. Only instances created as lazy are eligible for reclaim, so a timeout
without lazy start reclaims nothing, and lazy start without a timeout leaves
instances up forever. One switch makes both half-configured states unreachable.

`mcpManager.instancePod` (labels, annotations, nodeSelector, tolerations,
affinity, imagePullSecrets, priorityClassName) is passed to the manager as a
single JSON environment variable, `KUBERNETES_INSTANCE_POD`. Platform security
invariants — the managed-by label, securityContext and seccomp, the withheld
ServiceAccount token, and the RuntimeClass clamp — are applied on top and cannot
be weakened from these values.

### Frontend (group `frontend`)

| Variable | Helm value | Default |
|---|---|---|
| `PORT` | fixed | `3000` |
| `NODE_ENV` | fixed | `production` |
| `API_URL` | the backend service URL | derived |
| `ORY_SDK_URL` | `kratos.urls.public`, else the internal service | derived |
| `ORY_BROWSER_URL` | `kratos.urls.publicBrowser`, else `kratos.urls.public` | derived |
| `ORY_ADMIN_URL` | `kratos.urls.admin`, else the internal service | derived |
| `METRICS_ENABLED` | `global.monitoring.prometheus.enabled` | `true` |
| `HEALTH_CHECK_ENABLED` | `global.monitoring.health.enabled` | `true` |

`ORY_SDK_URL` is used for server-side calls from the frontend container;
`ORY_BROWSER_URL` is what the browser is redirected to. Set
`kratos.urls.publicBrowser` separately whenever pods cannot resolve the public
domain.

### Application secrets (group `application`)

| Variable | Helm value | Default |
|---|---|---|
| `SECRET_MANAGER_ENCRYPTION_KEY` | Secret `global.secrets.application`, key `encryption-key` | generated |

### Secret manager (not in `config.yaml`)

Read by `SecretManagerSettings` in the platform. On Kubernetes, set these through
`backend.extraEnv` and `worker.extraEnv`.

| Variable | Type | Default | Description |
|---|---|---|---|
| `SECRET_MANAGER_TYPE` | string | `database` | `database` or `infisical`. Any other value raises at startup. |
| `SECRET_MANAGER_ENCRYPTION_KEY` | string | unset | Fernet key. Required when type is `database`. |
| `SECRET_MANAGER_ENDPOINT` | string | unset | Infisical host. Defaults to `https://app.infisical.com` when unset. |
| `SECRET_MANAGER_ACCESS_KEY` | string | unset | Infisical client ID. Required when type is `infisical`. |
| `SECRET_MANAGER_SECRET_KEY` | string | unset | Infisical client secret. Required when type is `infisical`. |

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
(`SANDBOX_EMBEDDED_RUNNER=true`) and delegates execution to the
`sandbox-executor` container over `SANDBOX_EXECUTOR_URL`.

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
| `SECRET_MANAGER_ENCRYPTION_KEY` | yes | a shipped development key |
| `SANDBOX_ACTIVATION_AUTH_SECRET` | yes, no default | development placeholder |
| `SANDBOX_CLEANUP_AUTH_SECRET` | yes, no default | development placeholder |
| `KRATOS_JWKS_B64` / `KRATOS_ISSUER` / `KRATOS_AUDIENCE` | yes | a published test key |
| `SMTP_*` | for email delivery | targets the bundled Mailpit |
| `OIDC_GOOGLE_*` / `OIDC_GITHUB_*` | for social login | empty |
| `VERSION` | no | `latest` |
| `WORKERS` / `RELOAD` / `PORT` / `LOG_LEVEL` | no | `1` / `false` / `8000` / `info` |

The two sandbox secrets are declared `${VAR:?message}`, so Compose aborts rather
than starting with them empty.

## Errors

| Symptom | Cause | Action |
|---|---|---|
| Startup raises `SECRET_MANAGER_ENCRYPTION_KEY environment variable must be set` | `SECRET_MANAGER_TYPE=database` with no key | Generate a Fernet key |
| Startup raises `Invalid SECRET_MANAGER_TYPE` | Value is neither `database` nor `infisical` | Correct the value |
| Startup raises `Infisical credentials not configured` | Type is `infisical` without both keys | Set `SECRET_MANAGER_ACCESS_KEY` and `SECRET_MANAGER_SECRET_KEY` |
| `docker compose` aborts before starting anything | A `${VAR:?}` variable is empty | Set the sandbox secrets |
| Presigned upload URLs point at an unreachable host | `PUBLIC_S3_ENDPOINT` empty with a cluster-only object store | Set `global.storage.publicEndpoint` |
| CI fails on a Helm change with a configs diff | `templates/configs/` is stale relative to `config.yaml` | Run `make helm-gen` and commit |

## Example

Override a value that `config.yaml` hardcodes, using the per-service extension
point:

```yaml
worker:
  extraEnv:
    - name: WORKFLOW__TEMPORAL_MAX_CONCURRENT_ACTIVITIES
      value: "40"

backend:
  extraEnv:
    - name: SECRET_MANAGER_TYPE
      value: infisical
    - name: SECRET_MANAGER_ENDPOINT
      value: https://infisical.example.com
```

## Related

- [Requirements](/self-host/requirements)
- [Deploy on Kubernetes with Helm](/self-host/kubernetes)
- [Deploy with Docker Compose](/self-host/docker-compose)
- [Choose a secrets backend](/self-host/secrets-backends)
- [Collect logs and metrics](/self-host/observability)
