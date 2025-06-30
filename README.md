# AgentArea

An open-core platform for building, testing, and running automation agents. AgentArea provides a simple way to create and experiment with AI agents locally, while offering enterprise features for production deployments.

## 🚀 Quick Start

Run your first agent in minutes:

```bash
# Clone the repository
git clone https://github.com/your-org/agentarea.git
cd agentarea

# Set up your environment
cp .env.example .env
docker-compose up
```

## ✨ Features

- **Universal Tool Integration** via Model Context Protocol (MCP)
- **Agent-to-Agent Communication** for collaborative workflows
- **Enterprise-Grade Security** with role-based access control
- **Visual Workflow Builder** for complex automation
- **Real-time Monitoring** and analytics dashboard
- **Marketplace Integration** for sharing and discovering agents

## 📖 Usage

### Basic Setup
```bash
# To run database migrations (if needed manually)
# docker-compose exec core python cli.py migrate

# To run the core server directly (usually handled by docker-compose)
# docker-compose exec core python cli.py serve --host 0.0.0.0 --port 8000
```

### 🧪 Testing MCP Integration

Test your MCP servers with AgentArea using our integrated testing framework:

```bash
# Run preset tests
python scripts/run_mcp_tests.py --preset weather
python scripts/run_mcp_tests.py --preset filesystem

# Test custom MCP server
python scripts/run_mcp_tests.py \
  --image myorg/mcp-server:latest \
  --url http://mcp-server:3000 \
  --tools tools.json

# Using pytest
pytest tests/integration/test_mcp_real_integration.py -v
```

See `tests/integration/README_MCP.md` for detailed testing documentation.

## 📚 Documentation

### Quick Start
- [Project Overview](docs/project-overview.md) - Vision, features, and business model
- [Current Tasks](docs/current-tasks.md) - Development status and active tasks
- [Quick Reference Guide](docs/quick-reference.md) - Commands, URLs, and troubleshooting

### Architecture & Design
- [Architecture Decisions (ADR)](docs/architecture-decisions.md) - Key architectural decisions and rationale
- [MCP Architecture Overview](docs/mcp_architecture.md) - System architecture and components
- [Architecture Insights](docs/architecture_insights.md) - Design patterns and insights
- [Agent-to-Agent Communication](docs/agent_to_agent_communication.md) - A2A protocol design
- [Dependency Injection Patterns](docs/dependency_injection_patterns.md) - DI patterns and best practices

### Implementation
- [MCP Implementation Plan](docs/mcp-implementation-plan.md) - Technical implementation roadmap
- [Task Assignment](docs/task_assignment.md) - Task distribution and management

### Development
- [E2E Testing](test_mcp_flow.py) - Comprehensive end-to-end test suite
- [MCP Integration Testing](tests/integration/README_MCP.md) - MCP server testing framework

For more detailed information, please refer to the [documentation index](docs/README.md).

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guidelines](CONTRIBUTING.md) for details on how to get involved.

## 📄 License

This project is licensed under the [MIT License](LICENSE.md).

## 💬 Community & Support

- [Report an issue](https://github.com/your-org/agentarea/issues)
- [Discussions](https://github.com/your-org/agentarea/discussions)
