#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Change to script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

print_status "Starting AgentArea MCP Infrastructure..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    print_error "Docker is not running. Please start Docker first."
    exit 1
fi

print_success "Docker is running"

# Build the echo server image
print_status "Building echo server image..."
cd docker/templates/echo
docker build -t mcp/echo:latest .
print_success "Echo server image built"

# Go back to project root
cd "$PROJECT_DIR"

# Generate uv.lock file for mcp-manager if it doesn't exist
print_status "Preparing MCP Manager dependencies..."
cd docker/mcp-manager
if [ ! -f "uv.lock" ]; then
    print_status "Generating uv.lock file..."
    uv lock
fi
cd "$PROJECT_DIR"

# Start the infrastructure
print_status "Starting Traefik and MCP Manager..."
cd docker/traefik
docker-compose up -d

# Wait for services to be ready
print_status "Waiting for services to start..."
sleep 10

# Check if Traefik is running
if curl -f http://localhost:8080/api/rawdata > /dev/null 2>&1; then
    print_success "Traefik dashboard available at: http://localhost:8080"
else
    print_warning "Traefik dashboard not yet available"
fi

# Check if MCP Manager is running
if curl -f http://localhost/api/mcp/health > /dev/null 2>&1; then
    print_success "MCP Manager API available at: http://localhost/api/mcp"
else
    print_warning "MCP Manager not yet available"
fi

print_status "Infrastructure started! Available services:"
echo "  • Traefik Dashboard: http://localhost:8080"
echo "  • MCP Manager API: http://localhost/api/mcp"
echo "  • MCP Manager Health: http://localhost/api/mcp/health"
echo "  • MCP Manager Docs: http://localhost/api/mcp/docs"

print_status "You can now start MCP containers using the API:"
echo "  curl -X POST http://localhost/api/mcp/containers/echo-test/start \\"
echo "       -H 'Content-Type: application/json' \\"
echo "       -d '{\"image\": \"mcp/echo:latest\", \"port\": 8000}'"

print_success "AgentArea MCP Infrastructure is ready!" 