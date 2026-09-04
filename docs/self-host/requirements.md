---
title: Requirements
type: reference
summary: Host, cluster, and dependency versions required to run AgentArea, per deployment target.
prerequisites: []
related:
  - /self-host/docker-compose
  - /self-host/kubernetes
  - /self-host/configuration
  - /self-host/networking
last_updated: 2026-07-29
---

# Requirements

What a host or cluster must provide before AgentArea starts.

## Synopsis

AgentArea ships two supported deployment targets:

| Target | Entry point | Source of truth |
|---|---|---|
| Docker Compose | `docker-compose.yaml` at the repo root | `docker-compose.yaml` |
| Kubernetes | the `agentarea` Helm chart | `charts/agentarea/values.yaml` |

`docker-compose.dev.yaml` is a third file used for development. It starts the
same platform plus Traefik, Temporal UI, Keto, OpenFGA, Hydra, and Mailpit, and
it bind-mounts source into the containers. It is not a deployment target.

## Parameters

### Docker Compose host

| Requirement | Value | Notes |
|---|---|---|
| Docker Engine | 20.10 or later | Compose file uses `depends_on.condition`, which needs Compose v2 |
| Docker Compose | v2 (`docker compose`, not `docker-compose`) | The Makefile targets call `docker compose` |
| Architecture | linux/amd64 or linux/arm64 | Images are published for both |
| Ports | 3000, 4433, 5432, 6379, 7999, 8000, 9000 | See the port table below |

The compose stack starts 14 containers, three of which are one-shot init jobs
(`postgres_init`, `app_migrations`, `kratos-migrate`, `rclone-init`). No sizing
figure has been measured for this repo, so none is published here.

### Kubernetes cluster

| Requirement | Value | Required when |
|---|---|---|
| Kubernetes | any version supporting `batch/v1` Jobs and `networking.k8s.io/v1` NetworkPolicy | Always |
| Helm | v3 | Always |
| Default StorageClass | must exist and support `ReadWriteOnce` | `postgresql.enabled=true` or `rustfs.enabled=true` |
| Gateway API CRDs + a Gateway | `mcpManager.gateway.name` in `mcpManager.gateway.namespace`, default `envoy-gateway` in `envoy-gateway-system` | `mcpManager.backend=kubernetes` and `gateway_api` is in `mcpManager.features.enabled` |
| CNI that enforces NetworkPolicy | for example Cilium or Calico | `mcpManager.instanceNetworkPolicy.enabled=true` (the default) |
| RuntimeClass | named by `mcpManager.runtimeClass` | Set to anything other than `""` |
| Ingress controller | matching `ingress.className` | `ingress.enabled=true` |

`mcpManager.instanceNetworkPolicy` is a no-op on a cluster whose CNI does not
enforce NetworkPolicy. The chart does not detect this, so untrusted MCP instance
pods reach the cluster network and the cloud metadata endpoint unimpeded. See
[networking](/self-host/networking).

`mcpManager.runtimeClass` defaults to `""`, which is the node's default runtime
(runc) and provides no kernel isolation for code the platform did not write.
`gvisor` needs runsc and its containerd shim on the nodes; `kata-qemu` needs KVM,
which managed clusters on virtualized nodes rarely expose. Kubernetes refuses to
schedule the pod if the named RuntimeClass does not exist.

### Bundled dependencies

The chart bundles these and can run them in-cluster. Disable each one and point
the corresponding `global.*` key at a managed service instead.

| Dependency | Image and tag | Chart key | Default |
|---|---|---|---|
| PostgreSQL | `postgres:16-alpine` | `postgresql.enabled` | `true` |
| Valkey (Redis-compatible) | `valkey` subchart 0.9.3 from `https://valkey.io/valkey-helm/` | `redis.enabled` | `true` |
| RustFS (S3-compatible object store) | `rustfs/rustfs:latest` | `rustfs.enabled` | `true` |
| Temporal | `temporalio/auto-setup:1.29.1` | `temporal.enabled` | `true` |
| Temporal UI | `temporalio/ui:2.39.0` | `temporalUi.enabled` | `true` |
| Ory Kratos | `oryd/kratos:v1.3.1` | `kratos.enabled` | `true` |
| OpenFGA | `openfga/openfga:v1.18.0` | `openfga.enabled` | `true` |
| Ory Keto | `oryd/keto:v0.12.0` | `keto.enabled` | `false` |

