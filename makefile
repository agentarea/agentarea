.PHONY: help dev build up down restart down-clean \
	frontend-dev docs-dev agentarea-platform-api agentarea-platform-worker agentarea-platform-test agentarea-platform-lint \
	k8s-setup k8s-test k8s-build-images helm-test helm-gen \
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
	cd agentarea-webapp && npm run dev

docs-dev: ## Start documentation development server
	cd docs && npm run dev

##@ Development - Platform (Python)

agentarea-platform-api: ## Run the API application
	cd agentarea-platform && uv run --package agentarea-api uvicorn agentarea_api.main:app --reload --host 0.0.0.0 --port 8000

agentarea-platform-worker: ## Run the worker application
	cd agentarea-platform && uv run --package agentarea-worker python -m agentarea_worker.main

agentarea-platform-test: ## Run platform Python tests
	cd agentarea-platform && uv run pytest

agentarea-platform-lint: ## Lint platform Python code
	cd agentarea-platform && uv run ruff check && uv run pyright

agentarea-platform-format: ## Format platform Python code
	cd agentarea-platform && uv run ruff format && uv run ruff check --fix

agentarea-platform-sync: ## Sync platform dependencies
	cd agentarea-platform && uv sync --all-packages

##@ Development - Go MCP Manager

build-go: ## Build Go MCP manager
	cd agentarea-mcp-manager/go-mcp-manager && go build ./...

lint-go: ## Lint Go code
	cd agentarea-mcp-manager/go-mcp-manager && golangci-lint run --timeout=5m

test-go: ## Run Go tests
	cd agentarea-mcp-manager/go-mcp-manager && go test ./...

##@ Docker - Development Environment

build: ## Build development Docker images
	docker compose -f docker-compose.dev.yaml build

up: ## Start development environment
	docker compose -f docker-compose.yaml up

up-dev: ## Start development environment in background
	docker compose -f docker-compose.dev.yaml up

down: ## Stop development environment
	docker compose -f docker-compose.yaml down

down-dev: ## Stop development environment
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

helm-gen: ## Generate per-group env tpl files from config.yaml
	python3 scripts/generate_env_tpls.py

##@ MCP Infrastructure

mcp-start: ## Start MCP infrastructure
	@bash agentarea-mcp-manager/scripts/start.sh

mcp-stop: ## Stop MCP infrastructure
	@bash agentarea-mcp-manager/scripts/stop.sh

mcp-test: ## Test MCP echo server
	@bash agentarea-mcp-manager/scripts/test-mcp.sh

mcp-test-echo: ## Test MCP echo server (detailed)
	@bash agentarea-mcp-manager/scripts/test-echo.sh

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
