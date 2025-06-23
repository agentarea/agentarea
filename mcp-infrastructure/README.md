# MCP Infrastructure

A secure, scalable infrastructure for running Model Context Protocol (MCP) services with environment-specific backends.

## 🏗️ Architecture

**Environment-Aware Design**: The MCP Manager automatically detects its environment and uses the appropriate backend:

- **Docker Compose** (Development): Uses Podman + Traefik for container management and routing
- **Kubernetes** (Production): Uses native K8s resources (Deployments, Services, Ingress)

## 📁 Directory Structure

```
mcp-infrastructure/
├── go-mcp-manager/         # Go-based MCP Manager (main application)
├── docker-compose.yml      # Docker Compose deployment
├── traefik/                # Traefik configuration for Docker Compose backend
├── docker/                 # Container templates and configurations
├── k8s/                    # Kubernetes manifests and examples
├── scripts/                # Utility scripts for testing and management
├── BACKEND_STRATEGY.md     # Detailed architecture documentation
└── README.md              # This file
```

## 🚀 Quick Start

### Docker Compose (Development)

```bash
# Start the infrastructure
cd mcp-infrastructure
docker-compose up -d

# Check health
curl http://localhost:8000/health

# Create a service
curl -X POST http://localhost:8000/containers \
  -H "Content-Type: application/json" \
  -d '{"service_name": "nginx", "template": "nginx"}'

# Access the service
curl http://nginx.localhost
```

### Kubernetes (Production)

```bash
# Deploy to Kubernetes
kubectl apply -f k8s/

# Check health
kubectl port-forward svc/mcp-manager 8000:80
curl http://localhost:8000/health

# Create a service via API
curl -X POST http://localhost:8000/containers \
  -H "Content-Type: application/json" \
  -d '{"service_name": "nginx", "template": "nginx", "replicas": 3}'
```

## 🔧 API Usage

The HTTP API is consistent across all environments:

```bash
# List templates
curl http://localhost:8000/templates

# Create service from template
curl -X POST http://localhost:8000/containers \
  -H "Content-Type: application/json" \
  -d '{
    "service_name": "my-app",
    "template": "fastapi",
    "environment": {"DATABASE_URL": "sqlite:///app.db"},
    "replicas": 2
  }'

# List running services
curl http://localhost:8000/containers

# Get service status
curl http://localhost:8000/containers/my-app

# Delete service
curl -X DELETE http://localhost:8000/containers/my-app
```

## 🔒 Security Features

### Docker Compose Backend
- **Podman instead of Docker**: No Docker socket mounting
- **Rootless containers**: Enhanced security isolation
- **Privileged container isolation**: Single secure management layer

### Kubernetes Backend
- **Native K8s resources**: No privileged containers needed
- **RBAC integration**: Standard Kubernetes permissions
- **Network policies**: Standard K8s security model

## 📊 Environment Comparison

| Feature | Docker Compose | Kubernetes |
|---------|----------------|------------|
| **Container Runtime** | Podman | kubelet + containerd |
| **Service Discovery** | Traefik | Services |
| **Load Balancing** | Traefik | Services + Ingress |
| **Scaling** | Manual | Automatic (HPA) |
| **Storage** | Volumes | PVCs |
| **Secrets** | Environment | K8s Secrets |

## 🔒 Security Features

This infrastructure uses **Podman-in-Docker** instead of Docker-in-Docker for better security:

- **No Docker socket exposure**: Eliminates the major security risk of mounting `/var/run/docker.sock`
- **Rootless containers**: Podman runs containers without requiring root privileges by default
- **Privileged container isolation**: Uses a single privileged container to manage child containers safely
- **User namespace separation**: Better isolation between host and containers
- **No daemon dependency**: Podman doesn't require a running daemon as root

## Architecture

The infrastructure consists of:

1. **Traefik**: Reverse proxy and load balancer
2. **MCP Manager**: Podman-based container orchestrator with REST API
3. **MCP Containers**: Individual MCP services managed by the MCP Manager

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Traefik   │───▶│ MCP Manager │───▶│ MCP Service │
│             │    │  (Podman)   │    │ Containers  │
│ Port 80/443 │    │             │    │             │
└─────────────┘    └─────────────┘    └─────────────┘
```

## Quick Start

### Prerequisites

- Docker and Docker Compose
- At least 2GB RAM available
- Ports 80, 443, and 8080 available

### 1. Clone and Build

```bash
cd mcp-infrastructure
docker-compose -f docker/traefik/docker-compose.yml up -d
```

### 2. Verify Services

```bash
# Check service status
docker-compose -f docker/traefik/docker-compose.yml ps

