# AgentArea Technology Stack

## Architecture

AgentArea uses a microservices architecture with event-driven communication:

- **Frontend**: Next.js 15 + TypeScript + React 19 with CopilotKit integration
- **Backend**: Python 3.12+ with FastAPI framework and async/await throughout
- **Infrastructure**: Docker containerization with Traefik reverse proxy
- **Database**: PostgreSQL 15 with JSON support for dynamic configurations
- **Caching/Events**: Redis for both caching and pub/sub event processing
- **Workflow Engine**: Temporal for long-running task orchestration
- **Container Runtime**: Podman (rootless containers for enhanced security)

## Core Technologies

### Backend Stack
- **FastAPI** - High-performance async API framework
- **Google Agent Development Kit (ADK)** - Standardized agent execution
- **LiteLLM** - Unified interface for multiple LLM providers (OpenAI, Claude, Gemini, Ollama)
- **Alembic** - Database migrations and schema management
- **SQLAlchemy** - ORM with async support
- **Pydantic** - Data validation and serialization

### Frontend Stack
- **Next.js 15** with App Router and server components
- **TypeScript** for type-safe development
- **CopilotKit** for AI-powered UI components
- **Tailwind CSS + Radix UI** for responsive design
- **React Hook Form + Zod** for form handling and validation

### Infrastructure & DevOps
- **Go 1.24+** for MCP server management service
- **Docker/Podman** containerization with multi-stage builds
- **Traefik** for dynamic reverse proxy and load balancing
- **MinIO** for object storage and file management
- **Infisical** for secure secrets management
- **uv** for Python package management (fast pip replacement)

### Protocols & Integration
- **Model Context Protocol (MCP)** - Universal tool connectivity standard
- **Agent-to-Agent (A2A) Protocol** - Inter-agent communication
- **JSON-RPC 2.0** - Standardized API communication
- **Server-Sent Events (SSE)** - Real-time streaming
- **WebSocket** - Bidirectional real-time communication

## Build System & Package Management

### Python (Core Backend)
- **uv** for dependency management and virtual environments
- **Workspace structure** with multiple packages in `core/libs/` and `core/apps/`
- **Hatchling** as build backend

### Node.js (Frontend)
- **pnpm** for package management
- **Next.js** build system with TypeScript compilation

### Development Tools
- **Ruff** for Python linting and formatting (replaces Black, isort, flake8)
- **Pyright** for Python type checking
- **ESLint** for JavaScript/TypeScript linting
- **Prettier** for code formatting

## Common Commands

### Development Setup
```bash
# Start full development environment
make up

# Start only infrastructure (DB, Redis, etc.)
make up-infra

# Frontend development
cd frontend && npm run dev

# Backend development  
cd core && uv run python cli.py serve --reload
```

### Testing
```bash
# Run all Python tests
cd core && uv run pytest

# Run with coverage
cd core && uv run pytest --cov

# Run MCP integration tests
cd core && uv run pytest tests/integration/test_mcp_real_integration.py -v

# Run E2E tests
python scripts/test_e2e.py
```

### Database Management
```bash
# Run migrations
cd core && uv run python cli.py migrate

# Create new migration
cd core && uv run alembic revision --autogenerate -m "description"
```

### Code Quality
```bash
# Python linting and formatting
cd core && uv run ruff check
cd core && uv run ruff format

# Type checking
cd core && uv run pyright

# Frontend linting
cd frontend && npm run lint
```

### Docker Operations
```bash
# Build services
make build

# View logs
docker-compose -f docker-compose.dev.yaml logs -f

# Clean up
make down
```

## Key Design Patterns

- **Event-Driven Architecture** - Redis pub/sub for service communication
- **Repository Pattern** - Abstract data access through interfaces
- **Dependency Injection** - FastAPI's DI system for service management
- **Domain-Driven Design** - Code organized around business domains
- **Unified Configuration Pattern** - JSON specs for dynamic provider configs
- **Async-First** - Non-blocking I/O throughout the stack