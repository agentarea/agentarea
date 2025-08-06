# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Go MCP Manager (from go-mcp-manager/ directory)

**Build and run:**
- `go build -o bin/mcp-manager ./cmd/mcp-manager` - Build the Go binary
- `go run ./cmd/mcp-manager` - Run directly from source
- `go test ./...` - Run all tests
- `go mod tidy` - Clean up dependencies

**Docker commands:**
- `docker build -t mcp-manager:latest .` - Build Docker image
- `docker run -p 8000:8000 mcp-manager:latest` - Run containerized

### Infrastructure Management (from project root)

**Quick start:**
- `./scripts/start.sh` - Start full infrastructure (Traefik + MCP Manager)
- `./scripts/stop.sh` - Stop all services
- `./scripts/test-mcp.sh` - Test MCP Manager API
- `./scripts/test-echo.sh` - Test echo service example

**Docker Compose:**
- `docker-compose up -d` - Start infrastructure
- `docker-compose down` - Stop and remove containers
- `docker-compose logs -f mcp-manager` - View MCP Manager logs

### API Testing

**Health and status:**
- `curl http://localhost:8000/health` - Check MCP Manager health
- `curl http://localhost:8000/containers` - List managed containers

**Container management:**
- `curl -X POST http://localhost:8000/containers -H "Content-Type: application/json" -d '{"service_name": "test", "template": "echo"}'` - Create container from template
- `curl -X DELETE http://localhost:8000/containers/test` - Delete container

## Architecture Overview

The MCP Infrastructure is a Go-based container orchestration system designed for running Model Context Protocol (MCP) services securely.

### Core Components

**go-mcp-manager/** - Main Go application:
- `cmd/mcp-manager/main.go` - Application entry point with graceful shutdown
- `internal/api/` - HTTP API handlers for container management
- `internal/container/` - Container lifecycle management with Podman
- `internal/config/` - Environment-based configuration system
- `internal/providers/` - Docker and URL provider implementations
- `internal/events/` - Redis-based event publishing/subscribing
- `internal/secrets/` - Infisical SDK integration for secret management

**traefik/** - Reverse proxy configuration:
- `traefik.yml` - Static configuration for load balancing
- `dynamic.yml` - Dynamic routing rules for MCP services

**scripts/** - Infrastructure management utilities:
- Shell scripts for starting, stopping, and testing the infrastructure

### Key Architecture Patterns

**Environment-Aware Backend Selection:**
- Automatically detects Docker Compose vs Kubernetes environments
- Uses Podman + Traefik for development (Docker Compose)
- Uses native K8s resources for production (Kubernetes)

**Security-First Container Management:**
- **Podman-in-Docker** instead of Docker-in-Docker eliminates Docker socket exposure risks
- **Rootless containers** by default with proper user namespace separation  
- **Single privileged container** manages child containers safely
- **Resource limits** enforced per container (memory, CPU)

**Event-Driven Integration:**
- Redis-based event system for integration with core AgentArea platform
- Publishes container lifecycle events (created, started, stopped, failed)
- Subscribes to MCP server instance events from core system

**REST API Design:**
- RESTful HTTP API for container lifecycle management
- Template-based container creation with environment-specific configurations
- Health checks and monitoring endpoints
- Consistent API across Docker Compose and Kubernetes backends

### Container Runtime

**Podman Integration:**
- Uses Podman as container runtime instead of Docker for security
- Configured with overlay storage driver and custom storage paths
- Supports rootless operation with proper subuid/subgid mapping
- Integrated with Traefik for automatic service discovery and routing

**Template System:**
- JSON-based templates define container configurations
- Support for environment variables, volumes, resource limits
- Pre-built templates for common MCP server types
- Extensible template system for custom MCP implementations

### Configuration Management

**Environment Variables:**
All configuration via environment variables with sensible defaults:

- **Server**: `SERVER_HOST`, `SERVER_PORT`, `CORS_ENABLED`
- **Container**: `CONTAINER_RUNTIME`, `MAX_CONTAINERS`, `DEFAULT_MEMORY_LIMIT`
- **Traefik**: `TRAEFIK_NETWORK`, `DEFAULT_DOMAIN`, `PROXY_PORT`
- **Logging**: `LOG_LEVEL`, `LOG_FORMAT`
- **Redis**: `REDIS_URL` for event integration
- **Secrets**: Infisical configuration for secret management

**Security Configuration:**
- CORS disabled by default, configurable origins
- Resource limits with container quotas
- Network isolation with dedicated container networks
- Optional authentication middleware support

## Testing

**Test Scripts:**
- `scripts/test-mcp.sh` - Complete MCP Manager API testing
- `scripts/test-echo.sh` - Echo service deployment and testing
- Go unit tests with `go test ./...`

**Integration Testing:**
- Real container lifecycle testing with Podman
- Traefik integration with dynamic routing
- Redis event publishing/subscribing
- Health check and monitoring validation

**Test Environment:**
- Requires Docker/Docker Compose for infrastructure
- Uses localhost endpoints for API testing
- Includes cleanup procedures for test containers

## Deployment

**Docker Compose (Development):**
```yaml
# Uses Podman + Traefik stack
# Mounts templates and dynamic configuration
# Exposes ports 80 (Traefik), 8000 (MCP Manager), 8080 (Traefik Dashboard)
```

**Kubernetes (Production):**
- Native K8s Deployments and Services
- Ingress for external access
- ConfigMaps for template storage
- RBAC for secure cluster access

**Security Considerations:**
- No Docker socket mounting required
- Runs with minimal privileges where possible
- Network policies for pod communication
- Secret management via Infisical integration