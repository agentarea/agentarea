# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Backend (Python/FastAPI)

**Primary commands (from core/ directory):**
- `make install` - Set up uv virtual environment and install all dependencies
- `make sync` - Sync all workspace dependencies
- `make test` - Run all tests with pytest
- `make lint` - Run ruff linting and pyright type checking
- `make format` - Format code with ruff
- `make run-api` - Run the API server with auto-reload
- `make run-worker` - Run the worker application

**Alternative commands:**
- `uv run pytest` - Run tests directly
- `uv run pytest tests/unit/` - Run only unit tests
- `uv run pytest tests/integration/` - Run only integration tests
- `uv run pytest -m "not slow"` - Skip slow tests
- `uv run ruff check` - Check code style
- `uv run pyright` - Type checking
- `cd apps/api && alembic upgrade head` - Run database migrations
- `cd apps/api && alembic revision --autogenerate -m "description"` - Create new migration

### Frontend (Next.js)

**Commands (from frontend/ directory):**
- `npm run dev` - Start development server
- `npm run build` - Build for production
- `npm run lint` - Run ESLint
- `npm run format` - Fix linting issues

### Docker Infrastructure

**Main docker-compose files:**
- `docker-compose.dev.yaml` - Full development environment
- `docker-compose.dev-infra.yaml` - Infrastructure only (DB, Redis, Temporal)
- `docker-compose.yaml` - Production configuration

**Common commands:**
- `docker-compose -f docker-compose.dev-infra.yaml up -d` - Start infrastructure services
- `docker-compose -f docker-compose.dev.yaml up -d` - Start full development environment
- `docker-compose down` - Stop and remove containers
- `docker ps` - Show running containers
- `docker logs <container_name>` - View container logs

## Architecture Overview

AgentArea is a modular platform for building and running AI agents with the following key components:

### Core Architecture

**Workspace Structure:**
- `core/` - Python backend with uv workspace management
- `frontend/` - Next.js frontend application  
- `mcp-infrastructure/` - MCP (Model Context Protocol) server management in Go
- `bootstrap/` - System initialization and data population

**Backend Libraries (core/libs/):**
- `agentarea-common` - Shared utilities, config, database, events
- `agentarea-agents` - Agent domain models and services
- `agentarea-tasks` - Task execution and workflow management
- `agentarea-llm` - LLM provider and model management
- `agentarea-mcp` - MCP server integration and management
- `agentarea-secrets` - Secret management (Infisical/local)
- `agentarea-execution` - Temporal workflow execution

**Applications (core/apps/):**
- `agentarea-api` - Main FastAPI web server
- `agentarea-worker` - Background task worker
- `agentarea-cli` - Command-line interface

### Key Patterns

**Dependency Injection:** Uses a centralized DI container pattern in `agentarea_common.di.container` for service management across all libraries.

**Event-Driven Architecture:** Redis-based event system for inter-service communication via `agentarea_common.events`.

**Repository Pattern:** Domain-driven design with repository abstractions in each library's infrastructure layer.

**Temporal Workflows:** Uses Temporal.io for reliable task execution and agent workflow orchestration. Workflows are defined in `core/libs/execution/agentarea_execution/workflows/` and activities in `activities/`.

**MCP Integration:** Model Context Protocol servers run in Docker containers managed by the Go MCP manager, providing tools and context to agents.

**Event System:** Protocol-based event architecture using BaseWorkflowEvent structure. Events are published to Redis for real-time SSE streaming and stored in database via `task_events` table for historical access.

**LLM Integration:** Custom LLM execution layer supporting multiple providers (OpenAI, Anthropic, Ollama, etc.) via LiteLLM, integrated with Temporal workflows for durable agent task execution.

### Agent-to-Agent (A2A) Communication

The platform implements a standardized A2A protocol for inter-agent communication:
- **Bridge Pattern:** `a2a_bridge.py` handles message routing between agents
- **Authentication:** JWT-based auth for A2A endpoints
- **Protocol Compliance:** Follows Agent Communication Protocol standards
- **Well-Known Endpoints:** Discovery mechanism for agent capabilities

