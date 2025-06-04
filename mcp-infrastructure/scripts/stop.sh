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

print_status "Stopping AgentArea MCP Infrastructure..."

# Stop MCP containers first
print_status "Stopping MCP containers..."
docker stop $(docker ps -q --filter "label=managed_by=mcp-manager") 2>/dev/null || true
docker rm $(docker ps -aq --filter "label=managed_by=mcp-manager") 2>/dev/null || true

# Stop the main infrastructure
print_status "Stopping Traefik and MCP Manager..."
cd docker/traefik
docker-compose down

print_success "Infrastructure stopped"

# Optional: Remove MCP network (uncomment if desired)
# print_status "Removing MCP network..."
# docker network rm mcp-network 2>/dev/null || true

print_status "Cleanup complete!"
echo "To start again, run: ./scripts/start.sh" 