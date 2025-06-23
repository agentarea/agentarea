# AgentArea Workspace

AgentArea is a modular and extensible framework for building AI agents with support for various AI providers, MCP (Model Context Protocol) servers, and agent-to-agent communication.

## Architecture

This is a Python workspace containing multiple applications and shared libraries:

### Applications
- **agentarea-api**: FastAPI-based REST API server
- **agentarea-worker**: Background worker for processing tasks

### Libraries
- **agentarea-common**: Shared utilities and infrastructure
- **agentarea-agents**: Agent management functionality  
- **agentarea-chat**: Chat and communication services
- **agentarea-llm**: LLM provider integrations
- **agentarea-mcp**: MCP (Model Context Protocol) support
- **agentarea-tasks**: Task management and execution
- **agentarea-secrets**: Secret management utilities

## Quick Start

1. Install dependencies:
   ```bash
   uv sync
   ```

2. Run the API:
   ```bash
   cd apps/api
   uv run uvicorn agentarea_api.main:app --reload
   ```

3. Run the worker:
   ```bash
   cd apps/worker  
   uv run python agentarea_worker/main.py
   ```

## Docker Deployment

```bash
docker-compose up --build
```

## Development

This workspace uses [uv](https://docs.astral.sh/uv/) for dependency management and supports hot reload during development.

For more information, see the documentation in the `docs/` directory.
