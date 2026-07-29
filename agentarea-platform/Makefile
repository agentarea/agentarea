.PHONY: help install sync run-api run-worker test test-flows test-integration test-api test-full lint format build-apps

help:
	@echo "Available commands:"
	@echo "  install     - Create virtual environment and install dependencies"
	@echo "  sync        - Sync all workspace dependencies" 
	@echo "  run-api     - Run the API application"
	@echo "  run-worker  - Run the worker application"
	@echo "  test        - Hermetic per-merge gate (no infra)"
	@echo "  test-integration - Real-DB repository + Temporal tests (needs Postgres/Temporal)"
	@echo "  test-api    - OpenAPI contract + CRUD fuzz vs a LIVE stack (API+Kratos+DB up)"
	@echo "  test-full   - Everything: test + test-integration + test-api"
	@echo "  lint        - Run linting"
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

# Hermetic main-flow tests living OUTSIDE the dirs `test` already collects.
# Add new flow-test files here so both `test` (guard) and `test-flows` see them.
FLOW_TESTS := \
	libs/execution/tests/integration/test_task_complete_smoke.py \
	libs/execution/tests/integration/test_workflow_signals.py \
	libs/execution/tests/integration/test_flow_tool_use.py \
	libs/mcp/tests/test_flow_mcp_instance_lifecycle.py \
	libs/triggers/tests/test_flow_channels.py \
	libs/openapi/tests/test_service.py \
	libs/agentarea-agents-sdk/tests/test_flow_a2a_delegation.py

# Single source of truth for the per-merge gate (run verbatim by CI's
# `platform-test`). Covers unit + functional + apps/api + libs/common
# (OSS/Enterprise extension contract) + libs/tasks + all hermetic flow tests.
# Includes the flow coverage guard, which needs every flow test collected.
test:
	uv run python -m pytest tests/unit tests/functional apps/api/tests libs/common/tests libs/tasks/tests \
		$(FLOW_TESTS) \
		-m "not integration"

# Canonical main-flow suite — run before a release. Hermetic, no infra.
# Each flow is registered in agentarea_common.testing.flows.MainFlow and the
# coverage guard (run inside `make test`) enforces every flow has a test.
test-flows:
	uv run python -m pytest apps/api/tests libs/common/tests $(FLOW_TESTS) -m flow

# Real-DB repository + Temporal integration (needs Postgres + a Temporal dev
# server). These exercise actual schema constraints the hermetic `test` gate
# (mocked/sqlite) cannot. Mirrors the steps CI's integration job already trusts.
test-integration:
	uv run python -m pytest tests/integration/repositories tests/integration/test_temporal_workflow.py \
		-m "" --tb=short

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

# Everything, in order of infra cost: hermetic gate -> real-DB integration ->
# live-stack API fuzz. Run before a release or on a labelled PR.
test-full: test test-integration test-api

lint:
	uv run --group lint ruff check
	uv run --group lint pyright

format:
	uv run ruff format
	uv run ruff check --fix

build-apps:
	uv build apps/api
	uv build apps/worker 
