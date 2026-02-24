#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# API base URLs
MCP_MANAGER_URL="http://localhost/api/mcp"
ECHO_SERVICE_URL="http://localhost/mcp/echo-test"

print_status "Testing AgentArea MCP Infrastructure with Echo Server..."

# Test 1: Check MCP Manager health
print_status "1. Testing MCP Manager health..."
if curl -f -s "$MCP_MANAGER_URL/health" > /dev/null; then
    print_success "MCP Manager is healthy"
else
    print_error "MCP Manager is not responding"
    exit 1
fi

# Test 2: Start echo container
print_status "2. Starting echo container..."
CONTAINER_CONFIG='{
  "image": "mcp/echo:latest",
  "port": 8000,
  "environment": {
    "MCP_SERVICE_NAME": "echo-test",
    "LOG_LEVEL": "INFO"
  },
  "memory_limit": "256m",
  "cpu_limit": "0.5"
}'

RESPONSE=$(curl -s -X POST "$MCP_MANAGER_URL/containers/echo-test/start" \
  -H "Content-Type: application/json" \
  -d "$CONTAINER_CONFIG")

if echo "$RESPONSE" | grep -q "started"; then
    print_success "Echo container started successfully"
    CONTAINER_ID=$(echo "$RESPONSE" | grep -o '"container_id":"[^"]*"' | cut -d'"' -f4)
    print_status "Container ID: $CONTAINER_ID"
else
    print_error "Failed to start echo container"
    echo "Response: $RESPONSE"
    exit 1
fi

# Wait for container to be ready
print_status "3. Waiting for echo service to be ready..."
sleep 15

# Test 3: Check echo service health
print_status "4. Testing echo service health..."
MAX_RETRIES=10
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -f -s "$ECHO_SERVICE_URL/health" > /dev/null; then
        print_success "Echo service is healthy"
        break
    else
        RETRY_COUNT=$((RETRY_COUNT + 1))
        print_status "Retry $RETRY_COUNT/$MAX_RETRIES - waiting for echo service..."
        sleep 3
    fi
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    print_error "Echo service did not become healthy"
    
    # Show container logs for debugging
    print_status "Container logs:"
    curl -s "$MCP_MANAGER_URL/containers/echo-test/logs" | head -20
    exit 1
fi

# Test 4: Test echo functionality
print_status "5. Testing echo functionality..."

# Test GET endpoint
print_status "Testing GET /echo/hello..."
ECHO_RESPONSE=$(curl -s "$ECHO_SERVICE_URL/echo/hello")
if echo "$ECHO_RESPONSE" | grep -q "Echo: hello"; then
    print_success "GET echo test passed"
else
    print_error "GET echo test failed"
    echo "Response: $ECHO_RESPONSE"
fi

# Test POST endpoint
print_status "Testing POST /echo..."
POST_RESPONSE=$(curl -s -X POST "$ECHO_SERVICE_URL/echo" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello from MCP!", "metadata": {"test": true}}')

if echo "$POST_RESPONSE" | grep -q "Echo: Hello from MCP!"; then
    print_success "POST echo test passed"
else
    print_error "POST echo test failed"
    echo "Response: $POST_RESPONSE"
fi

# Test 5: Check MCP capabilities
print_status "6. Testing MCP capabilities endpoint..."
CAPABILITIES_RESPONSE=$(curl -s "$ECHO_SERVICE_URL/mcp/capabilities")
if echo "$CAPABILITIES_RESPONSE" | grep -q "protocol_version"; then
    print_success "MCP capabilities endpoint working"
else
    print_error "MCP capabilities endpoint failed"
    echo "Response: $CAPABILITIES_RESPONSE"
fi

# Test 6: Check container status via MCP Manager
print_status "7. Checking container status..."
STATUS_RESPONSE=$(curl -s "$MCP_MANAGER_URL/containers/echo-test/status")
if echo "$STATUS_RESPONSE" | grep -q "running"; then
    print_success "Container status check passed"
else
    print_error "Container status check failed"
    echo "Response: $STATUS_RESPONSE"
fi

# Test 7: List all containers
print_status "8. Listing all containers..."
LIST_RESPONSE=$(curl -s "$MCP_MANAGER_URL/containers")
if echo "$LIST_RESPONSE" | grep -q "echo-test"; then
    print_success "Container listing passed"
else
    print_error "Container listing failed"
    echo "Response: $LIST_RESPONSE"
fi

print_success "All tests passed! 🎉"
print_status "Echo service is accessible at:"
echo "  • Health: $ECHO_SERVICE_URL/health"
echo "  • Echo GET: $ECHO_SERVICE_URL/echo/your-message"
echo "  • Echo POST: $ECHO_SERVICE_URL/echo"
echo "  • MCP Capabilities: $ECHO_SERVICE_URL/mcp/capabilities"
echo "  • Service Info: $ECHO_SERVICE_URL/info"

print_status "MCP Manager endpoints:"
echo "  • Health: $MCP_MANAGER_URL/health"
echo "  • Containers: $MCP_MANAGER_URL/containers"
echo "  • Container Status: $MCP_MANAGER_URL/containers/echo-test/status"
echo "  • Container Logs: $MCP_MANAGER_URL/containers/echo-test/logs"

print_status "To stop the echo container:"
echo "  curl -X POST $MCP_MANAGER_URL/containers/echo-test/stop" 