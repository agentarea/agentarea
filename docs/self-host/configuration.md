---
title: Configuration
type: reference
description: "Every environment variable each AgentArea service reads, and the Helm value that sets it."
prerequisites:
  - /self-host/requirements
related:
  - /self-host/env-migration
  - /self-host/kubernetes
  - /self-host/docker-compose
  - /self-host/secrets-backends
  - /self-host/networking
last_updated: 2026-10-06
---

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

Every variable AgentArea reads is `AGENTAREA_<DOMAIN>_<KEY>`, at most 40
characters, with at most three segments after the domain. The domain comes from
a closed list: `DB` `S3` `AUTH` `AUTHZ` `SECRET` `MCP` `SANDBOX` `TEMPORAL`
`WORKER` `TASK` `TRIGGER` `CHANNEL` `EVENT` `CORS` `LOG` `REDIS` `KAFKA` `TOOL` `K8S`
`API` `HTTP` `OTEL` `BILLING` `METRICS` `A2A` `SPEND` `ANALYTICS`. Domains are whole words; only
established acronyms are abbreviated. A handful of
app-level names carry no domain — `AGENTAREA_ENV`, `AGENTAREA_API_URL`,
`AGENTAREA_APP_URL`, `AGENTAREA_EDITION`.

Durations carry their unit in the value, not the name: `30s`, `500ms`, `5m`,
`2h`, `7d`. A bare number is rejected rather than assumed to be seconds. Two
exceptions are named `..._SECONDS` and take plain integers, listed below.

An unprefixed name belongs to somebody else and keeps the name its owner
expects: the postgres image (`POSTGRES_USER`), the AWS SDK
(`AWS_ACCESS_KEY_ID`), OpenTelemetry (`OTEL_*`), the Ory SDK (`ORY_SDK_URL`),
OpenFGA (`OPENFGA_AUTHN_PRESHARED_KEY`), the Next.js build (`NEXT_PUBLIC_*`),
and the platform that starts the process (`PORT`, `HOST`). Where a library
reads its own connection settings, we use its names rather than inventing
ours: the Temporal client is `TEMPORAL_ADDRESS` / `TEMPORAL_NAMESPACE`
(with `TEMPORAL_API_KEY` and `TEMPORAL_TLS_*` for Temporal Cloud or mTLS),
and the execution cluster is `KUBECONFIG`.
`scripts/check_env_naming.py` enforces the split and runs in CI; a name owned by
a third party goes in that script's whitelist.

Upgrading from a release before this scheme: [Environment variable
migration](/self-host/env-migration) lists every old name and its replacement.

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
| `AGENTAREA_DB_TENANT_SCOPE` | `global.database.tenantScope` | `log` |

`AGENTAREA_DB_TENANT_SCOPE` is required and has no default in the platform. It
decides what an ORM query on a workspace-scoped table does when nothing bound a
workspace: `log` runs it unfiltered and logs one warning per call site, `enforce`
refuses it. Deploy with `log`, clear the warnings, then switch to `enforce`.

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
| `AGENTAREA_EVENT_NAMESPACE` | `global.events.namespace` | `agentarea` |
| `AGENTAREA_EVENT_PARTITIONS` | `global.events.partitions` | `16` |

Every broker topic and broker key is `<namespace>.<domain>.<dataset>`, for
example `agentarea.channel.inbound` or `agentarea.streams.events.3`.
`AGENTAREA_EVENT_NAMESPACE` is that first segment (lowercase letters, digits
and `-`); the broker adapters of every service put it in front, so two
deployments sharing one Redis need different namespaces. Stream events travel
on `AGENTAREA_EVENT_PARTITIONS` partitions of `streams.events`, each stream on
one of them. The API and the worker must agree on it, and changing it moves
streams to other partitions: let the `router` and `events-view` groups drain
first.

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

The bundled RustFS by default. With `rustfs.enabled=false` the same variables
name your own store, and `global.storage.endpoint` and
`global.storage.existingSecret` are required; the chart refuses to render
without them, and refuses them while RustFS is enabled.

