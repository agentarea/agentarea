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
- **Audit system**: Use `agentarea_common.audit` (`AuditService`, `@audited`) for DB-backed audit events
- **Audit decorator**: Prefer `@audited(action, resource_type, resource_id_param=...)` on service mutation methods
- **Money type**: All monetary values (costs, budgets, balances) use `Money` from `agentarea_common.money`. `Money` is `Decimal` with Pydantic str serialization — use it for model fields, arithmetic, and function args. Use `to_money()` to construct, `serialize_money()` for raw dicts/events. Never use `float` for money.

## ANTI-PATTERNS (THIS DIR)

- Never skip `UserContext` in repository constructors
- Never use `metadata` as field name (use `event_metadata`)
- Never create service without DI registration
- Never import from `apps/` in `libs/`
- Never add new usages of legacy `agentarea_common.logging.audit_logger`; use `agentarea_common.audit` instead
- Never use `float` for monetary values — use `Money` from `agentarea_common.money` (Decimal, serializes to str)

## COMMANDS

```bash
make install        # uv venv + sync all
make run-api        # uvicorn on :8000
make run-worker     # Temporal worker
make test           # pytest unit/functional
uv run pytest tests/integration/ -v  # integration tests
```

## ALEMBIC MIGRATIONS

- **Filenames: ISO timestamp** — `YYYYMMDD_HHMM_<slug>.py`, e.g. `20260601_1659_add_agent_mcp_slugs.py`. `alembic revision --autogenerate -m "..."` produces this format automatically via `file_template` in `apps/api/alembic.ini`. Sort chronologically in `ls`; no merge conflicts between parallel PRs.
- **Revision ids are capped at 32 chars** — `alembic_version.version_num` is `VARCHAR(32)`, so a `revision` string longer than that crashes the migration (`value too long for type character varying(32)`). `process_revision_directives` in `apps/api/alembic/env.py` auto-derives the id as `YYYYMMDD_HHMM_<slug>` truncated to 32 on `--autogenerate`; if you hand-write a revision id, keep it ≤32 chars. The filename slug may be longer than the rev_id (e.g. file `…_mcp_model_registry_provenance.py`, rev_id `…_mcp_model_reg_prov`).
- **Legacy names** — anything that predates this convention uses either numeric (`001_`, `011_`) or letter-pair (`aa, bb, ..., rr`) prefixes. **Do not extend the letter-pair scheme.** It was a half-baked attempt at chronological hints that didn't prevent collisions (we hit a `pp1_*` collision in #183). Leave existing files in place; new files go ISO.
- **`down_revision` is the source of truth** — alembic ignores filenames when ordering migrations. Always set `down_revision` to the current head (`uv run alembic heads` from `apps/api/`). When two parallel branches end up with two heads, add a merge revision: `uv run alembic merge -m "merge X and Y" <head_a> <head_b>`.
- **Self-contained** — never import helpers from `agentarea_common` or other domain libs into a migration. Inline anything you need so the migration is safe to run against any future revision of the codebase.

## ADDING NEW DOMAIN LIB

1. Create `libs/{name}/` with pyproject.toml
2. Add to root pyproject.toml `[tool.uv.workspace.members]`
3. Create `agentarea_{name}/` package with domain/application/infrastructure
4. Add `di_container.py` with `setup_{name}_di()`
5. Register in `apps/api/agentarea_api/api/deps/services.py`
