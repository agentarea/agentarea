# AgentArea Documentation

Welcome to the AgentArea documentation hub. This directory contains comprehensive guides and references for developers, architects, and stakeholders working with the AgentArea platform.

## 🚀 Quick Start

**New to AgentArea?** Start here:

1. **[Getting Started Guide](GETTING_STARTED.md)** - Complete setup walkthrough (30 minutes)
2. **[Project Overview](project-overview.md)** - Understanding AgentArea's vision and capabilities
3. **[Quick Reference](quick-reference.md)** - Essential commands and URLs

## 📚 Complete Documentation

**[📖 Documentation Index](DOCUMENTATION_INDEX.md)** - Comprehensive guide to all documentation, organized by audience and use case.

### By Role

#### 👨‍💻 Developers
- **[Getting Started](GETTING_STARTED.md)** - Setup and first steps
- **[CLI Usage](../core/docs/CLI_USAGE.md)** - Command-line interface
- **[System Architecture](../core/docs/SYSTEM_ARCHITECTURE.md)** - Technical implementation
- **[API Documentation](http://localhost:8000/docs)** - Interactive API reference

#### 🏗️ Architects
- **[Architecture Insights](architecture_insights.md)** - High-level system design
- **[Architecture Decisions](architecture-decisions.md)** - ADRs and design rationale
- **[MCP Architecture](mcp_architecture.md)** - Model Context Protocol integration

#### 📋 Product/Business
- **[Project Overview](project-overview.md)** - Vision, market, and roadmap
- **[Current Tasks](task_assignment.md)** - Active development priorities

### By Feature

#### 🤖 Agent Development
- **[A2A Integration Guide](../core/docs/A2A_INTEGRATION_GUIDE.md)** - Agent-to-Agent communication
- **[Agent Chat Implementation](../core/docs/agent-chat-implementation-plan.md)** - Chat system
- **[Agent Protocol Implementation](../core/docs/agent-protocol-implementation-plan.md)** - Protocol details

#### 🔌 MCP Integration
- **[MCP Architecture](mcp_architecture.md)** - System design
- **[MCP Implementation Plan](mcp-implementation-plan.md)** - Development roadmap

#### 🔐 Authentication
- **[Auth Implementation](auth_implementation.md)** - Authentication system
- **[Auth Context Dependency](../core/docs/auth_context_dependency.md)** - Auth patterns
- **[Dependency Injection](dependency_injection_patterns.md)** - DI patterns

## 🎯 Common Use Cases

| I want to... | Start with... |
|--------------|---------------|
| Set up development environment | [Getting Started](GETTING_STARTED.md) |
| Understand the architecture | [Architecture Insights](architecture_insights.md) |
| Build an agent | [A2A Integration Guide](../core/docs/A2A_INTEGRATION_GUIDE.md) |
| Use the CLI | [CLI Usage](../core/docs/CLI_USAGE.md) |
| Deploy to production | [Deployment Guide](#) *(Coming Soon)* |
| Contribute code | [Contributing Guidelines](#) *(Coming Soon)* |

## 🔧 Development Resources

### Essential URLs
- **Core API**: `http://localhost:8000`
- **API Docs**: `http://localhost:8000/docs`
- **MCP Manager**: `http://localhost:7999`
- **Traefik Dashboard**: `http://localhost:8080`

### Quick Commands
```bash
# Start development
make dev-up

# View logs
docker compose -f docker-compose.dev.yaml logs -f

# Run tests
python test_mcp_flow.py
```

## 📋 Documentation Status

- ✅ **Complete** - Comprehensive and up-to-date
- 🔄 **In Progress** - Partially complete
- ⚠️ **Planned** - Not yet started

See [Documentation Index](DOCUMENTATION_INDEX.md) for detailed status of all documents.

---

*This documentation is actively maintained. For questions or improvements, please contact the development team.*

*Last updated: January 2025*
