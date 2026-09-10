# MCP Runtime

Fast, secure runtime for Model Context Protocol (MCP) servers with warm pool acceleration.

## Features

- **Fast Cold Start**: ~1.3s activation via warm pools (vs 8-15s standard)
- **Kubernetes Native**: Gateway API and Ingress support
- **Feature Flags**: Gradual rollout with pluggable providers
- **Flexible Routing**: Automatic fallback from Gateway API to Ingress
- **Container Sandboxing**: Secure execution with proper isolation

## Quick Start

```bash
# Build images
docker build -t agentarea/mcp-manager:latest .
docker build -f build/Dockerfile.runner -t agentarea/mcp-runner:latest .

# Deploy with Helm
helm upgrade agentarea charts/agentarea -n agentarea \
  --set mcpManager.warmPool.enabled=true \
  --set mcpManager.features.enabled={warm_pool,gateway_api,state_reconciler}
```

## Architecture

### Warm Pool Fast Activation

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│   Request   │────▶│  Find Warm   │────▶│    Activate     │
│   (0ms)     │     │   Pod (0.1s) │     │  (1.3s total)   │
└─────────────┘     └──────────────┘     └─────────────────┘
                                                    │
                       ┌──────────────┐            │
                       │  Download    │◀───────────┤
                       │  Image       │            │
                       └──────────────┘            │
                                                    │
                       ┌──────────────┐            │
                       │  Extract &   │◀───────────┤
                       │  Start       │            │
                       └──────────────┘            │
                                                    ▼
                                            ┌──────────────┐
                                            │   Running    │
                                            │   MCP Server │
                                            └──────────────┘
```

### Components

1. **MCP Manager** (`cmd/mcp-manager/`)
   - REST API for instance management
   - Kubernetes backend with warm pool integration
   - Feature flag system

2. **Activation Service** (`cmd/activation-service/`)
   - Runs in warm pool pods
   - Downloads and activates MCP images
   - Parses ENTRYPOINT/CMD from docker config

## API

**Create Instance:**
```bash
curl -X POST http://localhost:80/instances \
  -H "Content-Type: application/json" \
  -d '{
    "instance_id": "my-mcp",
    "name": "My MCP",
    "service_name": "my-mcp-svc", 
    "image": "nginx:alpine",
    "port": 80,
    "workspace_id": "ws-123"
  }'
```

**Response:**
```json
{
  "id": "uuid",
  "name": "My MCP",
  "url": "https://mcp.local/mcp/my-mcp",
  "status": "running"
}
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `AGENTAREA_MCP_FEATURES` | Comma-separated feature flags | `gateway_api,state_reconciler` |
| `WARM_POOL_ENABLED` | Enable warm pool fast start | `false` |
| `AGENTAREA_K8S_GATEWAY` | Gateway API gateway name | `envoy-gateway` |

## Raw usage tracking

Usage is recorded independently of pricing, credits, wallets, and payments.
The manager requires the platform migration
`20260918_1200_resource_usage` before startup:

```bash
# From agentarea-platform/apps/api, with the deployment's database environment.
uv run alembic upgrade head
```

The append-only `resource_usage_events` table in PostgreSQL is the source of
truth. Replaying the same `(source, event_id)` is idempotent; different content
under that identity is rejected. Events remain after the runtime is removed.
Schema version `1` is required.

| Source | Recorded facts | Timing |
|--------|----------------|--------|
| MCP gateway | HTTP request start/end, status, integer duration in nanoseconds, lifecycle generation | Per request/transition |
| Native runtime | Physical container ID or pod UID, requests, limits, available CPU/RAM measurements | Every minute; also at MCP activation and before deletion |
| Sandbox runtime | Provisioning bounds, allocation profile, lease renewal, delete request/result, confirmed absence | At lifecycle boundaries |
| Artifact publication | Stored bytes, object version, source storage timestamp | On publication |
| Storage inventory | Current bytes, retained versions/bytes, delete markers; content and metadata separated | Every five minutes |

Docker reports cumulative CPU nanoseconds and memory `usage` bytes. CPU quota
and period remain available as an exact ratio when integer nanocores cannot
represent the limit. Kubernetes reports CPU nanocores over the metrics API's
window and memory working-set bytes. These are different measurements, not
interchangeable billing quantities. Kubernetes metrics permissions are
namespace-scoped `get`/`list` on `metrics.k8s.io/pods`.

External sandbox providers preserve allocation metadata with its provenance;
they do not expose actual CPU/RAM telemetry through this integration. Missing
measurements are explicitly unavailable, never zero. Provider-reported start
times and control-plane observations are distinguished. An opaque SDK failure
retains the provisioning attempt without inventing a physical allocation.
Lease expiry and deletion acceptance are not proof of physical termination.
Shared executors and unassigned pools remain platform usage, not duplicated
per task.

Storage inventory requires `ListObjectVersions` permission for the configured
bucket/prefix, including for unversioned buckets. An incomplete scan emits no
zero observations. Previously published/scanned scopes are recovered from
PostgreSQL even after Redis replacement. A complete empty observation closes a
scope once; later empty scans do not create more facts unless a new publication
or inventory makes it active again. Object/version/delete-marker counts keep
zero-byte scopes active. Polling is not an exact byte-time integral, and
provider timestamps retain their original precision.
The pre-inventory snapshot includes each scope's latest durable sequence.
A synthesized zero is inserted only if that sequence is still current. The
comparison and insert share a per-scope transaction lock with storage
publications and samples; a newer fact makes the collector discard the stale
zero. Other storage scopes remain independently writable.

The manager records local lifecycle facts directly in PostgreSQL. Standalone
sandbox runners publish to Redis stream `agentarea:usage:events`; the manager's
`usage-persistence` consumer persists the event before returning an
acknowledgement tied to its complete payload and removing the stream entry.
Runner publication succeeds only after that PostgreSQL commit acknowledgement,
not after `XADD`. It waits at most ten seconds, respects earlier cancellation,
and returns an error when persistence cannot be confirmed. Lifecycle callers
therefore require the persistence consumer and database to be available.
Configure persistent Redis storage and no eviction for pending entries; a
timeout does not prove that an event was never committed, so retry the same
immutable event. Provider operations and event persistence are not a distributed
transaction; incomplete observations and delivery errors must not be treated
as complete billing records.

Read workspace-scoped history through the platform API:
`GET /v1/usage/events`. Filters include `source`, `kind`, `resource_kind`,
`resource_id`, `task_id`, `from`, and `until`; the default page size is 50,
maximum 100. Pass `next_cursor` unchanged as the next request's string
`cursor`. Time bounds accept RFC3339 with up to nine fractional digits.
`occurred_at` preserves source nanoseconds. `data_json` is JSON **text** so
JavaScript's outer response parser cannot round 64-bit counters; use an
integer-preserving parser when decoding it. There is no public ingestion or
charging endpoint.

## Documentation

- [CLAUDE.md](CLAUDE.md) - Developer guide
- [docs/KATA_WARM_POOL.md](docs/KATA_WARM_POOL.md) - Warm pool design
- [docs/STATE_SYNC_ARCHITECTURE.md](docs/STATE_SYNC_ARCHITECTURE.md) - State reconciliation

## License

Licensed under the Apache License 2.0 — see [LICENSE.md](../LICENSE.md) for details.
