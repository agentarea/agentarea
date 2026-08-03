---
title: Troubleshoot a self-hosted deployment
type: guide
summary: Diagnose a deployment that will not start, will not migrate, will not authenticate, or will not run tasks.
prerequisites:
  - /self-host/requirements
related:
  - /self-host/docker-compose
  - /self-host/kubernetes
  - /self-host/database-and-migrations
  - /self-host/observability
  - /self-host/networking
last_updated: 2026-07-29
---

# Troubleshoot a self-hosted deployment

Start by establishing which layer is broken, then jump to that section. Working
downward from the symptom the user reported usually costs more time than
checking the four layers in order.

This page covers infrastructure — the platform not starting, not migrating, not
authenticating. For a task that runs and produces the wrong result, the problem
is the agent, not the deployment.

## Prerequisites

- Shell access to the Compose host, or `kubectl` against the namespace
- `jq` for reading the JSON logs

## Steps

### 1. Establish which layer is broken

Run these four in order and stop at the first that fails.

```bash
# 1. Are the containers running and the one-shot jobs complete?
docker compose -f docker-compose.yaml ps
kubectl get pods,jobs -n agentarea

# 2. Does the API answer?
curl -s http://localhost:8000/health | jq .

# 3. Did the schema migration apply?
docker compose -f docker-compose.yaml logs app_migrations | tail -5
kubectl logs -n agentarea -l app.kubernetes.io/component=migration | tail -5

# 4. Is the worker connected to Temporal?
docker compose -f docker-compose.yaml logs agentarea-worker | tail -20
kubectl logs -n agentarea -l app.kubernetes.io/component=worker | tail -20
```

Under Compose, `postgres_init`, `app_migrations`, `kratos-migrate`, and
`rclone-init` are one-shot. `Exited (0)` is success. Any other code is the
failure, and the services that depend on them will not have started.

### 2. Read the logs as structured data

Every Python service emits one JSON object per line, so filter on fields:

```bash
kubectl logs -n agentarea -l app.kubernetes.io/component=backend \
  | jq -c 'select(.level == "ERROR") | {logger, message, exception}'
```

Tracebacks are in the `exception` field with newlines escaped, so a failure is
one line, not fifty. See [observability](/self-host/observability) for the full
field list.

### 3. The stack will not start

**Compose aborts before creating any container.** A required variable is empty.
`SANDBOX_ACTIVATION_AUTH_SECRET` and `SANDBOX_CLEANUP_AUTH_SECRET` are declared
`${VAR:?message}`, so Compose refuses rather than starting an unauthenticated
sandbox path. Set both in `.env`, at least 32 bytes each.

**Port already allocated.** Find the holder and stop it, or change the published
port.

```bash
lsof -i :8000 -i :3000 -i :7999 -i :4433
```

**The `db` container will not start after pulling a newer checkout.**
`postgres:18` stores data under `/var/lib/postgresql/<version>/docker`, so the
Compose file mounts `./data/postgres` at `/var/lib/postgresql`, not the legacy
`/var/lib/postgresql/data`. A data directory laid out for the old mount point
will not start.

**The API container restarts in a loop.** Read the first error, not the last:

```bash
docker compose -f docker-compose.yaml logs app | head -50
```

`SECRET_MANAGER_ENCRYPTION_KEY environment variable must be set` is the most
common. `SecretManagerFactory` validates its configuration at construction, so
the process exits at startup instead of failing later on the first secret read.

**Pods stay `Pending`.**

```bash
kubectl describe pod -n agentarea <pod> | tail -20
```

`FailedScheduling` naming a RuntimeClass means `mcpManager.runtimeClass` points
at one the cluster does not have. Unschedulable PVCs mean no default
StorageClass.

**The migration Job sits in `Init:0/1`.** Its `wait-for-db` init container polls
`nc -z <host> <port>` with no timeout, printing `Waiting for database...`. Check
that `global.database.host` resolves from inside the namespace.

### 4. The database or migrations are wrong

Confirm connectivity first, from the pod that fails:

```bash
docker compose -f docker-compose.yaml exec db pg_isready -U "$POSTGRES_USER"
docker compose -f docker-compose.yaml exec db \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT 1;"
```

Then the schema state:

```bash
docker compose -f docker-compose.yaml exec -w /app/apps/api app alembic current
docker compose -f docker-compose.yaml exec -w /app/apps/api app alembic heads
```

Mismatched output means migrations have not fully applied. Migrations must run
from `/app/apps/api` — `alembic.ini` uses a relative `script_location`, so
running from the repository root fails with a missing-`script_location` error.

For `relation already exists`, `Can't locate revision`, and multiple heads, see
[database and migrations](/self-host/database-and-migrations).

### 5. Nobody can log in

Authentication spans Kratos, the frontend, and the backend, and the failure is
usually a URL mismatch rather than a broken service.

```bash
kubectl get configmap -n agentarea agentarea-env-frontend \
  -o jsonpath='{.data.ORY_SDK_URL}{"\n"}{.data.ORY_BROWSER_URL}{"\n"}'
```

| Symptom | Cause |
|---|---|
| Redirected to `localhost:4433` in production | `kratos.urls.public` unset, so the internal service URL was used |
| Login succeeds, next request is anonymous | `kratos.session.cookieDomain` still `localhost` |
| CORS error in the browser console | `kratos.config.serve.public.cors.allowed_origins` still points at the shipped staging domain |
| Token rejected with a signature error | `KRATOS_JWKS_B64` differs between Kratos and the API |

