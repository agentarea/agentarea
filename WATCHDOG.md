# WATCHDOG — advisor-only review notes for the AgentArea monorepo

Instructions the advisor sees but the primary agent does not. Flag concrete
violations, not stylistic wishes.

## Hard traps (raise `blocker` / `concern`)

- **Migrations from the wrong dir.** Alembic MUST run from `apps/api`
  (`cd apps/api && alembic upgrade head`). Flag any `alembic` invoked from the
  repo root or elsewhere.
- **Workspace scoping dropped.** Every entity uses `WorkspaceScopedMixin`, and
  `UserContext` (user_id, workspace_id) is REQUIRED in every repository/service.
  Flag any repository/service constructed or queried without `UserContext`, and
  any query that could leak cross-workspace rows.
- **Events published to Redis only.** Workflow/domain events MUST be persisted
  to the DB *and* published to Redis pub/sub. Flag a Redis publish with no
  corresponding DB write (breaks SSE replay + audit).
- **`metadata` as a SQLAlchemy column name.** Reserved by the declarative base —
  MUST be `event_metadata`. Flag any model field named `metadata`.
- **`SIMPLE` in code/comments** is banned by house rule. Flag it.

## Temporal determinism

- Code inside `@workflow.defn` / `@workflow.run` MUST be deterministic: no direct
  network/DB/file IO, no `datetime.now`, `random`, `uuid4`, or unguarded env
  reads. Side effects belong in activities (`make_agent_activities()` factory).
  Flag non-deterministic calls in workflow bodies.
- Signals/queries (`@workflow.signal`, `@workflow.query`) must not block on IO.

## Layering

- API → service → `RepositoryFactory(session, user_context)` → repository.
  Flag API handlers touching the DB session directly or bypassing the service
  layer.
- DI singletons/factories resolve via `get_container()`; flag ad-hoc global
  singletons.

## Frontend

- Server actions and API calls must carry workspace context; flag fetches that
  assume a single global tenant.
