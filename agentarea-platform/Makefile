.PHONY: help install sync run-api run-worker test test-flows lint format build-apps

help:
	@echo "Available commands:"
	@echo "  install     - Create virtual environment and install dependencies"
	@echo "  sync        - Sync all workspace dependencies" 
	@echo "  run-api     - Run the API application"
	@echo "  run-worker  - Run the worker application"
	@echo "  test        - Run tests"
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

lint:
	uv run --group lint ruff check
	uv run --group lint pyright

format:
	uv run ruff format
	uv run ruff check --fix

build-apps:
	uv build apps/api
	uv build apps/worker 