`ORY_SDK_URL` is for server-side calls from the frontend container;
`ORY_BROWSER_URL` is where the browser goes. They are allowed to differ, and
must, when pods cannot resolve the public domain. See
[networking](/self-host/networking).

### 6. Tasks are created but never run

Task execution is a Temporal workflow, so check the worker and Temporal, not the
API.

```bash
kubectl logs -n agentarea -l app.kubernetes.io/component=worker --tail=50
```

The worker and the API must agree on all three Temporal values —
`WORKFLOW__TEMPORAL_SERVER_URL`, `WORKFLOW__TEMPORAL_NAMESPACE`, and
`WORKFLOW__TEMPORAL_TASK_QUEUE`. A worker polling a different task queue than the
API submits to produces exactly this symptom, with no error on either side.

Under Compose, `temporal` has a 120-second health-check start period and the
worker waits for it. First start is slow; that is not a fault.

Open the Temporal UI to see whether the workflow was started at all, and where it
stopped:

```bash
kubectl port-forward -n agentarea svc/agentarea-temporal-ui 8080:8080
```

If the workflow does not appear, the API never submitted it. If it appears and
fails, the history shows which activity and why.

### 7. Tool calls or MCP servers fail

```bash
curl -s http://localhost:7999/health
kubectl logs -n agentarea -l app.kubernetes.io/component=mcp-manager --tail=50
```

**Instances are created but unreachable.** With `mcpManager.backend: kubernetes`
and the `gateway_api` feature on, the manager creates HTTPRoutes against
`mcpManager.gateway`. Absent Gateway API CRDs or Gateway means nothing programs
them.

**Instances start and immediately go idle.** With
`mcpManager.serverless.enabled`, `MCP_IDLE_TIMEOUT` reclaims uncalled instances.
Both the API and the worker must have `MCP_LAZY_PROVISIONING_ENABLED` set to the
same value — the worker dispatches agent tool calls, so without it a reclaimed
instance is never brought back for agents.

**An MCP server cannot reach its upstream.** The instance egress NetworkPolicy
denies all cluster-internal and link-local ranges. An upstream inside the
cluster is blocked by design; add it to
`mcpManager.instanceNetworkPolicy.extraEgress`.

### 8. File uploads or artifacts fail

Presigned URLs are the usual cause, and the error surfaces in the browser rather
than in any server log.

```bash
kubectl get configmap -n agentarea agentarea-env-backend \
  -o jsonpath='{.data.PUBLIC_S3_ENDPOINT}{"\n"}'
```

Empty means presigned URLs point at the in-cluster object store address, which
the browser cannot resolve. Set `global.storage.publicEndpoint`. A CORS
rejection after that means `global.storage.cors.allowedOrigins` was empty at
bootstrap, which skips applying a rule entirely.

## Verify

After any fix, confirm the whole path rather than the symptom:

```bash
# containers and jobs
kubectl get pods,jobs -n agentarea

# API
curl -s http://localhost:8000/health | jq .

# schema at head
kubectl exec -n agentarea deploy/agentarea-backend -- \
  sh -c 'cd /app/apps/api && alembic current && alembic heads'

# no errors in the last minute
kubectl logs -n agentarea -l app.kubernetes.io/instance=agentarea \
  --all-containers=true --since=1m | jq -c 'select(.level=="ERROR")'
```

Then run one task end to end and confirm it reaches a terminal state. That is
the only check that exercises the API, the worker, Temporal, the MCP Manager,
and object storage together.

## Troubleshooting

Failures that look like one problem and are another:

**Everything is healthy and every action is denied.** OpenFGA has no
authorization data — a fresh store after a restore, or a bootstrap that did not
run. The authorization reader fails closed, so a working platform where nothing
is permitted looks like a permissions bug rather than a missing database.

**`helm upgrade` succeeded and the platform runs the old version.** The
migration Job is a normal resource, not a Helm hook, so it does not gate the
rollout. Check the Job separately. See [upgrades](/self-host/upgrades).

**Logs are plain text instead of JSON.** Something called `logging.basicConfig`
after `setup_logging`, replacing the handler that carries the formatter and the
redaction filters. This is a logging defect and a secret-leak risk, not a
cosmetic one.

**A Prometheus scrape returns 404.** Expected. No AgentArea service exposes
`/metrics`, despite the chart rendering `METRICS_ENABLED`. See
[observability](/self-host/observability).

**Provider icons are broken and OAuth callbacks fail.** Both are served from
`API_BASE_URL`. When `global.api.publicUrl` is empty the chart derives it from
the backend ingress host, assuming `https`, and falls back to a ClusterIP URL if
ingress is off.

**Stored credentials fail with `InvalidToken`.**
`SECRET_MANAGER_ENCRYPTION_KEY` no longer matches the ciphertext in
`encrypted_secrets`. There is no recovery path without the original key. See
[secrets backends](/self-host/secrets-backends).

## Related

- [Deploy with Docker Compose](/self-host/docker-compose)
- [Deploy on Kubernetes with Helm](/self-host/kubernetes)
- [Run database migrations](/self-host/database-and-migrations)
- [Collect logs and traces](/self-host/observability)
- [Configure networking and ingress](/self-host/networking)
