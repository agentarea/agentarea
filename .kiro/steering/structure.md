# AgentArea Project Structure

## Repository Organization

AgentArea uses a monorepo structure with clear service boundaries and shared tooling:

```
agentarea/
├── core/                    # Python backend services
├── frontend/               # Next.js web application
├── mcp-infrastructure/     # Go MCP manager + infrastructure
├── bootstrap/              # Initial setup and data seeding
├── charts/                 # Kubernetes Helm charts
├── docs/                   # Project documentation
├── scripts/                # Utility and testing scripts
├── data/                   # Configuration files (providers, etc.)
└── docker-compose.*.yaml   # Development environments
```

## Core Backend Structure (`core/`)

The Python backend follows a workspace pattern with domain-driven organization:

```
core/
├── apps/                   # Standalone applications
│   ├── api/               # FastAPI REST server
│   ├── worker/            # Background task worker
│   └── cli/               # Command-line interface
├── libs/                  # Domain libraries (shared packages)
│   ├── common/            # Shared utilities, database models
│   ├── agents/            # Agent management and execution
│   ├── llm/               # LLM model integration
│   ├── mcp/               # MCP server management
│   ├── tasks/             # Task orchestration
│   ├── secrets/           # Secret management (Infisical)
│   ├── execution/         # Temporal workflow execution
│   ├── context/           # Context and memory management
│   └── triggers/          # Event triggers and conditions
├── tests/                 # Integration and unit tests
├── alembic/               # Database migrations
├── cli.py                 # Main CLI entry point
└── pyproject.toml         # Workspace configuration
```

### Library Organization Pattern

Each domain library follows a consistent structure:

```
libs/{domain}/agentarea_{domain}/
├── domain/                # Core business logic
│   ├── models.py         # Domain entities
│   ├── services.py       # Business services
│   └── events.py         # Domain events
├── infrastructure/        # External integrations
│   ├── repository.py     # Data access
│   ├── orm.py           # Database mappings
│   └── external.py      # External API clients
├── api/                  # HTTP endpoints (if applicable)
└── __init__.py
```

## Frontend Structure (`frontend/`)

Next.js 15 application with App Router:

```
frontend/
├── src/
│   ├── app/              # App Router pages and layouts
│   ├── components/       # Reusable UI components
│   ├── lib/              # Utilities and configurations
│   └── types/            # TypeScript type definitions
├── public/               # Static assets
├── messages/             # Internationalization files
└── package.json
```

## MCP Infrastructure (`mcp-infrastructure/`)

Go-based MCP server management:

```
mcp-infrastructure/
├── go-mcp-manager/       # Go service for container management
├── traefik/              # Reverse proxy configuration
└── scripts/              # Infrastructure scripts
```

## Configuration and Data

### Environment Configuration
- `.env.example` - Template for environment variables
- `.env.local` - Local development overrides
- `core/.env` - Core service configuration

### Data Files
- `data/providers.yaml` - LLM provider configurations
- `data/mcp_providers.yaml` - MCP server specifications

### Secrets Management
- `.secrets.json` - Local development secrets
- Infisical integration for production secrets

## Key Architectural Patterns

### Workspace Pattern
- Multiple Python packages in single repository
- Shared dependencies managed through `uv` workspace
- Cross-package imports via workspace references

### Domain-Driven Design
- Business logic organized by domain (agents, tasks, mcp, etc.)
- Clear separation between domain, application, and infrastructure layers
- Domain events for cross-service communication

### Event-Driven Architecture
- Redis pub/sub for service communication
- Domain events published on state changes
- Async event handlers for cross-cutting concerns

### Repository Pattern
- Abstract data access through repository interfaces
- ORM mappings separate from domain models
- Easy testing with in-memory implementations

## Development Conventions

### File Naming
- Python: `snake_case` for files and modules
- TypeScript: `kebab-case` for files, `PascalCase` for components
- Configuration: `kebab-case` or `snake_case` depending on context

### Import Organization
- Standard library imports first
- Third-party imports second
- Local imports last
- Absolute imports preferred over relative

### Testing Structure
- Unit tests alongside source code in `tests/unit/`
- Integration tests in `tests/integration/`
- E2E tests in project root and `scripts/`

### Database Migrations
- Alembic migrations in `core/alembic/versions/`
- Descriptive migration names with timestamps
- Both upgrade and downgrade paths

## Deployment Structure

### Docker Composition
- `docker-compose.yaml` - Production deployment
- `docker-compose.dev.yaml` - Development environment
- `docker-compose.dev-infra.yaml` - Infrastructure only

### Kubernetes
- Helm charts in `charts/` directory
- Separate charts for each service
- Environment-specific value files

This structure supports the platform's microservices architecture while maintaining clear boundaries and shared tooling across the monorepo.