# Check MCP Manager health
curl http://localhost/api/mcp/health

# Access Traefik dashboard
open http://traefik.localhost:8080
```

### 3. Deploy Your First MCP Service

```bash
# Start an echo service
curl -X POST http://localhost/api/mcp/containers/echo/start \
  -H "Content-Type: application/json" \
  -d '{
    "image": "mcp/echo:latest",
    "port": 8000,
    "environment": {
      "MCP_SERVICE_NAME": "echo"
    }
  }'

# Test the service
curl http://echo.localhost:8000/health
```

## API Usage

### Container Management

```bash
# List all containers
curl http://localhost/api/mcp/containers

# Get container status
curl http://localhost/api/mcp/containers/my-service/status

# Get container logs
curl http://localhost/api/mcp/containers/my-service/logs

# Stop container
curl -X POST http://localhost/api/mcp/containers/my-service/stop
```

## Configuration

### Environment Variables

The MCP Manager supports various environment variables:

```bash
# Container runtime configuration
CONTAINER_RUNTIME=podman
CONTAINERS_STORAGE_DRIVER=overlay
CONTAINERS_STORAGE_RUNROOT=/tmp/containers
CONTAINERS_STORAGE_GRAPHROOT=/var/lib/containers/storage

# Network configuration
MCP_NETWORK=mcp-network

# Resource limits
DEFAULT_MEMORY_LIMIT=512m
DEFAULT_CPU_LIMIT=0.5
MAX_CONTAINERS=100

# Security
ENABLE_AUTH=false
CORS_ORIGINS=*

# Monitoring
ENABLE_METRICS=true
HEALTH_CHECK_INTERVAL=30
```

### MCP Container Configuration

When starting containers, you can specify:

```json
{
  "image": "your-mcp-image:latest",
  "port": 8000,
  "environment": {
    "ENV_VAR": "value"
  },
  "volumes": {
    "/host/path": "/container/path"
  },
  "memory_limit": "512m",
  "cpu_limit": "1.0",
  "restart_policy": "unless-stopped",
  "health_check_path": "/health",
  "health_check_interval": 30,
  "labels": {
    "custom.label": "value"
  }
}
```

## Security

### Podman vs Docker Socket

Traditional Docker-in-Docker setups require mounting the Docker socket (`/var/run/docker.sock`), which poses significant security risks:

- **Full host access**: Any container with socket access can control the entire Docker daemon
- **Root privilege escalation**: Container can create privileged containers on the host
- **Host file system access**: Can mount any host directory into containers

Our Podman-based approach eliminates these risks:

- **Isolated container runtime**: Podman runs in a single privileged container
- **No socket exposure**: No communication with host Docker daemon
- **Rootless by default**: Child containers run without root privileges
- **Namespace isolation**: Better separation between containers and host

### Network Security

- All MCP containers run in isolated `mcp-network`
- Traefik handles TLS termination (configurable)
- CORS and rate limiting middleware
- Optional authentication middleware

### Resource Limits

- Memory and CPU limits enforced per container
- Maximum container count limits
- Storage quota management
- Network bandwidth controls (future)

## Monitoring

### Health Checks

- All containers include health checks
- Traefik monitors service health
- Automatic service removal on failure

### Metrics

Prometheus metrics are available at:
- MCP Manager: http://localhost/api/mcp/metrics
- Traefik: http://localhost:8080/metrics

### Logging

- Structured JSON logging
- Container logs accessible via API
- Traefik access logs

## Development

### Adding New MCP Templates

1. Create template JSON in `docker/mcp-manager/templates/`:

```json
{
  "name": "my-mcp",
  "description": "My custom MCP server",
  "image": "my-org/my-mcp:latest",
  "default_config": {
    "image": "my-org/my-mcp:latest",
    "port": 8000,
    "environment": {
      "MCP_SERVICE_NAME": "my-mcp"
    },
    "memory_limit": "512m",
    "cpu_limit": "0.5"
  },
  "required_env_vars": ["MCP_SERVICE_NAME"],
  "capabilities": ["custom-capability"]
}
```

2. Build and tag your MCP Docker image
3. Restart the MCP Manager to load new templates

### Creating MCP Containers

Your MCP containers should:

1. Expose an HTTP API on the configured port
2. Implement `/health` endpoint for health checks
3. Support graceful shutdown
4. Use environment variables for configuration

Example Dockerfile:
```dockerfile
FROM python:3.11-slim

