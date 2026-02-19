# MCP Manager - Go Service

A Go-based MCP (Model Context Protocol) server manager that handles Docker containers and URL-based MCP servers.

## Development Setup

### Live Reload Development

The development environment uses [Air](https://github.com/air-verse/air) for live reloading, which automatically rebuilds and restarts the service when you make code changes.

**Start development environment:**
```bash
# From project root
docker-compose -f docker-compose.dev.yaml up mcp-manager -d
```

**Watch logs:**
```bash
docker-compose -f docker-compose.dev.yaml logs mcp-manager -f
```

**Key features:**
- ✅ **Live reload**: Code changes trigger automatic rebuild and restart
- ✅ **Volume mounting**: Source code is mounted for real-time changes
- ✅ **Fast iteration**: No need to rebuild Docker images for code changes
- ✅ **Full debugging**: All Go tools available in development container

### Production Build

For production deployments, use the optimized build:

```bash
# Build production image
docker-compose -f docker-compose.prod.yaml build mcp-manager

# Run production
docker-compose -f docker-compose.prod.yaml up mcp-manager -d
```

## Architecture

- **Event-driven**: Listens to Redis pub/sub for MCP server lifecycle events
- **Multi-provider**: Supports Docker containers and URL-based MCP servers
- **Secret resolution**: Integrates with Python API for secret management
- **Container management**: Uses Podman for secure container operations
- **Handwritten proxy**: Built-in Go HTTP reverse proxy for MCP routing (no external dependencies)

## API Endpoints

- `GET /health` - Health check with service status
- `GET /containers` - List managed containers
- `POST /containers` - Create new container (via events)
- `DELETE /containers/{id}` - Remove container (via events)

## Configuration

Environment variables:
- `LOG_LEVEL` - Logging level (DEBUG, INFO, WARN, ERROR)
- `LOG_FORMAT` - Log format (json, text)
- `REDIS_URL` - Redis connection string
- `MCP_NETWORK` - Docker network for containers (default: agentarea_default)
- `MCP_PROXY_PORT` - Port for MCP proxy server (default: 8080)
- `MCP_DEFAULT_DOMAIN` - Default domain for MCP services (default: localhost)
- `MCP_MANAGER_URL` - URL of MCP manager service (default: http://localhost:8000)
- `TEMPLATES_DIR` - Directory containing container templates

## Development Tips

1. **Code changes**: Simply save your Go files - Air will detect and rebuild
2. **Dependencies**: Add new dependencies with `go mod tidy` in the container
3. **Debugging**: Use `docker exec -it mcp-manager sh` to access the container
4. **Logs**: Air shows build output and runtime logs together

## File Structure

```
cmd/mcp-manager/     # Main application entry point
internal/
  ├── api/           # HTTP API handlers
  ├── config/        # Configuration management
  ├── container/     # Container management
  ├── events/        # Event handling and Redis integration
  ├── models/        # Data models
  ├── providers/     # Provider implementations (Docker, URL)
  ├── proxy/         # Handwritten HTTP reverse proxy
  └── secrets/       # Secret resolution
```

## Proxy Routing

The MCP Manager includes a built-in HTTP reverse proxy (`internal/proxy/proxy.go`) that handles routing to MCP containers:

- **Path-based routing**: `/mcp/{slug}` routes to specific containers
- **Dynamic registration**: Routes are added/removed as containers start/stop
- **No port mapping**: Containers use internal IPs, no host port binding needed
- **No external dependencies**: No Traefik or Nginx required

Example:
- Container "my-mcp" with slug "my-mcp-abc123" is accessible at `http://localhost:8080/mcp/my-mcp-abc123`
