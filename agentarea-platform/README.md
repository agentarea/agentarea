# AgentArea Core Backend

The core backend module for AgentArea, providing the main API, business logic, and orchestration capabilities.

## 🏗️ Architecture

The core backend is organized into several key modules:

- **`agentarea_api/`** - FastAPI application with REST endpoints
- **`apps/`** - Standalone applications (API server, worker, CLI)
- **`libs/`** - Shared libraries and domain modules
- **`tests/`** - Integration and unit tests

## 📚 Key Libraries

### Domain Libraries
- **`agentarea_agents/`** - Agent management, creation, and execution
- **`agentarea_chat/`** - Chat interface and conversation handling
- **`agentarea_llm/`** - LLM model management and abstraction
- **`agentarea_mcp/`** - MCP server management and communication
- **`agentarea_tasks/`** - Task orchestration and workflow management

### Infrastructure Libraries
- **`agentarea_common/`** - Shared utilities, database models, and patterns
- **`agentarea_secrets/`** - Secret management via Infisical

## 🚀 Getting Started

### Development Setup

```bash
# Navigate to core directory
cd core

# Install dependencies using uv
uv sync

# Run database migrations
uv run python cli.py migrate

# Start the development server
uv run python cli.py serve --host 0.0.0.0 --port 8000
```

### Using Docker

```bash
# Build and start with docker-compose (from project root)
docker-compose up core

# Or run specific services
docker-compose up core worker
```

## 🧪 Testing

### Running Tests

```bash
# Run all tests
uv run pytest

# Run specific test categories
uv run pytest tests/integration/
uv run pytest tests/unit/

# Run with coverage
uv run pytest --cov=agentarea
```

### MCP Integration Tests

```bash
# Test MCP server integration
uv run pytest tests/integration/test_mcp_real_integration.py -v

# Run comprehensive E2E tests
uv run python test_mcp_flow.py
```

## 📁 Directory Structure

```
core/
├── agentarea_api/          # Main FastAPI application
│   ├── api/v1/            # API endpoints
│   ├── config.py          # Configuration management
│   └── main.py            # Application entry point
├── apps/                  # Standalone applications
│   ├── api/               # API server app
│   ├── cli/               # Command-line interface
│   └── worker/            # Background worker
├── libs/                  # Domain libraries
│   ├── agents/            # Agent management
│   ├── chat/              # Chat functionality
│   ├── common/            # Shared utilities
│   ├── llm/               # LLM integration
│   ├── mcp/               # MCP protocol
│   ├── secrets/           # Secret management
│   └── tasks/             # Task orchestration
├── tests/                 # Test suites
├── alembic/               # Database migrations
├── cli.py                 # CLI entry point
└── pyproject.toml         # Project dependencies
```

## 🔧 Configuration

### Environment Variables

Key environment variables for configuration:

```bash
# Database
AGENTAREA_DB_URL=postgresql://user:pass@localhost:5432/agentarea

# Redis (for events and caching)
AGENTAREA_REDIS_URL=redis://localhost:6379

# Infisical (secret management)
INFISICAL_CLIENT_ID=your_client_id
INFISICAL_CLIENT_SECRET=your_client_secret

# External services
AGENTAREA_MCP_MANAGER_URL=http://localhost:8080
TEMPORAL_HOST=localhost:7233
```

### Development vs Production

- **Development**: Uses local PostgreSQL and Redis instances
- **Production**: Configured for cloud deployment with proper secret management

## 🌐 API Endpoints

The core API provides endpoints for:

- **Agents**: `GET|POST /api/v1/agents/`
- **LLM Models**: `GET|POST /api/v1/llm-models/`
- **MCP Servers**: `GET|POST /api/v1/mcp-servers/`
- **Tasks**: `GET|POST /api/v1/tasks/`
- **Chat**: `POST /api/v1/chat/`

See the [API documentation](docs/) for detailed endpoint specifications.

## 📖 Related Documentation

- **[Architecture Insights](../docs/architecture_insights.md)** - Overall system design
- **[MCP Architecture](../docs/mcp_architecture.md)** - MCP integration details
- **[Dependency Injection](../docs/dependency_injection_patterns.md)** - Code patterns
- **[Current Tasks](../docs/current-tasks.md)** - Development status

## 🤝 Contributing

1. Follow the established patterns in `agentarea_common/`
2. Add tests for new functionality
3. Update documentation for API changes
4. Use dependency injection for service interactions
