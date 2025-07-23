# AgentArea Architecture Overview

AgentArea is a modular platform for building and running AI agents with a clean, layered architecture.

## Project Purpose
An open-core platform for building, testing, and running automation agents with:
- Universal Tool Integration via Model Context Protocol (MCP)
- Agent-to-Agent Communication for collaborative workflows
- Enterprise-Grade Security with role-based access control
- Visual Workflow Builder and Real-time Monitoring

## Core Architecture

### Workspace Structure
- `core/` - Python backend with uv workspace management
- `frontend/` - Next.js frontend application  
- `mcp-infrastructure/` - MCP server management in Go
- `bootstrap/` - System initialization and data population

### Backend Libraries (`core/libs/`)
- `agentarea-common` - Shared utilities, config, database, events, DI container
- `agentarea-agents` - Agent domain models and services
- `agentarea-tasks` - Task execution and workflow management
- `agentarea-llm` - LLM provider and model management
- `agentarea-mcp` - MCP server integration and management
- `agentarea-secrets` - Secret management (Infisical/local)
- `agentarea-execution` - Temporal workflow execution

### Applications (`core/apps/`)
- `agentarea-api` - Main FastAPI web server
- `agentarea-worker` - Background task worker
- `agentarea-cli` - Command-line interface

## Tech Stack
- **Backend**: Python 3.12+, FastAPI, SQLAlchemy, Alembic
- **Database**: PostgreSQL
- **Cache/Events**: Redis
- **Workflows**: Temporal.io
- **Frontend**: Next.js, TypeScript, Tailwind CSS, shadcn/ui
- **Package Management**: uv with workspace support
- **Containerization**: Docker, docker-compose