# AGENTS.md

**Generated:** 2026-03-02

Python backend with uv workspace. FastAPI API + Temporal worker. DDD architecture.

## WHERE TO LOOK

| Task | Location |
|------|----------|
| Add API endpoint | apps/api/agentarea_api/api/v1/ |
| Add workflow | libs/execution/agentarea_execution/workflows/ |
| Add activity | libs/execution/agentarea_execution/activities/ |
| Add domain model | libs/{domain}/agentarea_{domain}/domain/ |
| Add repository | libs/{domain}/agentarea_{domain}/infrastructure/ |
| Add service | libs/{domain}/agentarea_{domain}/application/ |
| Shared utilities | libs/common/agentarea_common/ |
| Auth/JWT | libs/common/agentarea_common/auth/ |
| DI setup | libs/{domain}/agentarea_{domain}/infrastructure/di_container.py |

## STRUCTURE

```
agentarea-platform/
├── apps/
│   ├── api/           # FastAPI server (agentarea_api)
│   └── worker/        # Temporal worker (agentarea_worker)
└── libs/              # Domain libraries (uv workspace)
    ├── common/        # Base classes, auth, events, DI
    ├── agents/        # Agent domain
    ├── tasks/         # Task domain
    ├── llm/           # LLM providers/models
    ├── mcp/           # MCP protocol
    ├── execution/     # Temporal workflows
    ├── triggers/      # Event triggers
    ├── context/       # Context management
    ├── secrets/       # Secret management
    └── agentarea-agents-sdk/  # Agent SDK
```

## CONVENTIONS

- **DDD layers**: domain/ → application/ → infrastructure/
- **DI**: Each lib has `infrastructure/di_container.py` with `setup_*_di()`
- **Repos**: Inherit `WorkspaceScopedRepository`, require `UserContext`
- **Services**: Accept `RepositoryFactory` + other deps in constructor
- **Models**: Use `WorkspaceScopedMixin` for workspace isolation
- **Events**: Extend `DomainEvent`, publish via `EventBroker`

## ANTI-PATTERNS (THIS DIR)

- Never skip `UserContext` in repository constructors
- Never use `metadata` as field name (use `event_metadata`)
- Never create service without DI registration
- Never import from `apps/` in `libs/`

## COMMANDS

```bash
make install        # uv venv + sync all
make run-api        # uvicorn on :8000
make run-worker     # Temporal worker
make test           # pytest unit/functional
uv run pytest tests/integration/ -v  # integration tests
```

## ADDING NEW DOMAIN LIB

1. Create `libs/{name}/` with pyproject.toml
2. Add to root pyproject.toml `[tool.uv.workspace.members]`
3. Create `agentarea_{name}/` package with domain/application/infrastructure
4. Add `di_container.py` with `setup_{name}_di()`
5. Register in `apps/api/agentarea_api/api/deps/services.py`
