# AgentArea MCP Infrastructure - Quick Reference

## 🏗️ Architecture Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Core API      │    │  Go MCP Manager │    │    Traefik      │
│  (Python/FastAPI)│    │   (Container    │    │ (Reverse Proxy) │
│   Port 8000     │    │   Management)   │    │   Port 81       │
│                 │    │   Port 7999     │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌─────────────────┐
                    │     Redis       │
                    │  (Event Bus)    │
                    │   Port 6379     │
                    └─────────────────┘
```

## 🚀 Quick Start

```bash
# Start development environment
make dev-up

# Run E2E tests
python test_mcp_flow.py

# Check service health
curl http://localhost:8000/v1/mcp-servers/
curl http://localhost:7999/health
```

## 🔗 Key URLs

| Service | URL | Purpose |
|---------|-----|---------|
| Core API | `http://localhost:8000` | MCP server/instance management |
| Go MCP Manager | `http://localhost:7999` | Container management API |
| Traefik Dashboard | `http://localhost:8080` | Proxy configuration |
| External MCP Access | `http://localhost:81/mcp/{slug}/mcp/` | MCP server endpoints |

## 📋 Key Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Container Runtime** | Podman | Security, rootless, daemonless |
| **Reverse Proxy** | Traefik | Dynamic config, better container integration |
| **Test MCP Server** | agentarea/echo | Reliable, lightweight, MCP compliant |
| **External Access** | Slug-based routing | Isolation, security, scalability |
| **Service Communication** | Redis Pub/Sub | Decoupling, reliability, event-driven |
| **Configuration** | File-based dynamic | Zero-downtime updates |
| **Development** | Docker Compose | Consistency, isolation |

## 🔧 Common Commands

### Development Environment
```bash
# Start all services
make dev-up

# Stop all services  
make dev-down

# View logs
docker-compose -f docker-compose.dev.yaml logs -f

# Restart specific service
docker-compose -f docker-compose.dev.yaml restart mcp-manager
```

### MCP Server Management
```bash
# List MCP servers
curl http://localhost:8000/v1/mcp-servers/

# Create MCP instance
curl -X POST http://localhost:8000/v1/mcp-server-instances/ \
  -H "Content-Type: application/json" \
  -d '{"name": "test", "json_spec": {...}}'

# List containers
curl http://localhost:7999/containers
```

### Container Management
```bash
# List running containers (from mcp-manager container)
docker exec mcp-manager podman ps

# View container logs
docker exec mcp-manager podman logs CONTAINER_NAME

# Inspect container
docker exec mcp-manager podman inspect CONTAINER_NAME
```

## 🧪 Testing

### E2E Test Flow
1. **Health Checks** - Verify services are running
2. **MCP Server Creation** - Create agentarea/echo specification
3. **MCP Instance Creation** - Create instance from spec
4. **Container Deployment** - Wait for Podman container
5. **Environment Variables** - Verify proper injection
6. **MCP Functionality** - Test protocol communication
7. **External Routing** - Test Traefik proxy access

### Test Commands
```bash
# Run full E2E test
python test_mcp_flow.py

# Test external access manually
curl "http://localhost:81/mcp/SLUG/mcp/" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {...}}'
```

## 🔒 Security Model

### Network Isolation
- MCP containers on dedicated `mcp-network`
- No direct port exposure to host
- All access through Traefik reverse proxy

### Access Control
- Slug-based URLs provide obscurity
- Unique slugs per MCP instance
- Path validation in Traefik rules

### Container Security
- Rootless Podman containers
- Limited privileges and capabilities
- Resource limits enforced

## 📁 File Structure

```
agentarea/
├── core/                           # Python Core API
│   ├── agentarea/api/v1/          # API endpoints
│   └── agentarea/modules/mcp/     # MCP domain logic
├── mcp-infrastructure/            # Go MCP Manager
│   ├── go-mcp-manager/           # Go service
│   └── traefik/                  # Traefik configuration
├── docs/                         # Documentation
│   ├── architecture-decisions.md # ADR document
│   └── quick-reference.md        # This file
├── test_mcp_flow.py             # E2E test script
└── docker-compose.dev.yaml     # Development environment
```

## 🐛 Troubleshooting

### Common Issues

**Services not starting:**
```bash
# Check Docker/Podman status
docker --version
podman --version

# Check port conflicts
netstat -tulpn | grep -E ':(8000|7999|81|6379)'
```

**Container creation fails:**
```bash
# Check mcp-manager logs
docker-compose -f docker-compose.dev.yaml logs mcp-manager

# Check Podman inside container
docker exec mcp-manager podman ps -a
docker exec mcp-manager podman system info
```

**External access not working:**
```bash
# Check Traefik configuration
cat mcp-infrastructure/traefik/dynamic.yml

# Check Traefik logs
docker-compose -f docker-compose.dev.yaml logs traefik

# Test internal connectivity
docker exec mcp-manager curl http://CONTAINER_NAME:PORT/mcp/
```

### Debug Commands
```bash
# Check Redis events
docker exec redis redis-cli MONITOR

# Inspect container network
docker exec mcp-manager podman network inspect mcp-network

# Check Traefik routes
curl http://localhost:8080/api/http/routers
```

## 📚 Documentation Links

- [Architecture Decisions](./architecture-decisions.md) - Detailed ADR document
- [MCP Architecture](./mcp_architecture.md) - System architecture overview
- [Architecture Insights](./architecture_insights.md) - Design patterns and insights

## 🔄 Development Workflow

1. **Make changes** to code
2. **Restart affected services** via Docker Compose
3. **Run E2E tests** to verify functionality
4. **Check logs** for any issues
5. **Test external access** manually if needed
6. **Commit changes** with clear messages

## 📞 Support

For questions or issues:
1. Check this quick reference
2. Review the ADR document for context
3. Check service logs for errors
4. Run E2E tests to isolate issues
5. Consult the team for complex problems

---

*Last updated: December 2024* 