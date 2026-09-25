.PHONY: help install sync run-api run-worker check check-db lint test migrations-heads migrate \
	test-flows test-integration test-integration-core collect-integration test-api test-api-fuzz test-full \
	openapi-drift format build-apps build-api build-worker bench-build

help:
	@echo "Available commands:"
	@echo "  install     - Create virtual environment and install dependencies"
	@echo "  sync        - Sync all workspace dependencies"
	@echo "  run-api     - Run the API application"
	@echo "  run-worker  - Run the worker application"
	@echo ""
	@echo "  check       - lint + test + migrations-heads (no infra; what CI runs)"
	@echo "  check-db    - Migrations roundtrip + schema-backed suites (needs POSTGRES_*)"
	@echo "  lint        - ruff check + ruff format --check + pyright (CI platform-lint)"
	@echo "  test        - Hermetic per-merge gate, no infra (CI platform-test)"
	@echo "  migrations-heads - Assert exactly one alembic head"
	@echo "  openapi-drift    - Committed openapi.json matches the backend (CI schema-check)"
	@echo ""
	@echo "  migrate     - Apply migrations to the configured database"
	@echo "  test-integration - Real-DB repository + Temporal tests (needs Postgres/Temporal)"
	@echo "  test-integration-core - Core integration pool (needs Postgres/Valkey/Temporal)"
	@echo "  collect-integration   - Import-check the integration suite (no infra)"
	@echo "  test-api    - OpenAPI contract + CRUD fuzz vs a LIVE stack (API+Kratos+DB up)"
	@echo "  test-api-fuzz - The live-stack fuzz pair CI runs; fails if nothing ran"
	@echo "  test-full   - Everything: test + test-integration + test-api"
	@echo "  format      - Format code"
	@echo "  build-apps  - Build both applications"

install:
	uv venv
	uv sync --all-packages --group lint --group dev

sync:
	uv sync --all-packages

run-api:
	uv run --package agentarea-api uvicorn agentarea_api.main:app --reload --host 0.0.0.0 --port 8000

run-worker:
	uv run --package agentarea-worker python -m agentarea_worker.main

check: lint test migrations-heads

LINT_RUN := uv run --all-extras --group lint

lint:
	$(LINT_RUN) ruff check .
	$(LINT_RUN) ruff format --check .
	$(LINT_RUN) pyright

migrations-heads:
	@cd apps/api && out=$$(uv run alembic heads) && echo "$$out" && \
	n=$$(printf '%s\n' "$$out" | grep -c '(head)' || true) && \
	if [ "$$n" -ne 1 ]; then \
		echo "Expected exactly 1 migration head, found $$n. Conflicting branches: add a merge migration." >&2; \
		exit 1; \
	fi

# Suites and their *_TEST_DATABASE_URL wiring live in scripts/check-db.sh.
check-db: migrations-heads
	@bash scripts/check-db.sh

migrate:
	cd apps/api && uv run --package agentarea-api agentarea-api migrate

openapi-drift:
	@bash ../scripts/check-openapi-drift.sh

# Main-flow tests, listed for the `test-flows` release suite only. `test` no
# longer needs this list — it collects everything — so a new flow test is picked
# up by the gate whether or not it lands here; add it here to include it in the
# canonical flow run.
FLOW_TESTS := \
	libs/execution/tests/integration/test_task_complete_smoke.py \
	libs/execution/tests/integration/test_workflow_signals.py \
	libs/execution/tests/integration/test_flow_tool_use.py \
	libs/mcp/tests/test_flow_mcp_instance_lifecycle.py \
	libs/triggers/tests/test_flow_channels.py \
	libs/openapi/tests/test_service.py \
	libs/agentarea-agents-sdk/tests/test_flow_a2a_delegation.py

# Single source of truth for the per-merge gate (run verbatim by CI's
# `platform-test`).
#
# This used to enumerate the directories to collect, plus two hand-maintained
# lists of individual files that lived outside them. A library whose tests were
# not on the list simply never ran, and nothing failed to say so — the gate went
# green either way. It now collects everything and excludes by marker, so a new
# library is covered on arrival and dropping one has to be an explicit edit.
#
# The second pytest process this target used to need is gone too: it existed
# because libs/secrets/tests and libs/triggers/tests both imported their
# conftest as `tests.conftest`. Only the latter needs to be a package (it uses
# `from .conftest import ...`), so dropping the __init__.py from the former lets
# a single run collect both.
test:
	uv run python -m pytest libs apps tests -m "not integration"

