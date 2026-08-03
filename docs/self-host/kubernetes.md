---
title: Deploy on Kubernetes with Helm
type: guide
summary: Install the agentarea Helm chart, decide which bundled dependencies to keep, and confirm the install completed.
prerequisites:
  - /self-host/requirements
related:
  - /self-host/configuration
  - /self-host/networking
  - /self-host/secrets-backends
  - /self-host/database-and-migrations
  - /self-host/upgrades
last_updated: 2026-07-29
---

# Deploy on Kubernetes with Helm

Install AgentArea with the `agentarea` chart. Choose Kubernetes over
[Docker Compose](/self-host/docker-compose) when you need more than one replica
of a service, rolling updates, or kernel isolation for the code agents run — the
`mcpManager.runtimeClass` setting only exists on this target.

The chart bundles PostgreSQL, Valkey, RustFS, Temporal, Kratos, and OpenFGA so a
default install works on an empty cluster. The bundled PostgreSQL is a single
StatefulSet with no replication and no backup, and the chart's own values file
marks it as not for production. Decide which dependencies to externalize before
you install, not after.

## Prerequisites

- Kubernetes with `batch/v1` Jobs and `networking.k8s.io/v1` NetworkPolicy; the chart README states 1.20 or later
- Helm 3.8 or later
- A default StorageClass, if you keep the bundled PostgreSQL or RustFS
- Gateway API CRDs and a Gateway, if you keep `gateway_api` in `mcpManager.features.enabled`
- See [requirements](/self-host/requirements) for the full matrix

## Steps

### 1. Add the chart repository

```bash
helm repo add agentarea https://agentarea.github.io/helm-charts
helm repo update
```

To install from a clone instead, run `helm dependency build charts/agentarea`
first — the Valkey subchart is a repository dependency and is not vendored.

### 2. Decide what the chart should bring with it

Set these in a `values.yaml` you keep under version control.

Keep everything bundled for an evaluation:

```yaml
# values.yaml — evaluation only
global:
  deploymentEnv: development
```

Externalize state for anything you intend to keep:

```yaml
# values.yaml — external PostgreSQL, Redis, and S3
postgresql:
  enabled: false
redis:
  enabled: false
rustfs:
  enabled: false

global:
  database:
    host: postgres.internal.example.com
    port: 5432
    name: agentarea
    sslMode: require
  redis:
    existingSecret: agentarea-redis-url    # key `url`, holds the full REDIS_URL
  storage:
    type: s3
    endpoint: https://s3.us-east-1.amazonaws.com
    publicEndpoint: https://s3.us-east-1.amazonaws.com
    bucket: agentarea-documents
    region: us-east-1
```

Disabling `postgresql` does not create the auxiliary databases for you. Temporal,
Kratos, and OpenFGA each need their own database on the external instance; the
chart's create-database Jobs run against `global.database.host` using the
credentials in `global.secrets.postgresql`, so that role needs `CREATEDB`.

`global.storage.publicEndpoint` matters as soon as the object store is not
reachable from the browser. The platform signs presigned URLs for direct
browser uploads and downloads; if this is empty it falls back to the internal
endpoint, and those URLs resolve to a cluster-only address.

### 3. Set the isolation boundary for untrusted code

`mcpManager.runtimeClass` governs both MCP server instance pods and agent sandbox
pods — one setting, so a sandbox can never end up less confined than an MCP
server. It defaults to `""`, the node's default runtime, which gives untrusted
code the host kernel.

```yaml
mcpManager:
  runtimeClass: gvisor          # requires runsc + containerd shim on the nodes
  instanceNetworkPolicy:
    enabled: true               # no-op unless your CNI enforces NetworkPolicy
```

`kata-qemu` is the alternative and needs KVM, which managed clusters on
virtualized nodes rarely expose. Kubernetes refuses to schedule the pod if the
named RuntimeClass does not exist in the cluster, which is the correct failure —
it is better than silently running on runc.

### 4. Install

```bash
helm install agentarea agentarea/agentarea \
  --namespace agentarea --create-namespace \
  -f values.yaml \
  --wait --timeout 15m
```

