# AGENTS.md

**Generated:** 2026-03-02
**Branch:** main

Polyglot monorepo for building governed agentic networks with VPC-inspired architecture.

## WHERE TO LOOK

| Task | Location |
|------|----------|
| Backend (one Go binary, `agentarea <role>`) | `agentarea-platform/` |
| Roles (serve, worker, events, mcp, sandbox, operator, migrate, ...) | `agentarea-platform/app/roles.go`, wiring in `agentarea-platform/app/` |
| Domain modules (agents, runs, connections, sandbox, streams, ...) | `agentarea-platform/internal/modules/<module>/` |
| Agent workflows (Temporal) | `agentarea-platform/internal/modules/runs/workflows/` |
| LLM transports | `agentarea-platform/internal/modules/models/transport/` |
| MCP runtime and gateway | `agentarea-platform/internal/modules/connections/` |
| Ports shared by modules (db, events, authz, durable, ...) | `agentarea-platform/internal/kernel/` |
| Migrations (goose) | `agentarea-platform/internal/schema/migrations/` |
| Extension points (enterprise) | `agentarea-platform/ext/` |
| API fuzz against a live stack (Python, schemathesis) | `agentarea-platform/test/fuzz/` |
| Frontend UI | `agentarea-webapp/src/` |
| Release process | `docs/VERSIONING.md` + `scripts/release.sh` |
| Decisions (`ADR-NNNN` in code and commits) | The team's private wiki, not in this repo. If you have access it is checked out next to this repo at `../agentarea-wiki`; start at its `AGENTS.md` |

## STRUCTURE

```
agentarea/
├── agentarea-platform/     # Go backend: one binary, every server role
│   ├── app/                # roles and module wiring
│   ├── cmd/                # agentarea, activation-service, exec-supervisor
│   ├── internal/kernel/    # ports and value types, no domain
│   ├── internal/modules/   # domain modules (api, domain, service, store, handlers, workflows)
│   ├── internal/profiles/  # adapters (cluster)
│   ├── internal/schema/    # goose migrations
│   └── test/               # behaviour suite (Go) and API fuzz (Python)
├── agentarea-webapp/       # Next.js frontend + packages
├── agentarea-cli/          # Node.js CLI (Ink/React)
├── mcp-servers/            # mcp-base image and platform MCP apps
├── charts/                 # Helm charts (CRDs and example resources in charts/agentarea)
├── docs/                   # Mintlify documentation
└── scripts/                # Build/deploy utilities
```

## COMMANDS

Checks: one entrypoint per stack, the same command CI runs.

```bash
# From the repo root
make check          # Every non-DB check (check-backend + check-frontend)
make check-db       # Migrations + schema-backed suites; needs AGENTAREA_DB_TEST_URL (make db-test-up / db-test-down)

# Per stack
make -C agentarea-platform check        # go build + vet + test + golangci-lint + architecture checks
pnpm -C agentarea-webapp run check      # eslint + tsc + vitest (check:integration = client drift + build)
pnpm -C agentarea-cli run check         # prettier + tsc + ava

# Backend (from agentarea-platform/)
go run ./cmd/agentarea serve      # API on :8000
go run ./cmd/agentarea worker     # Temporal worker
deploy/suite/stack.sh up          # behaviour-suite stack; then deploy/suite/stack.sh test
make test-api-fuzz                # schemathesis against a running stack (AGENTAREA_API_URL, AGENTAREA_AUTH_KRATOS_*)

# Frontend (from agentarea-webapp/)
npm run dev         # Next.js on :3000
npm run build       # Production build

# Docker (from root)
make up-dev         # Full dev stack
make down-dev       # Stop containers
```

## KEY PATTERNS

**Layering:** a module imports the kernel, itself and other modules' `api` only; SQL lives in a module's `store/` and `internal/kernel/db`, the Temporal SDK in `internal/kernel/durable` and `modules/*/workflows`. `tools/archgen` generates `.golangci.yml` from these rules; `make check` fails on a violation.

**Workspace Scoping:** a store runs queries only through a `db.Session` bound to the workspace the call acts in; workspace-less tables go through `db.Global`, named so a reviewer sees it.

**Temporal Workflows:** per module in `internal/modules/<module>/workflows`, run by the `worker` role.

**Event Flow:** Workflow → DB (outbox) + Redis → SSE streaming to frontend.

## ANTI-PATTERNS

- **NEVER** query workspace data outside a `db.Session` → workspace-less access goes through `db.Global`
- **NEVER** publish events to Redis only → must also store in DB
- **NEVER** edit a migration that has shipped (`00001_baseline.sql` included) → add the next goose file in `internal/schema/migrations/`
- **NEVER** use "SIMPLE" in code/comments
- **NEVER** add a frontend test by default → a webapp change gets **no test**. Only two things earn one: a pure `.ts` module (no React, no DOM), or an e2e flow. Never `renderToStaticMarkup` + `expect(markup).toContain(...)`, never a test that mocks the pieces the component is made of and then asserts the markup those mocks produced. If UI logic feels worth testing, that is the signal it is not UI — lift it into a pure function and test the function. Full rule: `agentarea-webapp/AGENTS.md` → "TESTS (THIS DIR)"
- **NEVER** start UI work in `agentarea-webapp/src/**` from a blank file → first read `agentarea-webapp/AGENTS.md` (CONVENTIONS, ANTI-PATTERNS) and `agentarea-webapp/Design.md` (Patterns & Conventions), then find the shared component or sibling screen that already renders the same thing and reuse it. Lint and build pass a page that hand-rolls its own search, header button or table, so the drift only shows on screen.
- **NEVER** add, rename or remove an environment variable without `.agents/skills/aa-env-vars/SKILL.md` → names are `AGENTAREA_<DOMAIN>_<KEY>` unless a library reads its own standard name, one variable per value, no aliases, wired into the chart/compose/docs/migration table, and `python scripts/check_env_naming.py` must pass.

## SUBMODULE GUIDES

- **Backend:** `agentarea-platform/internal/kernel/README.md`, `agentarea-platform/internal/schema/README.md`, `agentarea-platform/test/suite/README.md`
- **Frontend:** `agentarea-webapp/AGENTS.md`
