.PHONY: help check check-backend check-frontend check-db db-test-up db-test-down \
	frontend-dev docs-dev \
	agentarea-platform-api agentarea-platform-worker agentarea-platform-test \
	agentarea-platform-lint agentarea-platform-format agentarea-platform-sync \
	build-go lint-go test-go \
	build ensure-env up up-dev down down-dev down-clean restart restart-dev logs \
	k8s-build-images helm-gen preflight validate-icons \
	clean docker-clean full-clean

.DEFAULT_GOAL := help

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
NC := \033[0m # No Color

##@ General

help: ## Display this help message
	@echo "$(BLUE)Available targets:$(NC)"
	@awk 'BEGIN {FS = ":.*##"; printf "\n"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  $(GREEN)%-24s$(NC) %s\n", $$1, $$2 } /^##@/ { printf "\n$(YELLOW)%s$(NC)\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Checks (the same entrypoints CI runs)

check: check-backend check-frontend ## Every non-DB check across all stacks
	@echo "$(GREEN)All checks passed$(NC)"

check-backend: ## Platform + openapi drift, MCP manager, event service, operator
	$(MAKE) -C agentarea-platform check
	$(MAKE) -C agentarea-platform openapi-drift
	$(MAKE) -C agentarea-mcp-manager check
	$(MAKE) -C agentarea-event-service check
	$(MAKE) -C agentarea-operator check

check-frontend: ## Webapp (lint, types, tests, client drift, build) + CLI
	pnpm -C agentarea-webapp run check
	pnpm -C agentarea-webapp run check:integration
	pnpm -C agentarea-cli run check

check-db: ## Migrations roundtrip + schema-backed suites (needs POSTGRES_*; see db-test-up)
	$(MAKE) -C agentarea-platform check-db

DB_TEST_CONTAINER := agentarea-check-db
DB_TEST_PORT ?= 55432

db-test-up: ## Start a throwaway Postgres (tmpfs) for check-db and print its env
	docker run -d --rm --name $(DB_TEST_CONTAINER) \
		-e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=agentarea_test \
		-e PGDATA=/var/lib/postgresql/data --tmpfs /var/lib/postgresql/data \
		-p $(DB_TEST_PORT):5432 postgres:15
	@for _ in $$(seq 1 30); do \
		docker exec $(DB_TEST_CONTAINER) pg_isready -U postgres -d agentarea_test >/dev/null 2>&1 && break; \
		sleep 1; \
	done; \
	docker exec $(DB_TEST_CONTAINER) pg_isready -U postgres -d agentarea_test >/dev/null || { echo "Postgres did not become ready" >&2; exit 1; }
	@echo "export POSTGRES_HOST=localhost POSTGRES_PORT=$(DB_TEST_PORT) POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres POSTGRES_DB=agentarea_test"

db-test-down: ## Remove the check-db Postgres
	docker rm -f $(DB_TEST_CONTAINER)

##@ Development - Frontend

frontend-dev: ## Start frontend development server
	cd agentarea-webapp && pnpm dev

docs-dev: ## Start documentation development server
	cd docs && npm run dev

##@ Development - Platform (Python)

agentarea-platform-api: ## Run the API application
	cd agentarea-platform && uv run --package agentarea-api uvicorn agentarea_api.main:app --reload --host 0.0.0.0 --port 8000

agentarea-platform-worker: ## Run the worker application
	cd agentarea-platform && uv run --package agentarea-worker python -m agentarea_worker.main

agentarea-platform-test: ## Run platform Python tests
	$(MAKE) -C agentarea-platform test

agentarea-platform-lint: ## Lint platform Python code
	$(MAKE) -C agentarea-platform lint

agentarea-platform-format: ## Format platform Python code
	cd agentarea-platform && uv run ruff format && uv run ruff check --fix

agentarea-platform-sync: ## Sync platform dependencies
	cd agentarea-platform && uv sync --all-packages

##@ Development - Go MCP Manager

build-go: ## Build Go MCP manager
	$(MAKE) -C agentarea-mcp-manager build

lint-go: ## Lint Go code
	$(MAKE) -C agentarea-mcp-manager lint

test-go: ## Run Go tests
	$(MAKE) -C agentarea-mcp-manager test

##@ Docker - Development Environment

build: ## Build development Docker images
	docker compose -f docker-compose.dev.yaml build

ensure-env: ## Create .env and fill in any missing local credentials (idempotent)
	@test -f .env || { cp .env.example .env; echo "Created .env from .env.example"; }
	@./scripts/gen-dev-secrets.sh

up: ensure-env ## Start the published-image stack — the same one users get. Does NOT build your source.
	docker compose -f docker-compose.yaml up

up-dev: ensure-env ## Start the development stack, built from your source. Use this to develop.
	docker compose -f docker-compose.dev.yaml up

down: ## Stop the published-image stack
	docker compose -f docker-compose.yaml down

down-dev: ## Stop the development stack
	docker compose -f docker-compose.dev.yaml down

down-clean: ## Stop the development stack and remove its volumes
	docker compose -f docker-compose.dev.yaml down -v

restart: ## Restart the published-image stack
	docker compose -f docker-compose.yaml restart

restart-dev: ## Restart the development stack
	docker compose -f docker-compose.dev.yaml restart

logs: ## Follow logs from the development stack
	docker compose -f docker-compose.dev.yaml logs -f

##@ Kubernetes

k8s-build-images: ## Build and load images into Minikube
	@bash scripts/build-images-minikube.sh

helm-gen: ## Generate per-group env tpl files from config.yaml
	python3 scripts/generate_env_tpls.py

##@ Testing

preflight: ## Run all CI checks locally before pushing (lint, tests, schema, helm). Use SKIP=python,go,schema,env-tpl,helm-docs,helm-lint to skip groups.
	@bash scripts/preflight.sh

##@ Utilities

validate-icons: ## Validate icon files
	@python scripts/validate_icons.py

clean: ## Clean build artifacts and caches
	@echo "$(YELLOW)Cleaning build artifacts...$(NC)"
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "node_modules" -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "$(GREEN)Clean complete!$(NC)"

docker-clean: ## Clean Docker resources
	docker system prune -f
	docker volume prune -f

full-clean: clean docker-clean down-clean ## Complete cleanup (code + docker + volumes)
	@echo "$(GREEN)Full cleanup complete!$(NC)"
