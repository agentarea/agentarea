#!/bin/bash
# Clean up disk space in minikube
# Usage: ./scripts/cleanup-minikube.sh [--full]

set -e

FULL_CLEAN=${1:-}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
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

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

check_minikube() {
    if ! minikube status &>/dev/null; then
        log_error "Minikube is not running."
        exit 1
    fi
}

show_disk_usage() {
    log_info "Current disk usage in minikube:"
    minikube ssh -- "df -h" | grep -E "(Filesystem|overlay|/dev/vda)"
    echo ""
    minikube ssh -- "docker system df"
}

cleanup_docker() {
    log_step "Cleaning up Docker images and containers..."
    minikube ssh -- "docker system prune -af --volumes" || true
}

cleanup_images() {
    log_step "Removing unused Docker images..."
    minikube ssh -- "docker image prune -af" || true
}

cleanup_volumes() {
    log_step "Cleaning up unused volumes..."
    minikube ssh -- "docker volume prune -f" || true
}

cleanup_logs() {
    log_step "Cleaning up logs..."
    minikube ssh -- "sudo find /var/log -type f -name '*.log' -delete 2>/dev/null || true"
    minikube ssh -- "sudo journalctl --vacuum-time=1d 2>/dev/null || true"
}

cleanup_tmp() {
    log_step "Cleaning up temporary files..."
    minikube ssh -- "sudo rm -rf /tmp/* 2>/dev/null || true"
}

full_cleanup() {
    log_warn "Performing FULL cleanup - this will remove all non-running containers and images!"
    
    # Delete all completed/failed pods
    log_step "Deleting completed/failed pods..."
    kubectl delete pods --all-namespaces --field-selector=status.phase=Succeeded 2>/dev/null || true
    kubectl delete pods --all-namespaces --field-selector=status.phase=Failed 2>/dev/null || true
    
    # Clean everything
    cleanup_docker
    cleanup_volumes
    cleanup_logs
    cleanup_tmp
}

main() {
    log_info "Minikube Disk Cleanup Script"
    echo ""
    
    check_minikube
    
    echo "Before cleanup:"
    show_disk_usage
    echo ""
    
    if [ "$FULL_CLEAN" == "--full" ]; then
        full_cleanup
    else
        cleanup_docker
        cleanup_images
        cleanup_volumes
    fi
    
    echo ""
    echo "After cleanup:"
    show_disk_usage
    echo ""
    
    log_info "Cleanup complete!"
    log_info "To free more space, run with --full flag: ./scripts/cleanup-minikube.sh --full"
}

main "$@"