On install the chart generates the secrets that were not pre-created —
PostgreSQL, Redis, and RustFS credentials, the application encryption key, and
the two sandbox HMAC secrets — and annotates each with
`helm.sh/resource-policy: keep` so they survive `helm uninstall`. Subsequent
upgrades look the existing secrets up and reuse them rather than rotating them.
To supply your own instead, create the Secrets named in `global.secrets.*` before
installing; see [secrets backends](/self-host/secrets-backends).

The install runs Jobs in this order: create the auxiliary databases, run
`agentarea-api migrate` (the `db-migration` Job, working directory
`/app/apps/api`), then `agentarea-api reconcile` (the `registryReconcile` Job,
which seeds the LLM provider, LLM model, and MCP server catalogs from S3). The
migration Job has an init container that blocks on a TCP connection to the
database, so it sits in `Init:0/1` until PostgreSQL accepts connections.

### 5. Expose the platform

Ingress is off by default. Port-forward to check the install:

```bash
kubectl port-forward -n agentarea svc/agentarea-frontend 3000:3000
kubectl port-forward -n agentarea svc/agentarea-backend 8000:8000
```

For a real deployment, enable ingress and set the public URLs. See
[networking](/self-host/networking) — several settings besides `ingress.hosts`
have to agree, and getting only the Ingress right leaves authentication broken.

## Verify

Confirm every Job succeeded. A running Deployment with a failed migration Job is
a broken install that looks healthy.

```bash
kubectl get jobs -n agentarea
```

Each Job should show `Completions 1/1`. The migration Job has
`ttlSecondsAfterFinished: 300`, so it disappears five minutes after completing —
absence is not failure if the pods are up.

```bash
kubectl get pods -n agentarea
kubectl logs -n agentarea -l app.kubernetes.io/component=migration
```

The migration log ends in `Migrations completed successfully`, or
`Stamped database to head revision` if the schema already existed.

Check the API answers:

```bash
kubectl port-forward -n agentarea svc/agentarea-backend 8000:8000 &
curl -s http://localhost:8000/health
```

Confirm the catalogs seeded, otherwise the model picker in the UI is empty:

```bash
kubectl logs -n agentarea -l app.kubernetes.io/component=registry-reconcile
```

## Troubleshooting

**The `db-migration` Job stays in `Init:0/1`.** Its `wait-for-db` init container
loops on `nc -z <host> <port>` and prints `Waiting for database...` forever. The
host comes from `global.database.host`, or from the bundled PostgreSQL service
when that is empty. Check that the value resolves and that the port is open from
inside the namespace.

**Pods stay `Pending` with `FailedScheduling` naming a RuntimeClass.** The
cluster has no RuntimeClass matching `mcpManager.runtimeClass`. Install the
runtime and its RuntimeClass, or set it back to `""` and accept that untrusted
code shares the host kernel.

**PVCs stay `Pending`.** No default StorageClass. Set
`postgresql.persistence.storageClass` and `rustfs.persistence`, or disable both
components and use managed services.

**MCP server instances are created but nothing can reach them.** With
`mcpManager.backend: kubernetes` and the `gateway_api` feature enabled, the
manager creates HTTPRoutes attached to `mcpManager.gateway.name` in
`mcpManager.gateway.namespace` (default `envoy-gateway` in
`envoy-gateway-system`). If Gateway API CRDs or that Gateway are absent, the
routes are never programmed. Install Envoy Gateway or point the values at your
own Gateway.

**Browser uploads fail with a DNS or connection error on a presigned URL.**
`global.storage.publicEndpoint` is empty and the presigned URL points at the
in-cluster object store address. Set it to a URL the browser can resolve, and
set `global.storage.cors.allowedOrigins` to your frontend origin.

**The API pod crash-loops on `SECRET_MANAGER_ENCRYPTION_KEY`.** The
`agentarea-app-secrets` Secret is missing its `encryption-key` entry — usually
because a hand-created Secret replaced the generated one without that key.

## Related

- [Requirements](/self-host/requirements)
- [Configuration](/self-host/configuration)
- [Configure networking and ingress](/self-host/networking)
- [Run database migrations](/self-host/database-and-migrations)
- [Upgrade a deployment](/self-host/upgrades)
