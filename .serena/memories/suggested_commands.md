# Suggested Development Commands

## Backend (Python/FastAPI) - from core/ directory

### Primary commands:
- `make install` - Set up uv virtual environment and install all dependencies
- `make sync` - Sync all workspace dependencies
- `make test` - Run all tests with pytest
- `make lint` - Run ruff linting and pyright type checking
- `make format` - Format code with ruff
- `make run-api` - Run the API server with auto-reload
- `make run-worker` - Run the worker application

### Alternative commands:
- `uv run pytest` - Run tests directly
- `uv run ruff check` - Check code style
- `uv run pyright` - Type checking
- `python cli.py serve --reload` - Start API server with reload
- `python cli.py migrate` - Run database migrations

## Frontend (Next.js) - from frontend/ directory:
- `npm run dev` - Start development server
- `npm run build` - Build for production
- `npm run lint` - Run ESLint
- `npm run format` - Fix linting issues

## Docker Infrastructure

### Main docker-compose files:
- `docker-compose.dev.yaml` - Full development environment
- `docker-compose.dev-infra.yaml` - Infrastructure only (DB, Redis, Temporal)
- `docker-compose.yaml` - Production configuration

### Common commands:
- `make up` - Start full development environment
- `make up-infra` - Start only infrastructure services  
- `make down` - Stop and remove containers
- `make down-infra` - Stop infrastructure services

## Testing
- `pytest -m "not slow"` - Run fast tests only
- `pytest -m integration` - Run integration tests only
- `pytest tests/integration/test_mcp_real_integration.py -v` - MCP integration tests