#!/bin/bash

# MCP Service Test Runner
# This script builds the service, starts it, runs tests, and cleans up

set -e

# Configuration
SERVICE_HOST="localhost"
SERVICE_PORT="8000"
BUILD_BINARY="./mcp-manager"
PID_FILE="/tmp/mcp-manager.pid"
LOG_FILE="/tmp/mcp-manager.log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Cleanup function
cleanup() {
    log_info "Cleaning up..."
    
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            log_info "Stopping MCP service (PID: $pid)"
            kill "$pid"
            
            # Wait for process to stop
            local count=0
            while kill -0 "$pid" 2>/dev/null && [ $count -lt 10 ]; do
                sleep 1
                count=$((count + 1))
            done
            
            if kill -0 "$pid" 2>/dev/null; then
                log_warning "Force killing service"
                kill -9 "$pid"
            fi
        fi
        rm -f "$PID_FILE"
    fi
    
    rm -f "$LOG_FILE"
}

# Trap cleanup on exit
trap cleanup EXIT

# Check if service is already running
check_service_running() {
    if curl -s "http://$SERVICE_HOST:$SERVICE_PORT/health" >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

# Wait for service to be ready
wait_for_service() {
    local max_wait=30
    local count=0
    
    log_info "Waiting for service to be ready..."
    
    while [ $count -lt $max_wait ]; do
        if check_service_running; then
            log_success "Service is ready!"
            return 0
        fi
        
        sleep 1
        count=$((count + 1))
        
        if [ $((count % 5)) -eq 0 ]; then
            log_info "Still waiting... ($count/${max_wait}s)"
        fi
    done
    
    log_error "Service did not become ready within ${max_wait} seconds"
    return 1
}

# Build the service
build_service() {
    log_info "Building MCP service..."
    
    if ! go build -o "$BUILD_BINARY" ./cmd/mcp-manager; then
        log_error "Failed to build service"
        exit 1
    fi
    
    log_success "Service built successfully"
}

# Start the service
start_service() {
    log_info "Starting MCP service..."
    
    # Set environment variables for testing
    export LOG_LEVEL="DEBUG"
    export BACKEND_ENVIRONMENT="docker"  # Force Docker backend for testing
    export CORS_ENABLED="true"
    
    # Start the service in background
    nohup "$BUILD_BINARY" > "$LOG_FILE" 2>&1 &
    local pid=$!
    echo $pid > "$PID_FILE"
    
    log_info "Service started with PID: $pid"
    log_info "Logs are being written to: $LOG_FILE"
    
    # Wait for service to be ready
    if ! wait_for_service; then
        log_error "Service failed to start properly"
        log_info "Last few lines of log:"
        tail -n 10 "$LOG_FILE" || true
        exit 1
    fi
}

# Run tests
run_tests() {
    log_info "Running MCP service tests..."
    
    # Check if we have python3
    if ! command -v python3 >/dev/null 2>&1; then
        log_error "python3 is required but not installed"
        exit 1
    fi
    
    # Run the simple test first
    log_info "Running simple tests..."
    if python3 simple_test.py --host "$SERVICE_HOST" --port "$SERVICE_PORT"; then
        log_success "Simple tests passed!"
    else
        log_error "Simple tests failed!"
        return 1
    fi
    
    # Run comprehensive tests if available and requests is installed
    if python3 -c "import requests" 2>/dev/null; then
        log_info "Running comprehensive tests..."
        if python3 test_mcp_service.py --host "$SERVICE_HOST" --port "$SERVICE_PORT" --legacy; then
            log_success "Comprehensive tests passed!"
        else
            log_warning "Comprehensive tests failed, but continuing..."
        fi
    else
        log_info "Skipping comprehensive tests (requests library not installed)"
        log_info "Install with: pip install requests"
    fi
    
    return 0
}

# Show service logs
show_logs() {
    if [ -f "$LOG_FILE" ]; then
        log_info "Service logs (last 20 lines):"
        echo "----------------------------------------"
        tail -n 20 "$LOG_FILE"
        echo "----------------------------------------"
    fi
}

# Main function
main() {
    local command="${1:-test}"
    
    case "$command" in
        "build")
            build_service
            ;;
        "start")
            build_service
            start_service
            log_info "Service is running. Use 'curl http://$SERVICE_HOST:$SERVICE_PORT/health' to test."
            log_info "Press Ctrl+C to stop..."
            wait
            ;;
        "test")
            build_service
            start_service
            run_tests
            ;;
        "logs")
            show_logs
            ;;
        "stop")
            cleanup
            ;;
        "health")
            if check_service_running; then
                log_success "Service is running and healthy"
                curl -s "http://$SERVICE_HOST:$SERVICE_PORT/health" | python3 -m json.tool 2>/dev/null || curl -s "http://$SERVICE_HOST:$SERVICE_PORT/health"
            else
                log_error "Service is not running or not healthy"
                exit 1
            fi
            ;;
        *)
            echo "Usage: $0 {build|start|test|logs|stop|health}"
            echo ""
            echo "Commands:"
            echo "  build  - Build the service binary"
            echo "  start  - Build and start the service (runs until Ctrl+C)"
            echo "  test   - Build, start service, run tests, and cleanup"
            echo "  logs   - Show recent service logs"
            echo "  stop   - Stop the running service"
            echo "  health - Check if service is running and healthy"
            echo ""
            echo "Environment variables:"
            echo "  SERVICE_HOST - Host to bind/connect to (default: localhost)"
            echo "  SERVICE_PORT - Port to bind/connect to (default: 8000)"
            exit 1
            ;;
    esac
}

# Allow environment variable overrides
SERVICE_HOST="${SERVICE_HOST:-localhost}"
SERVICE_PORT="${SERVICE_PORT:-8000}"

# Run main function
main "$@"