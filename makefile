.PHONY: help dev build up down restart down-clean \
	frontend-dev docs-dev core-api core-worker core-test core-lint \
	k8s-setup k8s-test k8s-build-images helm-test \
	mcp-start mcp-stop mcp-test \
	test-e2e test-mcp cleanup-validation \
	lint-go build-go

.DEFAULT_GOAL := help

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
NC := \033[0m # No Color

##@ General

help: ## Display this help message
	@echo "$(BLUE)Available targets:$(NC)"
	@awk 'BEGIN {FS = ":.*##"; printf "\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2 } /^##@/ { printf "\n$(YELLOW)%s$(NC)\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Development - Frontend

frontend-dev: ## Start frontend development server
	cd frontend && npm run dev

docs-dev: ## Start documentation development server
	cd docs && npm run dev

##@ Development - Core (Python)

core-api: ## Run the API application
	cd core && uv run --package agentarea-api uvicorn agentarea_api.main:app --reload --host 0.0.0.0 --port 8000

core-worker: ## Run the worker application
	cd core && uv run --package agentarea-worker python -m agentarea_worker.main

core-test: ## Run core Python tests
	cd core && uv run pytest

core-lint: ## Lint core Python code
	cd core && uv run ruff check && uv run pyright

core-format: ## Format core Python code
	cd core && uv run ruff format && uv run ruff check --fix

core-sync: ## Sync core dependencies
	cd core && uv sync --all-packages

##@ Development - Go MCP Manager

build-go: ## Build Go MCP manager
	cd mcp-infrastructure/go-mcp-manager && go build ./...

lint-go: ## Lint Go code
	cd mcp-infrastructure/go-mcp-manager && golangci-lint run --timeout=5m

test-go: ## Run Go tests
	cd mcp-infrastructure/go-mcp-manager && go test ./...

##@ Docker - Development Environment

build: ## Build development Docker images
	docker compose -f docker-compose.dev.yaml build

up: ## Start development environment
	docker compose -f docker-compose.dev.yaml up

up-d: ## Start development environment in background
	docker compose -f docker-compose.dev.yaml up -d

down: ## Stop development environment
	docker compose -f docker-compose.dev.yaml down

down-clean: ## Stop and clean development environment (removes volumes)
	docker compose -f docker-compose.dev.yaml down -v

restart: ## Restart development environment
	docker compose -f docker-compose.dev.yaml restart

logs: ## Follow logs from all services
	docker compose -f docker-compose.dev.yaml logs -f

##@ Kubernetes

k8s-setup: ## Install and setup Minikube
	@bash scripts/install-minikube.sh

k8s-build-images: ## Build and load images into Minikube
	@bash scripts/build-images-minikube.sh

k8s-test: helm-test ## Run Kubernetes tests (alias for helm-test)

helm-test: ## Test Helm chart installation
	@bash scripts/test-chart.sh

##@ MCP Infrastructure

mcp-start: ## Start MCP infrastructure
	@bash mcp-infrastructure/scripts/start.sh

mcp-stop: ## Stop MCP infrastructure
	@bash mcp-infrastructure/scripts/stop.sh

mcp-test: ## Test MCP echo server
	@bash mcp-infrastructure/scripts/test-mcp.sh

mcp-test-echo: ## Test MCP echo server (detailed)
	@bash mcp-infrastructure/scripts/test-echo.sh

##@ Testing

test-e2e: ## Run end-to-end tests
	@python scripts/test_e2e.py

test-mcp-nginx: ## Run nginx MCP tests
	@python scripts/test_nginx_mcp.py

test-mcp-run: ## Run MCP tests
	@python scripts/run_mcp_tests.py

cleanup-validation: ## Run cleanup validation
	@python scripts/cleanup_validation.py

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
