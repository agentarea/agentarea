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
| `MCP_FEATURES_ENABLED` | Comma-separated feature flags | `gateway_api,state_reconciler` |
| `WARM_POOL_ENABLED` | Enable warm pool fast start | `false` |
| `KUBERNETES_GATEWAY_NAME` | Gateway API gateway name | `envoy-gateway` |

## Documentation

- [CLAUDE.md](CLAUDE.md) - Developer guide
- [docs/KATA_WARM_POOL.md](docs/KATA_WARM_POOL.md) - Warm pool design
- [docs/STATE_SYNC_ARCHITECTURE.md](docs/STATE_SYNC_ARCHITECTURE.md) - State reconciliation

## License

MIT
