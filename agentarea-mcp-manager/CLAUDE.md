# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

**MCP Runtime** (formerly mcp-manager) - A container orchestration system for running Model Context Protocol (MCP) servers with fast cold start via warm pools.

## Components

### 1. MCP Manager (`cmd/mcp-manager/`)
Main API service that manages MCP server lifecycle:
- REST API for instance CRUD operations
- Kubernetes backend with Gateway API/Ingress routing
- Feature flags for gradual rollout
- Warm pool integration for fast activation

### 2. Activation Service (`cmd/activation-service/`)
Runs inside warm pool pods to activate MCP images on demand:
- Downloads container images via Skopeo
- Extracts docker layers to rootfs
- Parses image ENTRYPOINT/CMD from config
- Supports user-provided entrypoint/command overrides
- Configurable health checks

## Development Commands

**Build:**
```bash
# Build MCP Manager
go build -o bin/mcp-manager ./cmd/mcp-manager

# Build Activation Service
go build -o bin/activation-service ./cmd/activation-service/...

# Build both
docker build -t agentarea/mcp-manager:latest .
docker build -f build/Dockerfile.runner -t agentarea/mcp-runner:latest .
```

**Test:**
```bash
go test ./...
go mod tidy
```

## Architecture

### Warm Pool Fast Start
```
Request → Find Warm Pod → Assign → Activate → Route Ready
  │            │            │         │          │
  0ms        ~100ms       ~150ms    ~1200ms    ~1300ms

Cold Start: 8-15s → Warm Pool: ~1.3s (~10x faster)
```

### Key Features

**Feature Flags** (`internal/features/`):
- `warm_pool` - Enable warm pool fast activation
- `gateway_api` - Use Gateway API HTTPRoute
- `state_reconciler` - Background state reconciliation
- Pluggable provider: config, env, or hybrid

**Backends** (`internal/backends/`):
- Kubernetes: Native Deployments/Services + Gateway API/Ingress
- Warm Pool: Pre-created pods with activation service
- Docker: Podman-based (development)

**Warm Pool** (`internal/warmpool/`):
- DaemonSet with pre-created activation pods
- Pod selection, assignment, and lifecycle management
- HTTP activation API

**Activation** (`cmd/activation-service/`):
- Skopeo for image download
- Docker layer extraction to rootfs
- Image config parsing (ENTRYPOINT/CMD)
- User override support
- Chroot execution with fallback

## Configuration

**Environment Variables:**
```bash
# Core
LOG_LEVEL=info
SERVER_PORT=80
BACKEND_TYPE=kubernetes

# Kubernetes
KUBERNETES_NAMESPACE=agentarea
KUBERNETES_DOMAIN=mcp.local
KUBERNETES_GATEWAY_NAME=envoy-gateway

# Feature Flags
MCP_FEATURES_ENABLED=warm_pool,gateway_api,state_reconciler

# Warm Pool
WARM_POOL_ENABLED=true
WARM_POOL_SIZE=10
```

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
    "workspace_id": "ws-123",
    "entrypoint": ["/docker-entrypoint.sh"],  // optional override
    "command": ["nginx", "-g", "daemon off;"]  // optional override
  }'
```

## Testing

**Manual Test:**
```bash
# Start infrastructure
docker-compose -f docker-compose.dev-infra.yaml up -d

# Deploy warm pool DaemonSet
kubectl apply -f charts/agentarea/templates/warm-pool/

# Test instance creation
curl -X POST http://localhost:8080/instances \
  -d '{"instance_id":"test","name":"Test","service_name":"test-svc","image":"nginx:alpine","port":80,"workspace_id":"test"}'
```

## Deployment

**Images:**
- `agentarea/mcp-manager:latest` - Main API service
- `agentarea/mcp-runner:latest` - Activation service (warm pool pods)

**Helm:**
```bash
helm upgrade agentarea charts/agentarea -n agentarea \
  --set mcpManager.warmPool.enabled=true \
  --set mcpManager.features.enabled={warm_pool,gateway_api}
```

## File Structure

```
agentarea-mcp-manager/
├── cmd/
│   ├── mcp-manager/        # Main API service
│   └── activation-service/ # Warm pool activation
├── internal/
│   ├── api/               # HTTP handlers
│   ├── backends/          # K8s, Docker backends
│   ├── features/          # Feature flag system
│   ├── warmpool/          # Warm pool client
│   └── ...
├── build/
│   └── Dockerfile.runner  # Activation service image
├── docs/                  # Implementation docs
├── archive/design/        # Design decision docs
└── api/                   # OpenAPI specs
```

## Security

- RBAC for Kubernetes resources (including Ingress)
- Warm pool pods run privileged (for chroot)
- No Docker socket exposure
- Image caching for fast activation