The bundled PostgreSQL is a single StatefulSet with no replication and no backup.
`charts/agentarea/values.yaml` marks it "not for production". For anything you
care about, set `postgresql.enabled=false` and point `global.database.host` at a
managed instance.

The Compose stack pins `postgres:18` and `valkey/valkey:8`. The chart pins
`postgres:16-alpine`. The two targets are not on the same PostgreSQL major.

### Databases

One PostgreSQL instance, several logical databases. Compose creates them in
`postgres_init`; the chart creates each in a dedicated Job.

| Database | Created by | Required when |
|---|---|---|
| `agentarea` (`global.database.name`) | `postgres_init` / `db-migration` job | Always |
| `temporal` (`temporal.database.name`) | `postgres_init` / `create-temporal-db-job` | `temporal.enabled=true` |
| `kratos` (`kratos.database.name`) | `postgres_init` / `create-kratos-db-job` | `kratos.enabled=true` |
| `openfga` (`openfga.database.name`) | `create-openfga-db-job` | `openfga.enabled=true` |
| `keto` (`keto.database.name`) | `create-keto-db-job` | `keto.enabled=true` |

### Service ports

| Service | Compose | Chart service port |
|---|---|---|
| Backend API | 8000 | 8000 |
| Frontend | 3000 | 3000 |
| MCP Manager | 7999 (host) to 80 (container) | 80 |
| Event service | not published | 8002 |
| Temporal | 7233 | 7233 |
| Temporal UI | 8080 (dev only) | 8080 |
| PostgreSQL | 5432 | 5432 |
| Valkey | 6379 | 6379 |
| RustFS | 9000 | 9000 |
| Kratos public | 4433 | 4433 |
| Kratos admin | not published | 4434 |
| OpenFGA | HTTP 8080, gRPC 8081, metrics 2112 | same |
| Keto | read 4466, write 4467, metrics 4468 | same |

### Building from source

Only needed if you build images yourself rather than pulling published ones.

| Toolchain | Version | Where |
|---|---|---|
| Python | 3.12 or later, with `uv` | `agentarea-platform/` |
| Go | 1.25.0 | `agentarea-mcp-manager/` |
| Node.js with npm | version not pinned in `agentarea-webapp/package.json` | `agentarea-webapp/` |

## Errors

| Symptom | Meaning | Action |
|---|---|---|
| `db-migration` job stuck in `Init:0/1` | The `wait-for-db` init container is polling a database host that never becomes reachable | Check `global.database.host`, or that the bundled `postgresql` StatefulSet is running |
| Pod stuck in `Pending` with `FailedScheduling: RuntimeClass ... not found` | `mcpManager.runtimeClass` names a RuntimeClass the cluster does not have | Install the runtime and its RuntimeClass, or set `runtimeClass: ""` and accept no kernel isolation |
| MCP instances created but unreachable over HTTP | Gateway API CRDs or the named Gateway are missing | Install Envoy Gateway, or set `mcpManager.gateway.*` to your Gateway |
| PVCs stuck in `Pending` | No default StorageClass | Set `postgresql.persistence.storageClass` and `rustfs.persistence.*`, or disable both and use managed services |
| API exits at startup with `SECRET_MANAGER_ENCRYPTION_KEY environment variable must be set` | The default `database` secret backend has no key | See [secrets backends](/self-host/secrets-backends) |

## Example

A cluster that meets the minimum for a Kubernetes install with everything
bundled:

```bash
kubectl get storageclass                 # at least one, marked (default)
kubectl get crd | grep gateway.networking.k8s.io
kubectl get gateway -n envoy-gateway-system
kubectl get runtimeclass
helm version --short                     # v3.x
```

## Related

- [Deploy with Docker Compose](/self-host/docker-compose)
- [Deploy on Kubernetes with Helm](/self-host/kubernetes)
- [Configuration](/self-host/configuration)
- [Configure networking and ingress](/self-host/networking)