| Variable | Helm value | Default |
|---|---|---|
| `AGENTAREA_S3_REGION` | `global.storage.region` | `us-east-1` |
| `AGENTAREA_S3_BUCKET` | `global.storage.bucket` | `agentarea-documents` |
| `AGENTAREA_S3_ARTIFACTS_BUCKET` | `global.storage.bucket` | `agentarea-documents` |
| `AGENTAREA_S3_ENDPOINT` | `global.storage.endpoint`; with RustFS, the RustFS service, port 9000 | derived |
| `AGENTAREA_S3_CONDITIONAL_WRITES` | `global.storage.conditionalWrites`: `native`, or `emulated` for a store that refuses or ignores `If-Match` / `If-None-Match` (Timeweb S3); mcp-manager then checks them under a per-object lock, which needs a single replica | `native` |
| `AGENTAREA_S3_ACCESS_KEY` | Secret `global.storage.existingSecret`, key `global.storage.accessKeyKey`; with RustFS, Secret `global.secrets.rustfs`, key `root-user` | generated |
| `AGENTAREA_S3_SECRET_KEY` | Secret `global.storage.existingSecret`, key `global.storage.secretKeyKey`; with RustFS, Secret `global.secrets.rustfs`, key `root-password` | generated |

`global.storage.publicEndpoint` is rendered in the `backend` group as
`AGENTAREA_S3_PUBLIC_ENDPOINT`, not here.

### Backend API (group `backend`)

| Variable | Helm value | Default |
|---|---|---|
| `PORT` | fixed | `8000` |
| `AGENTAREA_LOG_LEVEL` | fixed in `config.yaml` | `info` |
| `AGENTAREA_API_URL` | `global.api.publicUrl`, else derived from `ingress.hosts.backend.host`, else the ClusterIP service URL | derived |
| `AGENTAREA_MCP_MANAGER_URL` | the MCP Manager service and `mcpManager.service.port` | derived |
| `AGENTAREA_MCP_TIMEOUT` | fixed | `30` |
| `AGENTAREA_S3_PUBLIC_ENDPOINT` | `global.storage.publicEndpoint` | `""` |
| `AGENTAREA_ENV` | `global.deploymentEnv` | `production` |
| `AGENTAREA_ANALYTICS_ENABLED` | `global.analytics.enabled` | `true` |
| `AGENTAREA_ANALYTICS_SIGNUP_HOOK_KEY` | Secret `global.analytics.signupHookSecret`, key `signup-hook-key` | unset (no sign-up hook) |
| `AGENTAREA_ANALYTICS_OWN_DOMAINS` | `global.analytics.ownDomains` (a list) | empty (no own domains) |
| `AGENTAREA_AUTH_ISSUER` | `kratos.jwt.issuer` | `https://agentarea.dev` |
| `AGENTAREA_AUTH_AUDIENCE` | `kratos.jwt.audience` | `agentarea-api` |
| `AGENTAREA_AUTH_JWKS_B64` | Secret `<release>-kratos-jwks` or `kratos.secretName`, key `jwks_b64` | generated |
| `AGENTAREA_AUTH_KRATOS_ADMIN_URL` | `kratos.urls.admin` | in-cluster `<release>-kratos-admin:4434` |
| `AGENTAREA_APP_URL` | derived from the frontend ingress | `http://localhost:3000` |
| `AGENTAREA_A2A_AGENT_URL` | `global.envVars.AGENTAREA_A2A_AGENT_URL` | `http://{agent_id}.a2a.localhost:8000` |
| `SMTP_CONNECTION_URI` / `SMTP_FROM_EMAIL` / `SMTP_FROM_NAME` | `kratos.smtp.*` | empty (invitations are link-only) |
| `AGENTAREA_MCP_OAUTH_APPS` | Secret `global.mcpOAuthApps.existingSecret`, key `global.mcpOAuthApps.existingSecretKey` | unset (no platform OAuth apps) |

