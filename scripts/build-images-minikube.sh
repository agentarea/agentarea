#!/bin/bash
# Build AgentArea images for ARM64 and load into minikube
# Usage: ./scripts/build-images-minikube.sh [component]
#   component: platform, frontend, or "all" (default)

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

# Build the platform image: one binary for every server role
build_platform() {
    log_info "Building Platform image..."
    build_image \
        "Platform" \
        "${PROJECT_ROOT}/agentarea-platform" \
        "${PROJECT_ROOT}/agentarea-platform/Dockerfile" \
        "agentarea/agentarea-platform:latest"
}

# Build frontend image
build_frontend() {
    log_info "Building Frontend image..."
    build_image \
        "Frontend" \
        "${PROJECT_ROOT}/agentarea-webapp" \
        "${PROJECT_ROOT}/agentarea-webapp/Dockerfile" \
        "agentarea/agentarea-frontend:latest"
}

# Main execution
main() {
    log_info "Starting AgentArea ARM64 image build for minikube..."
    
    check_minikube
    setup_docker_env
    
    case "${COMPONENT}" in
        platform)
            build_platform
            ;;
        frontend)
            build_frontend
            ;;
        all)
            build_platform
            build_frontend
            ;;
        *)
            log_error "Unknown component: ${COMPONENT}"
            echo "Usage: $0 [platform|frontend|all]"
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
