.PHONY: help install sync run-api run-worker test lint format build-apps

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
	uv sync --all-packages

sync:
	uv sync --all-packages

run-api:
	uv run --package agentarea-api uvicorn agentarea_api.main:app --reload --host 0.0.0.0 --port 8000

run-worker:
	uv run --package agentarea-worker python -m agentarea_worker.main

test:
	uv run pytest tests/unit tests/functional

lint:
	uv run ruff check
	uv run pyright

format:
	uv run ruff format
	uv run ruff check --fix

build-apps:
	uv build apps/api
	uv build apps/worker 