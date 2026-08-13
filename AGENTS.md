# AGENTS.md

**Generated:** 2026-03-02
**Branch:** main

Polyglot monorepo for building governed agentic networks with VPC-inspired architecture.

## WHERE TO LOOK

| Task | Location |
|------|----------|
| Backend API | `agentarea-platform/apps/api/agentarea_api/` |
| Temporal Worker | `agentarea-platform/apps/worker/agentarea_worker/` |
| Agent Workflows | `agentarea-platform/libs/execution/agentarea_execution/workflows/` |
| LLM Integration | `agentarea-platform/libs/llm/agentarea_llm/` |
| MCP Protocol | `agentarea-platform/libs/mcp/agentarea_mcp/` |
| Frontend UI | `agentarea-webapp/src/` |
| MCP Manager (Go) | `agentarea-mcp-manager/` |
| Shared Utilities | `agentarea-platform/libs/common/agentarea_common/` |
| Release process | `docs/VERSIONING.md` + `scripts/release.sh` |

## STRUCTURE

```
agentarea/
├── agentarea-platform/     # Python backend (FastAPI + Temporal)
│   ├── apps/               # API, worker, CLI apps
│   └── libs/               # Domain libraries (uv workspace)
├── agentarea-webapp/       # Next.js frontend + packages
├── agentarea-mcp-manager/  # Go MCP server orchestration
├── agentarea-cli/          # Node.js CLI (Ink/React)
├── agentarea-operator/     # K8s operator (catalog reconcile, LLM provider configs)
├── charts/                 # Helm charts
├── docs/                   # Mintlify documentation
└── scripts/                # Build/deploy utilities
```

## COMMANDS

```bash
# Backend (from agentarea-platform/)
make install        # Setup venv + install deps
make run-api        # FastAPI on :8000
make run-worker     # Temporal worker
make test           # Unit + functional tests

# Frontend (from agentarea-webapp/)
npm run dev         # Next.js on :3000
npm run build       # Production build

# Docker (from root)
make up-dev         # Full dev stack
make down-dev       # Stop containers

# Go MCP Manager (from agentarea-mcp-manager/)
go build ./...      # Build all
go test ./...       # Test all
```

## KEY PATTERNS

**Workspace Scoping:** All entities use `WorkspaceScopedMixin`. `UserContext` (user_id, workspace_id) required in all repositories/services.

**DI Container:** `agentarea_common.di.container` - register singletons/factories, resolve via `get_container()`.

**Repository Factory:** `RepositoryFactory(session, user_context)` creates workspace-scoped repositories.

**Temporal Workflows:** `@workflow.defn` classes with `@workflow.run`, `@workflow.signal`, `@workflow.query`. Activities via `make_agent_activities()` factory.

**Event Flow:** Workflow → Redis pub/sub + DB persistence → SSE streaming to frontend.

## ANTI-PATTERNS

- **NEVER** use `metadata` as SQLAlchemy field name → use `event_metadata`
- **NEVER** skip `UserContext` in repositories/services
- **NEVER** publish events to Redis only → must also store in DB
- **NEVER** run migrations from project root → `cd apps/api && alembic upgrade head`
- **NEVER** use "SIMPLE" in code/comments

## SUBMODULE GUIDES

- **Backend:** `agentarea-platform/AGENTS.md`
- **Frontend:** `agentarea-webapp/AGENTS.md`
- **MCP Manager:** `agentarea-mcp-manager/AGENTS.md`