# AGENTS.md

**Generated:** 2026-03-02

Go MCP server orchestration with warm pool acceleration.

## WHERE TO LOOK

| Task | Location |
|------|----------|
| API handlers | internal/api/handlers.go |
| Backend implementations | internal/backends/ |
| Warm pool logic | internal/warmpool/ |
| Container management | internal/container/manager.go |
| Proxy routing | internal/proxy/ |
| Main entry point | cmd/mcp-manager/main.go |
| Activation service | cmd/activation-service/main.go |

## STRUCTURE

```
agentarea-mcp-manager/
├── cmd/
│   ├── mcp-manager/       # Main API service
│   └── activation-service/ # Warm pool activation
├── internal/
│   ├── api/               # HTTP handlers
│   ├── backends/          # Kubernetes, Docker backends
│   ├── container/         # Container lifecycle
│   ├── features/          # Feature flags
│   ├── warmpool/          # Warm pool client
│   ├── proxy/             # Request proxying
│   └── config/            # Configuration
└── build/                 # Dockerfiles
```

## KEY PATTERNS

**Warm Pool Activation Flow:**
```
Request → Find Warm Pod → Assign → Activate → Route Ready
  0ms       ~100ms       ~150ms    ~1200ms    ~1300ms
```

**Feature Flags:** `MCP_FEATURES_ENABLED=warm_pool,gateway_api,state_reconciler`

**Backends:** Kubernetes (Gateway API/Ingress), Docker (dev)

## CONVENTIONS

- Implement `Backend` interface in `internal/backends/`
- Handlers in `internal/api/handlers.go`
- Config via environment variables in `internal/config/`
- Structured logging with logrus

## ANTI-PATTERNS

- Never expose Docker socket
- Warm pool pods run privileged (chroot required)
- `container.Manager` methods not thread-safe

## COMMANDS

```bash
go build ./...              # Build all
go test ./...               # Test all
golangci-lint run           # Lint
docker build -t agentarea/mcp-manager:latest .
```

## API

```bash
# Create instance
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

## CONFIGURATION

| Variable | Default |
|----------|---------|
| `BACKEND_TYPE` | kubernetes |
| `KUBERNETES_NAMESPACE` | agentarea |
| `WARM_POOL_ENABLED` | false |
| `WARM_POOL_SIZE` | 10 |
| `MCP_FEATURES_ENABLED` | gateway_api,state_reconciler |