The API serves `/health` on its normal port unconditionally. Metrics and traces
are pushed over OTLP; see [Telemetry](#telemetry-every-first-party-deployment) and
[observability](/self-host/observability).

`AGENTAREA_ANALYTICS_ENABLED` sends anonymous usage statistics to AgentArea from the
backend and the worker; `false` sends nothing. It is not OpenTelemetry. The fields
sent are listed in [usage analytics](/self-host/analytics).

`AGENTAREA_ANALYTICS_SIGNUP_HOOK_KEY` is the key an Ory Kratos after-registration
web hook presents, as its `Authorization` header, to
`POST /internal/analytics/signups`. The backend then records which channel brought
each sign-up (see [usage analytics](/self-host/analytics)). Unset, the
endpoint answers 404.

`AGENTAREA_ANALYTICS_OWN_DOMAINS` lists the domains of your own sites, comma-separated,
such as `example.com,example.org`. A sign-up referred from one of them or from a
subdomain of one is not credited to a referrer. Empty, no site is your own. An
entry that is not a domain name (a URL, a port, a wildcard, an IP address) stops
the API and the worker at startup.

`AGENTAREA_API_URL` is the URL the backend advertises for itself — provider icon URLs,
OAuth protected-resource metadata, and the MCP `WWW-Authenticate` header. It must
be reachable by the client, not by the pod.

`AGENTAREA_A2A_AGENT_URL` is where each agent is served over A2A: one host per agent, with
the agent id as the host's first label, so the agent card sits at
`/.well-known/agent-card.json` on its own origin. The API answers that host
itself; the deployment provides a wildcard DNS record and a wildcard
certificate for the zone, and routes it to the backend. The value must be an
http(s) origin whose host starts with `{agent_id}.`, such as
`https://{agent_id}.a2a.example.com`; anything else stops the API at startup.
See [agent-to-agent communication](/concepts/agents/a2a#addresses).

`AGENTAREA_MCP_OAUTH_APPS` holds the operator's OAuth apps for remote MCP
servers whose authorization server has no Dynamic Client Registration, such as
GitHub. It is a JSON list of objects with `issuer`, `client_id`,
`client_secret`, `authorization_endpoint`, `token_endpoint`, and
`resource_origins` (exact https origins). A workspace connecting an MCP server
at one of `resource_origins` through `issuer` then authorizes with that app
without registering its own; tokens minted through it are sent only to
`resource_origins`. Unset, such providers need the workspace's own OAuth app.
The same list serves one-click catalog API connections (Google Search Console,
Yandex Metrica and the like): a catalog connection uses the app whose
`authorization_endpoint` and `token_endpoint` equal its own and whose
`resource_origins` include every API origin it calls. Register
`<API URL>/v1/oauth/callback` — the one callback for every OAuth connection,
MCP and catalog API alike — as a redirect URI with each app's provider. A malformed value stops the API and the worker at startup. Both read
it, the worker to refresh tokens.

### Worker (group `worker`)

| Variable | Helm value | Default |
|---|---|---|
| `AGENTAREA_TEMPORAL_MAX_ACTIVITIES` | fixed in `config.yaml` | `10` |
| `AGENTAREA_TEMPORAL_MAX_WORKFLOWS` | fixed in `config.yaml` | `5` |
| `AGENTAREA_DEBUG` | fixed | `false` |
| `AGENTAREA_ENV` | `global.deploymentEnv` | `production` |
| `AGENTAREA_MCP_MANAGER_URL` | derived | — |
| `AGENTAREA_MCP_OAUTH_APPS` | same Secret as the backend | unset |
| `AGENTAREA_TASK_OUTAGE_RETRY_WINDOW` | `worker.outageWait.retryWindow` | `5m` |
| `AGENTAREA_TASK_OUTAGE_WAIT_BACKOFF` | `worker.outageWait.backoff` | `1m,5m,10m` |
| `AGENTAREA_TASK_OUTAGE_WAIT_DEADLINE` | `worker.outageWait.deadline` | `24h` |
| `AGENTAREA_TASK_SKILLS_WINDOW_SHARE` | `worker.skillsWindowShare` | `0.3` |
| `AGENTAREA_ANALYTICS_ENABLED` | `global.analytics.enabled` | `true` |

The three `OUTAGE` durations decide how a run rides out a service it cannot
reach (see [waiting for a service](/concepts/execution/tasks#waiting-for-a-service)):
how long a call retries before the run starts waiting, the pauses between
retries while it waits (comma-separated, the last repeats), and how long it
waits before it fails with `dependency_unavailable`. Each must be positive. A
run keeps the values it was configured with. `AGENTAREA_TASK_SKILLS_WINDOW_SHARE`
is the share of the model's context window all of a run's activated skills may
take together, above 0 and at most 1; one skill takes at most a tenth.

`global.temporal.worker.maxConcurrentActivityExecutions`,
`maxConcurrentWorkflowTaskExecutions`, and `maxConcurrentSessionExecutions` in
`values.yaml` do not feed these variables — `config.yaml` hardcodes 10 and 5. To
change worker concurrency, use `worker.extraEnv`.

Neither the API nor the worker configures on-demand MCP start any more. Every
container-backed call goes through the manager's demand gateway, which starts a
cold workload itself; there is nothing for the Python side to agree on. See the
MCP Manager group below.

### Temporal client (group `temporal`)

Consumed by the backend and the worker.

| Variable | Helm value | Default |
|---|---|---|
| `TEMPORAL_ADDRESS` | `global.temporal.host` and `global.temporal.port` | derived, port `7233` |
| `TEMPORAL_NAMESPACE` | `global.temporal.namespace` | `default` |
| `AGENTAREA_TEMPORAL_QUEUE` | `global.temporal.taskQueue` | `agent-tasks` |

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
| `PORT` | fixed; the Service still answers on `mcpManager.service.port` | `8000` |
| `AGENTAREA_MCP_BACKEND` | fixed to `kubernetes` in `config.yaml` | `kubernetes` |
| `AGENTAREA_K8S_ENABLED` | fixed | `true` |
| `AGENTAREA_K8S_NAMESPACE` | the release namespace | derived |
| `AGENTAREA_K8S_DOMAIN` | `mcpManager.domain` | `mcp.local` |
| `AGENTAREA_K8S_GATEWAY` | `mcpManager.gateway.name` | `envoy-gateway` |
| `AGENTAREA_K8S_GATEWAY_NS` | `mcpManager.gateway.namespace` | `envoy-gateway-system` |
| `AGENTAREA_K8S_RUNTIME_CLASS` | `mcpManager.runtimeClass` | `""` |
| `AGENTAREA_K8S_SERVICE_ACCOUNT` | the zero-RBAC runtime ServiceAccount | derived |
| `AGENTAREA_K8S_NON_ROOT` | fixed | `true` |
| `AGENTAREA_K8S_READONLY_ROOT` | fixed | `true` |
| `AGENTAREA_K8S_CPU_REQUEST` | fixed | `100m` |
| `AGENTAREA_K8S_CPU_LIMIT` | fixed | `500m` |
| `AGENTAREA_K8S_MEMORY_REQUEST` | fixed | `128Mi` |
| `AGENTAREA_K8S_MEMORY_LIMIT` | fixed | `512Mi` |
| `AGENTAREA_MCP_FEATURES` | `mcpManager.features.enabled`, comma-joined | `gateway_api,state_reconciler` |
| `AGENTAREA_MCP_IDLE_TIMEOUT` | `mcpManager.serverless.idleTimeout` when `serverless.enabled`, else `0` | `10m` |
| `AGENTAREA_MCP_SWEEP_INTERVAL` | `mcpManager.serverless.sweepInterval` | `60s` |
| `AGENTAREA_MCP_LEASE_TTL` | `mcpManager.serverless.requestLeaseTTL` | `90s` |
| `AGENTAREA_MCP_STARTUP_TIMEOUT` | `mcpManager.serverless.startupTimeout` | `5m` |
| `AGENTAREA_MCP_GATEWAY_SECRET` | required, at least 32 characters; `global.runtimeCredentials` `mcp-gateway-token`. Shared with the API and worker: the gateway and the manager's instance, monitoring and container inspection routes reject requests without it | none |
| `AGENTAREA_MCP_PACKAGE_REPO` | `mcpManager.packageImages.repository` | `""` |
| `AGENTAREA_MCP_IMPORT_TIMEOUT` | `mcpManager.packageImages.importTimeout` | `15m` |
| `DOCKER_CONFIG` | `mcpManager.packageImages.registrySecret` | not set; `/etc/agentarea/mcp-registry` when a registry Secret is configured |

An empty `AGENTAREA_MCP_PACKAGE_REPO` uses the local Docker image store only when
the manager's backend is Docker; Kubernetes and data-plane backends require a
repository.

`mcpManager.packageImages.registrySecret` names an existing
`kubernetes.io/dockerconfigjson` Secret. The manager projects its
`.dockerconfigjson` key as `config.json` in a read-only mount at
`/etc/agentarea/mcp-registry`, and `DOCKER_CONFIG` points at that directory.

All four gateway durations are **required** — the manager refuses to start when
one is missing or unparseable, and only `AGENTAREA_MCP_IDLE_TIMEOUT` may be zero
(`LoadPolicyFromEnv` in `internal/mcpgateway/gateway.go`). Failing to boot is the
intended outcome: a gateway with an unset lease TTL would hold workloads open
indefinitely.

`serverless.enabled` collapses to a single duration: enabled renders
`idleTimeout`, disabled renders `0`, and `0` means "never reclaim". The switch
controls **idle reclaim only**. On-demand start is not conditional — every
container-backed call passes through the gateway, which serializes cold starts
and brings the workload up regardless of this setting.

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
| `ORY_BROWSER_URL` | `kratos.urls.publicBrowser`, else `kratos.urls.public` | derived |
| `AGENTAREA_AUTH_KRATOS_ADMIN_URL` | `kratos.urls.admin`, else the internal service | derived |
| `AGENTAREA_MCP_APPS_ORIGIN` | `global.webapp.appsSandboxUrl` | empty |
| `AGENTAREA_APP_ORIGIN` | `global.webapp.url`, else the internal frontend service URL | derived |

`ORY_SDK_URL` is used for server-side calls from the frontend container;
`ORY_BROWSER_URL` is what the browser is redirected to. Set
`kratos.urls.publicBrowser` separately whenever pods cannot resolve the public
domain.

The Apps page renders each MCP App inside an iframe loaded from
`AGENTAREA_MCP_APPS_ORIGIN`. The frontend answers `/app-sandbox` only when the
request's `Host` matches that origin, and the sandbox refuses to run unless it is
embedded by `AGENTAREA_APP_ORIGIN`. With `AGENTAREA_MCP_APPS_ORIGIN` empty, or equal
to the webapp origin, the Apps page lists apps but opens none. The ingress side
is in [networking](/self-host/networking).

Error reporting to Sentry (or a Sentry-compatible server such as GlitchTip) is
off until you set `SENTRY_DSN` through `frontend.envVars`; `SENTRY_ENVIRONMENT`
labels the events. Both are read at runtime, so one image serves every
deployment. The frontend reports browser errors, errors caught by the page error
boundaries, and server rendering and server action failures. Browser reports go
through the frontend's own `/api/monitoring` route, which forwards only to the
configured DSN and does not pass on the client IP. Events carry no user,
cookies, headers or request bodies, and URLs lose their query string and
fragment, which can hold invitation tokens and login flow ids.

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

### Event streams (not in `config.yaml`)

Read by `EventStreamSettings` inside both the backend (webhook intake, the
`/streams` routes) and the worker (the `router` and `events-view` consumer
groups and the partition maintainer). Not wired into any Helm group yet — set
these through `backend.extraEnv` and `worker.extraEnv`, matching values on
both, the same way as the secret manager settings just above.

| Variable | Type | Default | Description |
|---|---|---|---|
| `AGENTAREA_EVENT_WRITE_QUOTA` | integer | `600` | Events one workspace may append per rolling minute, counted across every stream it owns. Exceeding it answers a webhook `429`. |
| `AGENTAREA_EVENT_RETENTION` | duration | `7d` | How long the events read model (`stream_events`) keeps a day: an older daily partition is dropped whole. One setting for every stream. |
| `AGENTAREA_EVENT_ARCHIVE` | boolean | `false` | Before an expired day is dropped, write its events to the object store (`AGENTAREA_S3_BUCKET`) as gzipped JSONL, one object per workspace at `event-archive/<workspace>/<YYYY-MM-DD>.jsonl.gz`. A day the store does not take is kept, logged as an error, and tried again on the next pass. |
| `AGENTAREA_EVENT_PARTITIONS_AHEAD` | integer | `7` | Daily read-model partitions kept created ahead of today. |
| `AGENTAREA_EVENT_FORWARD_DEPTH` | integer | `8` | Longest causation chain a forward or a trigger firing may extend: past it a forward records an error and a trigger skips the event. A task started by an event is at that event's depth, and its outcome in the platform stream one deeper. |
| `AGENTAREA_EVENT_MAX_ATTEMPTS` | integer | `10` | Deliveries of one bus event before the router records the reactions still missing as `error` and moves the event to `streams.events.router.dlq`. |

These share the `EVENT` domain with `AGENTAREA_EVENT_POLL_INTERVAL` and
`AGENTAREA_EVENT_MAX_POLLERS` just below, but are unrelated settings: those
two configure the event service's poll sources; the five above configure the
event bus. See [Event streams](/concepts/integration/event-streams).

Stream events travel on Redis Streams (the partitions of `streams.events`, see
the Redis group above), so the API and the worker both refuse to start unless `AGENTAREA_BROKER=redis`
(the default, and what every chart and Compose file sets).

### Trigger batches (not in `config.yaml`)

Read by `TriggerSettings` in the backend (it refuses a trigger whose batch asks
for more) and in the worker (the router's trigger handler). Set the same value
on both through `backend.extraEnv` and `worker.extraEnv`.

| Variable | Type | Default | Description |
|---|---|---|---|
| `AGENTAREA_TRIGGER_BATCH_MAX_EVENTS` | integer | `100` | The most events one batch of a windowed stream trigger holds. A batch that reaches it fires at once, also before its window has passed; a trigger's own `max_events` may not exceed it. |

### Event service (group `eventService` values, chart keys only)

| Setting | Helm value | Default |
|---|---|---|
| Port | `eventService.port` | `8002` |
| Source reload interval (`AGENTAREA_EVENT_POLL_INTERVAL`) | `eventService.pollInterval` | `30s` |
| Max pollers (`AGENTAREA_EVENT_MAX_POLLERS`) | `eventService.maxPollers` | `10` |

The event service polls every stream source of kind `poll` at the interval its
catalog entry names, and registers the webhook of every webhook source whose
entry has a `registration` block (Telegram `setWebhook`). It publishes the raw
items to the `streams.ingest` topic, which the worker's `ingest` group turns into
stream events. `pollInterval` is how often it reads the set of sources again.

It also reads, from the groups above:

- `AGENTAREA_API_URL`: the public base of `/webhooks/{webhook_id}`, the URL it
  registers with a provider. Required; the chart sets the backend's own value.
- `AGENTAREA_SECRET_ENCRYPTION_KEY`: source credentials are read from the
  `database` secret backend. Required; the event service refuses to start with
  any other `AGENTAREA_SECRET_BACKEND`.
- `AGENTAREA_HTTP_ALLOW_PRIVATE`, `AGENTAREA_HTTP_PRIVATE_ALLOWLIST`: a host the
  member names (a feed URL, a mailbox) may reach only public addresses unless
  these open private ones, as for the backend.
- `AGENTAREA_MCP_MANAGER_URL`, `AGENTAREA_MCP_GATEWAY_SECRET`: MCP Events
  sources are polled and subscribed through the MCP manager's gateway, which
  adds the MCP server's credentials. Required; the chart sets both, the secret
  from the same Secret the backend reads.

### Sandbox runner (`mcpSandboxRunner`)

| Setting | Helm value | Default |
|---|---|---|
| Consumer group | `mcpSandboxRunner.consumerGroup` | `agentarea-sandbox-runners` |
| Batch size | `mcpSandboxRunner.batchSize` | `1` |
| Image | `mcpSandboxRunner.image` | falls back to `mcpManager.image` |
| Max command duration | `mcpManager.warmPool.maxExecutionTimeoutSeconds` | `1800` |

The runner consumes sandbox execution requests from Redis Streams. In Docker
Compose there is no separate runner: the manager runs it in-process
(`AGENTAREA_SANDBOX_EMBEDDED_RUNNER=true`) and delegates execution to the
`sandbox-executor` container over `AGENTAREA_SANDBOX_EXECUTOR_URL`.

### Telemetry (every first-party Deployment)

Rendered into backend, worker, mcp-manager and event-service by the
`agentarea.telemetry.envs` helper, only while `telemetry.enabled` is true.

| Variable | Helm value | Default |
|---|---|---|
| `AGENTAREA_OTEL_ENABLED` | `telemetry.enabled` | unset (off) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `telemetry.otlpEndpoint`, required when enabled | unset |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | fixed | `http/protobuf` |
| `OTEL_SEMCONV_STABILITY_OPT_IN` | fixed | `http` |
| `OTEL_RESOURCE_ATTRIBUTES` | fixed, from the Downward API `POD_NAME` and `POD_NAMESPACE` and the Deployment's image tag | `k8s.pod.name=$(POD_NAME),k8s.namespace.name=$(POD_NAMESPACE),service.version=<tag>` |

`AGENTAREA_OTEL_ENABLED=true` with no `OTEL_EXPORTER_OTLP_ENDPOINT` (or no
per-signal endpoints) stops the process at startup. `OTEL_METRICS_EXPORTER`
picks `otlp` (the default), `prometheus` (a scrape endpoint on
`OTEL_EXPORTER_PROMETHEUS_HOST`:`OTEL_EXPORTER_PROMETHEUS_PORT`, default
`localhost:9464`) or `none`; `OTEL_METRIC_EXPORT_INTERVAL` sets the push interval
in milliseconds (default `15000`). See [observability](/self-host/observability).

### Outbound TLS (not in `config.yaml`)

Read by `HttpSettings` in the backend and the worker.

| Variable | Helm value | Default |
|---|---|---|
| `AGENTAREA_HTTP_EXTRA_CA_CERTS` | `global.http.extraCaCerts` (PEM text) | unset |

Every request the platform sends to a host outside the deployment checks TLS
against one trust store: the system CAs and certifi's bundle, plus the PEM file
this variable names. The file adds to the public roots and never replaces them.
Set it when members connect services whose chain those roots leave out, such as
hosts certified by the Russian Trusted Root CA, or a corporate CA. It covers
OpenAPI spec fetches and tool calls, URL MCP servers, OAuth discovery and token
endpoints, A2A delegates, model discovery and model calls, skill and registry
imports, and channel webhooks.

On Kubernetes, put the PEM text of one or more certificates in
`global.http.extraCaCerts`: the chart stores it in the ConfigMap
`<release>-extra-ca-certs`, mounts it into the backend and worker at
`/etc/agentarea/extra-ca`, and sets the variable to the file there. In Docker
Compose, mount the file into `app` and `agentarea-worker` with an override file
and set the variable to its path inside the container.

A path that does not exist, cannot be read, or holds no certificate stops the
API and the worker at startup.

### Outbound URL policy (not in `config.yaml`)

Read by `HttpSettings` in the backend and the worker, by the event service, and
by the MCP manager for URL MCP servers reached through its gateway.

| Variable | Helm value | Default |
|---|---|---|
| `AGENTAREA_HTTP_PRIVATE_ALLOWLIST` | none (set it in the env values) | empty |
| `AGENTAREA_HTTP_ALLOW_PRIVATE` | none (set it in the env values) | `false` |

Every address a workspace member supplies is refused when it resolves to a
private, loopback, link-local or metadata address: a provider config's
`endpoint_url` (model test, runs, compaction, trigger conditions, media), URL MCP
servers, OpenAPI connections, A2A delegates, bundle and skill sources. Platform-managed
provider configs are called as configured.

`AGENTAREA_HTTP_PRIVATE_ALLOWLIST` admits named exceptions, comma-separated host
globs and CIDRs (`localhost,host.docker.internal`, `192.168.1.50/32`) for a model
server on the LAN or the host. Name each one: `*.svc.cluster.local` or a cluster
CIDR lets every member reach every in-cluster service, the platform's own
included. `AGENTAREA_HTTP_ALLOW_PRIVATE=true` admits every private address and
belongs only on a single-tenant install. `docker-compose.dev.yaml` allows
`localhost,host.docker.internal`; `docker-compose.yaml` allows nothing.

### Spend currency (not in `config.yaml`)

Read by `SpendSettings` in the backend and the worker.

| Variable | Helm value | Default |
|---|---|---|
| `AGENTAREA_SPEND_CURRENCY` | none (set it in the env values) | `USD` |

The one currency spend caps count and tool costs are declared in, as an ISO 4217
code. Nothing converts other currencies: a tool cost declared in another currency is
recorded in that currency and shown as not covered by caps. With the enterprise
billing extension installed, billing's ledger currency is the source of truth and
this must name it, or the backend and the worker refuse to start.

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
| `AGENTAREA_SANDBOX_ACTIVATION_SECRET` | yes, no default | empty; `scripts/gen-dev-secrets.sh` generates it |
| `AGENTAREA_SANDBOX_CLEANUP_SECRET` | yes, no default | empty; `scripts/gen-dev-secrets.sh` generates it |
| `AGENTAREA_AUTH_JWKS_B64` / `AGENTAREA_AUTH_ISSUER` / `AGENTAREA_AUTH_AUDIENCE` | yes | a published test key |
| `AGENTAREA_AUTH_KRATOS_ADMIN_URL` | yes, to show member names | `http://kratos:4434` |
| `SMTP_*` | for email delivery | targets the bundled Mailpit |
| `AGENTAREA_APP_URL` | for links in invitation email and the Telegram bot's account-link reply | `http://localhost:3000` |
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
| Startup raises `AGENTAREA_HTTP_EXTRA_CA_CERTS=... names no readable PEM file of CA certificates` | The file is missing, unreadable, or holds no certificate | Mount the PEM bundle at that path, or unset the variable |
| A connection fails with `CERTIFICATE_VERIFY_FAILED` | The host's chain ends at a CA outside the public roots | Add that CA to `AGENTAREA_HTTP_EXTRA_CA_CERTS` |
| Presigned upload URLs point at an unreachable host | `AGENTAREA_S3_PUBLIC_ENDPOINT` empty with a cluster-only object store | Set `global.storage.publicEndpoint` |
| CI fails on a Helm change with a configs diff | `templates/configs/` is stale relative to `config.yaml` | Run `make helm-gen` and commit |
| A webhook answers `429` | The workspace crossed `AGENTAREA_EVENT_WRITE_QUOTA` events in the trailing minute, across every stream it owns | Raise `AGENTAREA_EVENT_WRITE_QUOTA`; it is workspace-wide, not per stream |
| A webhook answers `413` | The request body is over the fixed 256 KiB event size cap | Send a reference to a workspace file instead of the content itself |

## Example

Override a value that `config.yaml` hardcodes, using the per-service extension
point:

```yaml
worker:
  extraEnv:
    - name: AGENTAREA_TEMPORAL_MAX_ACTIVITIES
      value: "40"

backend:
  extraEnv:
    - name: AGENTAREA_SECRET_BACKEND
      value: infisical
    - name: AGENTAREA_SECRET_ENDPOINT
      value: https://infisical.example.com
```

## Related

<Columns cols={2}>
  <Card title="Requirements" icon="server" href="/self-host/requirements">
    Host, cluster, and dependency versions required to run AgentArea, per
    deployment target
  </Card>
  <Card title="Deploy on Kubernetes with Helm" icon="server" href="/self-host/kubernetes">
    Install the agentarea Helm chart, decide which bundled dependencies to keep
  </Card>
  <Card title="Deploy with Docker Compose" icon="server" href="/self-host/docker-compose">
    Run the full AgentArea platform on one host with docker- compose.yaml
  </Card>
  <Card title="Choose a secrets backend" icon="server" href="/self-host/secrets-backends">
    Configure where AgentArea stores workspace secrets
  </Card>
  <Card title="Collect logs and metrics" icon="server" href="/self-host/observability">
    Read AgentArea's structured JSON logs, enable OpenTelemetry tracing
  </Card>
</Columns>