# Canonical main-flow suite — run before a release. Hermetic, no infra.
# Each flow is registered in agentarea_common.testing.flows.MainFlow and the
# coverage guard (run inside `make test`) enforces every flow has a test.
test-flows:
	uv run python -m pytest apps/api/tests libs/common/tests $(FLOW_TESTS) -m flow

# Real-DB repository + Temporal integration (needs Postgres + a Temporal dev
# server). These exercise actual schema constraints the hermetic `test` gate
# (mocked/sqlite) cannot. CI's integration smoke job runs this target.
test-integration: migrate
	uv run python -m pytest tests/integration/repositories tests/integration/test_temporal_workflow.py \
		-m "" --tb=short

# Deterministic integration pool: postgres + valkey + Temporal only. Tests that
# need a real LLM / Docker / object store / API server are deselected.
test-integration-core: migrate
	uv run python -m pytest tests/integration/ -v --tb=short \
		-m "not slow and not requires_llm and not requires_docker and not requires_server and not requires_s3 and not perf"

# Pytest collection imports every module: catches a test importing a symbol a
# refactor renamed or deleted. Needs no infra.
collect-integration:
	uv run --all-extras python -m pytest tests/integration/ --collect-only -q

# OpenAPI contract + stateful CRUD fuzz against a LIVE stack (API + Kratos + DB
# must be up, e.g. `make up-dev` from the repo root). This is the only layer that
# would catch persistence/constraint 5xx on real create paths (e.g. the MCP slug
# NOT NULL 500). Override *_URL to point at a non-local stack.
API_URL ?= http://localhost:8000
KRATOS_ADMIN_URL ?= http://localhost:4434
KRATOS_PUBLIC_URL ?= http://localhost:4433
test-api:
	API_URL=$(API_URL) KRATOS_ADMIN_URL=$(KRATOS_ADMIN_URL) KRATOS_PUBLIC_URL=$(KRATOS_PUBLIC_URL) \
		uv run python -m pytest tests/e2e/api -p no:cacheprovider -o addopts="" --tb=short

# Both fuzz modules skip at import when the stack is unreachable and pytest then
# exits 5 ("no tests collected"); a silently skipped fuzz suite is
# indistinguishable from no coverage, so that is a failure here. -rs prints why.
test-api-fuzz:
	@API_URL=$(API_URL) KRATOS_ADMIN_URL=$(KRATOS_ADMIN_URL) KRATOS_PUBLIC_URL=$(KRATOS_PUBLIC_URL) \
		uv run python -m pytest tests/e2e/api/test_openapi_fuzz.py tests/e2e/api/test_stateful_fuzz.py \
		-m "" -p no:cacheprovider -o addopts="" --tb=short -rs; \
	status=$$?; \
	if [ "$$status" -eq 5 ]; then \
		echo "The fuzz suite collected nothing: both modules skipped at import (reason above)." >&2; \
		exit 1; \
	fi; \
	exit $$status

# Everything, in order of infra cost: hermetic gate -> real-DB integration ->
# live-stack API fuzz. Run before a release or on a labelled PR.
test-full: test test-integration test-api

format:
	uv run ruff format
	uv run ruff check --fix

build-apps: build-api build-worker

build-api build-worker: build-%:
	uv build apps/$*

# Markdown table of per-app build time (CI's `performance` job summary).
bench-build:
	@echo "## Build Performance Report"
	@echo "| Component | Build Time |"
	@echo "|-----------|------------|"
	@for component in api worker; do \
		start=$$(python3 -c 'import time; print(time.time())'); \
		uv build apps/$$component >&2 || exit 1; \
		end=$$(python3 -c 'import time; print(time.time())'); \
		echo "| $$component | $$(python3 -c "print(f'{$$end - $$start:.2f}')")s |"; \
	done
