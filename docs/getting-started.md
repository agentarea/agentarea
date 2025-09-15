# Getting Started with AgentArea

<Info>
Create your first AI agent in under 5 minutes. This guide walks you through installation, setup, and building your first working agent.
</Info>

<Warning>
Make sure you have Docker installed and running before starting.
</Warning>

## 📋 Prerequisites

### Required Software
- **Docker** (v20.10+) or **Podman** (v4.0+)
- **Docker Compose** (v2.0+)
- **Git** (v2.30+)
- **Python** (v3.11+) - for local development
- **Node.js** (v18+) - for frontend development

### System Requirements
- **RAM**: 8GB minimum, 16GB recommended
- **Storage**: 10GB free space
- **OS**: Linux, macOS, or Windows with WSL2

## 🚀 Quick Setup (5 minutes)

### 1. Clone the Repository
```bash
git clone https://github.com/agentarea/agentarea.git
cd agentarea
```

### 2. Environment Configuration
```bash
# Copy environment template
cp core/docs/env.example .env

# Edit configuration (optional for development)
vim .env
```

### 3. Start Development Environment
```bash
# Using Docker Compose
docker compose -f docker-compose.dev.yaml up -d

# Or using make (if available)
make dev-up
```

### 4. Verify Installation
```bash
# Check service health
curl http://localhost:8000/health

# Expected response: {"status": "healthy"}
```

## 🔧 Development Environment

### Service Overview
| Service | Port | Purpose | Health Check |
|---------|------|---------|-------------|
| **Core API** | 8000 | Main application API | `http://localhost:8000/health` |
| **MCP Manager** | 7999 | MCP server management | `http://localhost:7999/health` |
| **Traefik** | 8080 | Reverse proxy dashboard | `http://localhost:8080` |
| **PostgreSQL** | 5432 | Database | Internal |
| **Redis** | 6379 | Cache & sessions | Internal |
| **MinIO** | 9000 | Object storage | `http://localhost:9000` |

### Key URLs
- **API Documentation**: `http://localhost:8000/docs`
- **Admin Interface**: `http://localhost:8000/admin`
- **MCP External Access**: `http://localhost:81/mcp/{slug}/mcp/`

## 🛠️ Development Workflow

### Daily Development
```bash
# Start services
docker compose -f docker-compose.dev.yaml up -d

# View logs
docker compose -f docker-compose.dev.yaml logs -f app

# Stop services
docker compose -f docker-compose.dev.yaml down
```

### Database Operations
```bash
# Run migrations
docker compose -f docker-compose.dev.yaml run --rm app alembic upgrade head

# Create new migration
docker compose -f docker-compose.dev.yaml run --rm app alembic revision --autogenerate -m "description"

# Reset database (development only)
docker compose -f docker-compose.dev.yaml down -v
docker compose -f docker-compose.dev.yaml up -d
```

### CLI Usage
```bash
# Access CLI inside container
docker compose -f docker-compose.dev.yaml exec app bash

# Run CLI commands
python -m agentarea_cli --help

# Example: Create an agent
python -m agentarea_cli agent create --name "test-agent" --type "chat"
```

## 🧪 Testing Your Setup

### 1. API Health Check
```bash
curl -X GET http://localhost:8000/health
# Expected: {"status": "healthy", "timestamp": "..."}
```

### 2. Create Your First Agent
```bash
curl -X POST http://localhost:8000/v1/agents/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "hello-world",
    "description": "My first agent",
    "type": "chat"
  }'
```

### 3. Test MCP Integration
```bash
# List available MCP servers
curl http://localhost:8000/v1/mcp-servers/

# Test MCP flow
python test_mcp_flow.py
```

### 4. Verify Database Connection
```bash
# Check database tables
docker compose -f docker-compose.dev.yaml exec db psql -U agentarea -d agentarea -c "\dt"
```

## 📚 Next Steps

### For Backend Developers
1. **[System Architecture](../core/docs/SYSTEM_ARCHITECTURE.md)** - Understand the technical implementation
2. **[CLI Usage](../core/docs/CLI_USAGE.md)** - Master the command-line interface
3. **[API Documentation](http://localhost:8000/docs)** - Explore available endpoints
4. **[Auth Implementation](auth_implementation.md)** - Learn authentication patterns

### For Frontend Developers
1. **[Agent Chat Implementation](../core/docs/agent-chat-implementation-plan.md)** - Chat system design
2. **[API Reference](#)** - Frontend integration patterns *(Coming Soon)*
3. **[UI Components](#)** - Reusable component library *(Coming Soon)*

### For DevOps/Infrastructure
1. **[Architecture Decisions](architecture-decisions.md)** - Infrastructure choices
2. **[Deployment Guide](#)** - Production deployment *(Coming Soon)*
3. **[Monitoring Setup](#)** - Observability configuration *(Coming Soon)*

### For Product/Business
1. **[Project Overview](project-overview.md)** - Vision and roadmap
2. **[Architecture Insights](architecture_insights.md)** - High-level system design
3. **[Task Assignment](task_assignment.md)** - Current development priorities

## 🔍 Troubleshooting

### Common Issues

#### Services Won't Start
```bash
# Check Docker daemon
docker info

# Check port conflicts
lsof -i :8000

# Clean restart
docker compose -f docker-compose.dev.yaml down -v
docker compose -f docker-compose.dev.yaml up -d
```

#### Database Connection Errors
```bash
# Check database logs
docker compose -f docker-compose.dev.yaml logs db

# Reset database
docker compose -f docker-compose.dev.yaml down -v
docker compose -f docker-compose.dev.yaml up -d db
# Wait 30 seconds, then start other services
```

#### Permission Errors
```bash
# Fix file permissions (Linux/macOS)
sudo chown -R $USER:$USER .

# Or run with sudo (not recommended)
sudo docker compose -f docker-compose.dev.yaml up -d
```

#### Module Import Errors
```bash
# Rebuild containers
docker compose -f docker-compose.dev.yaml build --no-cache
docker compose -f docker-compose.dev.yaml up -d
```

### Getting Help

1. **Check Logs**: `docker compose -f docker-compose.dev.yaml logs -f`
2. **Service Status**: `docker compose -f docker-compose.dev.yaml ps`
3. **Health Checks**: Visit health endpoints listed above
4. **Documentation**: Check our [troubleshooting guide](/troubleshooting)
5. **Community Support**: Ask for help in [GitHub Discussions](https://github.com/agentarea/agentarea/discussions)

## 🎉 Success!

If you've reached this point, you should have:
- ✅ AgentArea running locally
- ✅ All services healthy
- ✅ Database connected
- ✅ First API call successful

## 🚀 What's Next?

<CardGroup cols={2}>
  <Card title="Build Your First Agent" icon="bot" href="/building-agents">
    Create a working AI agent with our step-by-step guide
  </Card>
  <Card title="Explore Examples" icon="play" href="/examples">
    See real-world examples and use cases
  </Card>
</CardGroup>

**Ready to build amazing AI agent experiences!** 🚀

---

*Last updated: January 2025*
*Next review: February 2025*