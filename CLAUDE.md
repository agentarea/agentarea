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
- `uv run ruff check` - Check code style
- `uv run pyright` - Type checking
- `python cli.py serve --reload` - Start API server with reload
- `python cli.py migrate` - Run database migrations

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
- `make up` - Start full development environment
- `make up-infra` - Start only infrastructure services
- `make down` - Stop and remove containers
- `make down-infra` - Stop infrastructure services

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

**Temporal Workflows:** Uses Temporal.io for reliable task execution and agent workflow orchestration.

**MCP Integration:** Model Context Protocol servers run in Docker containers managed by the Go MCP manager, providing tools and context to agents.

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

**Migration Management:** 
- Alembic migrations in `core/apps/api/alembic/versions/`
- Run migrations with `python cli.py migrate`

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