### Database Schema

**Core Entities:**
- Agents, Tasks, LLM Models/Instances, MCP Servers/Instances
- Provider specifications and configurations
- Task execution history and workflow state
- Task events (event sourcing for task lifecycle)

**Migration Management:** 
- Alembic migrations in `core/apps/api/alembic/versions/`
- Run migrations with `cd apps/api && alembic upgrade head`
- **Important:** When working with ORM models, avoid using `metadata` as a field name (SQLAlchemy reserved). Use `event_metadata` instead.

## Testing

**Test Organization:**
- `tests/unit/` - Fast, isolated unit tests
- `tests/integration/` - Database and service integration tests
- `tests/integration/README_MCP.md` - MCP testing framework documentation

**Test Execution:**
- Run all tests: `make test` or `uv run pytest`
- Run specific test types: `pytest -m "not slow"` or `pytest -m integration`
- Coverage reports generated in `htmlcov/`

**Test Environment:**
- Uses test-specific environment variables
- Requires running infrastructure (postgres, redis, temporal)
- MCP integration tests use real Docker containers

## Configuration

**Environment Management:**
- Development: Uses `.env` files and docker-compose
- Production: Environment variables and external secret management
- Test: Isolated test configuration in pytest.ini

**Key Services:**
- **Database:** PostgreSQL (localhost:5432 in development)
- **Cache/Events:** Redis (localhost:6379)
- **Workflows:** Temporal (localhost:7233)
- **Secrets:** Infisical or local file-based storage

## CLI Usage

The `python cli.py` command provides management interfaces for:
- LLM model and instance management (`cli llm`)
- MCP server and instance management (`cli mcp`)
- Agent creation and management (`cli agent`)
- Interactive chat with agents (`cli chat`)

## Frontend Integration

**Tech Stack:** Next.js with TypeScript, Tailwind CSS, shadcn/ui components
**Key Features:**
- Agent creation and management UI
- MCP server configuration
- Chat interface with CopilotKit integration
- Provider and model configuration
- Real-time task monitoring

**API Integration:** Uses openapi-fetch for type-safe API communication with the backend.

## Critical Architecture Patterns

### Workspace Management
- All entities are workspace-scoped using `WorkspaceScopedMixin`
- User context (`UserContext`) contains `user_id` and `workspace_id` for data isolation
- Repository pattern enforces workspace scoping at data access layer

### Real-time Event Flow
1. **Workflow Events**: Generated in Temporal workflows, published to Redis via `publish_workflow_events_activity`
2. **Database Persistence**: Events stored in `task_events` table alongside Redis publishing
3. **SSE Streaming**: Frontend connects to `/api/sse/agents/{id}/tasks/{id}/events/stream` for real-time updates
4. **Protocol Structure**: Events follow BaseWorkflowEvent format with `event_type`, `timestamp`, `data` fields

### Service Layer Pattern
- Services use dependency injection via `RepositoryFactory`
- Database sessions are request-scoped for transaction isolation
- All services accept `UserContext` for workspace/user scoping
- Event publishing integrated into service layer for domain events

### Task Execution Flow
1. **Task Creation**: API creates task via `TaskService.create_and_execute_task_with_workflow()`
2. **Workflow Execution**: Temporal workflow `AgentExecutionWorkflow` orchestrates execution
3. **Real-time Updates**: Events published during execution for UI updates
4. **Status Management**: Task status derived from workflow state and stored events

### Common Development Pitfalls
- **SQLAlchemy Reserved Names**: Avoid `metadata` as field name, use `event_metadata`
- **Workspace Scoping**: Always pass `UserContext` to repositories and services
- **Event Publishing**: Ensure events are both published to Redis AND stored in database
- **Migration Paths**: Run migrations from `apps/api/` directory, not project root