# Install dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy application
COPY app.py .

# Health check
HEALTHCHECK --interval=30s --timeout=10s \
    CMD curl -f http://localhost:8000/health || exit 1

# Non-root user
RUN useradd mcpuser
USER mcpuser

EXPOSE 8000
CMD ["python", "app.py"]
```

## API Reference

### MCP Manager API

- `GET /health` - Service health check
- `GET /containers` - List all containers
- `POST /containers/{name}/start` - Start container
- `POST /containers/{name}/stop` - Stop container
- `GET /containers/{name}/status` - Get container status
- `GET /containers/{name}/logs` - Get container logs
- `GET /templates` - List available templates
- `GET /metrics` - Prometheus metrics

### Echo Server API (Example)

- `GET /health` - Health check
- `GET /` - Service information
- `POST /echo` - Echo message (JSON)
- `GET /echo/{message}` - Echo message (URL param)
- `GET /info` - Detailed service info
- `GET /mcp/capabilities` - MCP capabilities

## Troubleshooting

### Common Issues

1. **Container startup failures**
   ```bash
   # Check MCP Manager logs
   docker logs mcp-manager
   
   # Check container logs
   curl http://localhost/api/mcp/containers/service-name/logs
   ```

2. **Network connectivity issues**
   ```bash
   # Verify network exists
   docker network ls | grep mcp-network
   
   # Check service registration in Traefik
   curl http://localhost:8080/api/http/routers
   ```

3. **Resource limits**
   ```bash
   # Check container resource usage
   curl http://localhost/api/mcp/metrics
   ```

4. **Podman issues**
   ```bash
   # Check Podman status inside manager
   docker exec mcp-manager podman version
   docker exec mcp-manager podman system info
   ```

### Debug Mode

Enable debug logging:

```bash
docker-compose -f docker/traefik/docker-compose.yml down
docker-compose -f docker/traefik/docker-compose.yml up -d --build \
  -e LOG_LEVEL=DEBUG
```

### Performance Tuning

For high-load scenarios:

1. **Increase resource limits**:
   ```bash
   # In docker-compose.yml
   environment:
     - MAX_CONTAINERS=500
     - DEFAULT_MEMORY_LIMIT=1g
     - DEFAULT_CPU_LIMIT=1.0
   ```

2. **Enable Redis caching**:
   ```bash
   environment:
     - ENABLE_REDIS=true
     - REDIS_URL=redis://redis:6379/0
   ```

3. **Scale MCP Manager**:
   ```bash
   docker-compose -f docker/traefik/docker-compose.yml up -d --scale mcp-manager=3
   ```

## Migration from Docker Socket

If migrating from a Docker socket-based setup:

1. **Update container management code** to use REST API instead of Docker SDK
2. **Remove Docker socket mounts** from docker-compose.yml
3. **Update environment variables** to use Podman configuration
4. **Test container lifecycle** with the new Podman backend

Example migration:

```python
# Old Docker SDK approach
import docker
client = docker.from_env()
container = client.containers.run("image:tag", detach=True)

# New REST API approach
import httpx
response = httpx.post("http://mcp-manager:8000/containers/my-service/start", json={
    "image": "image:tag",
    "port": 8000
})
```

## 📋 Templates

Templates define service configurations and are stored in `docker/templates/`. Each template includes:

```json
{
  "name": "fastapi",
  "image": "python:3.11-slim",
  "port": 8000,
  "environment": {
    "PYTHONPATH": "/app"
  },
  "volumes": {
    "./app": "/app"
  },
  "command": ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
}
```

## 🛠️ Development

### Building from Source

```bash
# Build Go application
cd go-mcp-manager
go build -o bin/mcp-manager ./cmd/mcp-manager

# Build Docker image
docker build -t mcp-manager:latest .
```

### Running Tests

```bash
# Run test scripts
./scripts/test-mcp.sh
./scripts/test-echo.sh
```

## 📚 Documentation

- **[BACKEND_STRATEGY.md](BACKEND_STRATEGY.md)**: Detailed architecture and implementation strategy
- **[k8s/README.md](k8s/README.md)**: Kubernetes deployment guide
- **[go-mcp-manager/README.md](go-mcp-manager/README.md)**: Go application details

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details. 