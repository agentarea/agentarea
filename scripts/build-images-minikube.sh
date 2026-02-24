#!/bin/bash
# Build AgentArea images for ARM64 and load into minikube
# Usage: ./scripts/build-images-minikube.sh [component]
#   component: api, worker, frontend, or "all" (default)

set -e

COMPONENT=${1:-all}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if minikube is running
check_minikube() {
    if ! minikube status &>/dev/null; then
        log_error "Minikube is not running. Start it with:"
        echo "  minikube start --driver=docker --cpus=4 --memory=8192"
        exit 1
    fi
    log_info "Minikube is running"
}

# Configure Docker to use minikube's Docker daemon
setup_docker_env() {
    log_info "Configuring Docker environment for minikube..."
    eval $(minikube docker-env)
    log_info "Docker environment configured"
}

# Build and load a single image
build_image() {
    local name=$1
    local context=$2
    local dockerfile=$3
    local tag=$4

    log_info "Building ${name} image for linux/arm64..."
    
    docker build \
        --platform linux/arm64 \
        -t "${tag}" \
        -f "${dockerfile}" \
        "${context}"
    
    log_info "✓ ${name} image built: ${tag}"
}

# Build backend API image
build_api() {
    log_info "Building Backend API image..."
    build_image \
        "Backend API" \
        "${PROJECT_ROOT}/core" \
        "${PROJECT_ROOT}/core/apps/api/Dockerfile" \
        "agentarea/agentarea-api:latest"
}

# Build worker image
build_worker() {
    log_info "Building Worker image..."
    build_image \
        "Worker" \
        "${PROJECT_ROOT}/core" \
        "${PROJECT_ROOT}/core/apps/worker/Dockerfile" \
        "agentarea/agentarea-worker:latest"
}

# Build frontend image
build_frontend() {
    log_info "Building Frontend image..."
    build_image \
        "Frontend" \
        "${PROJECT_ROOT}/frontend" \
        "${PROJECT_ROOT}/frontend/Dockerfile" \
        "agentarea/agentarea-frontend:latest"
}

# Build MCP Manager image
build_mcp_manager() {
    log_info "Building MCP Manager image..."
    build_image \
        "MCP Manager" \
        "${PROJECT_ROOT}/agentarea-mcp-manager" \
        "${PROJECT_ROOT}/agentarea-mcp-manager/Dockerfile" \
        "agentarea/agentarea-mcp-manager:latest"
}

# Build bootstrap image
build_bootstrap() {
    log_info "Building Bootstrap image..."
    build_image \
        "Bootstrap" \
        "${PROJECT_ROOT}/agentarea-bootstrap" \
        "${PROJECT_ROOT}/agentarea-bootstrap/Dockerfile" \
        "agentarea/agentarea-bootstrap:latest"
}

# Main execution
main() {
    log_info "Starting AgentArea ARM64 image build for minikube..."
    
    check_minikube
    setup_docker_env
    
    case "${COMPONENT}" in
        api)
            build_api
            ;;
        worker)
            build_worker
            ;;
        frontend)
            build_frontend
            ;;
        mcp-manager|mcp)
            build_mcp_manager
            ;;
        bootstrap)
            build_bootstrap
            ;;
        all)
            build_api
            build_worker
            build_frontend
            build_mcp_manager
            build_bootstrap
            ;;
        *)
            log_error "Unknown component: ${COMPONENT}"
            echo "Usage: $0 [api|worker|frontend|mcp-manager|bootstrap|all]"
            exit 1
            ;;
    esac
    
    log_info "Build complete! Images available in minikube:"
    echo ""
    minikube image list | grep "agentarea/" || true
    echo ""
    log_info "To deploy, run:"
    echo "  helm upgrade agentarea charts/agentarea -f charts/agentarea/values-minikube.yaml"
}

main "$@"
