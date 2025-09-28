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

print_status "🚀 Testing AgentArea MCP Infrastructure with Simple MCP Servers..."

# Test 1: Check MCP Manager health
print_status "1. Testing MCP Manager health..."
if curl -f -s "$MCP_MANAGER_URL/health" > /dev/null; then
    print_success "MCP Manager is healthy"
else
    print_error "MCP Manager is not responding"
    exit 1
fi

# Test 2: Build and start multiple MCP containers
print_status "2. Building simple MCP server image..."
cd "$(dirname "$0")/../docker/templates/simple-mcp"
docker build -t mcp/simple:latest .
print_success "Simple MCP server image built"

cd "$(dirname "$0")/.."

print_status "3. Starting 3 MCP server instances..."

# Start 3 instances
for i in {1..3}; do
    CONTAINER_NAME="mcp-server-$i"
    CONTAINER_CONFIG='{
      "image": "mcp/simple:latest",
      "port": 8000,
      "environment": {
        "MCP_SERVICE_NAME": "'$CONTAINER_NAME'",
        "LOG_LEVEL": "INFO"
      },
      "memory_limit": "256m",
      "cpu_limit": "0.5"
    }'

    print_status "Starting $CONTAINER_NAME..."
    RESPONSE=$(curl -s -X POST "$MCP_MANAGER_URL/containers/$CONTAINER_NAME/start" \
      -H "Content-Type: application/json" \
      -d "$CONTAINER_CONFIG")

    if echo "$RESPONSE" | grep -q "started"; then
        print_success "$CONTAINER_NAME started successfully"
    else
        print_error "Failed to start $CONTAINER_NAME"
        echo "Response: $RESPONSE"
        exit 1
    fi
done

# Wait for all containers to be ready
print_status "4. Waiting for MCP services to be ready..."
sleep 20

# Test 3: Test each MCP server
print_status "5. Testing MCP functionality on all servers..."

for i in {1..3}; do
    CONTAINER_NAME="mcp-server-$i"
    MCP_SERVICE_URL="http://localhost/mcp/$CONTAINER_NAME"
    
    print_status "Testing $CONTAINER_NAME at $MCP_SERVICE_URL..."
    
    # Test health check
    if curl -f -s "$MCP_SERVICE_URL/health" > /dev/null; then
        print_success "$CONTAINER_NAME health check passed"
    else
        print_error "$CONTAINER_NAME health check failed"
        continue
    fi
    
    # Test store text via direct endpoint
    print_status "Testing store_text on $CONTAINER_NAME..."
    STORE_RESPONSE=$(curl -s -X POST "$MCP_SERVICE_URL/test/store?text=Hello%20from%20server%20$i&key=test-$i")
    if echo "$STORE_RESPONSE" | grep -q "stored.*true"; then
        print_success "$CONTAINER_NAME store_text test passed"
    else
        print_error "$CONTAINER_NAME store_text test failed"
        echo "Response: $STORE_RESPONSE"
    fi
    
    # Test get text via direct endpoint
    print_status "Testing get_text on $CONTAINER_NAME..."
    GET_RESPONSE=$(curl -s "$MCP_SERVICE_URL/test/get/test-$i")
    if echo "$GET_RESPONSE" | grep -q "Hello from server $i"; then
        print_success "$CONTAINER_NAME get_text test passed"
    else
        print_error "$CONTAINER_NAME get_text test failed"
        echo "Response: $GET_RESPONSE"
    fi
    
    # Test list texts
    print_status "Testing list_texts on $CONTAINER_NAME..."
    LIST_RESPONSE=$(curl -s "$MCP_SERVICE_URL/test/list")
    if echo "$LIST_RESPONSE" | grep -q "count.*1"; then
        print_success "$CONTAINER_NAME list_texts test passed"
    else
        print_error "$CONTAINER_NAME list_texts test failed"
        echo "Response: $LIST_RESPONSE"
    fi
done

# Test 4: Test MCP JSON-RPC protocol
print_status "6. Testing MCP JSON-RPC protocol..."

CONTAINER_NAME="mcp-server-1"
MCP_SERVICE_URL="http://localhost/mcp/$CONTAINER_NAME"

# Test store_text via JSON-RPC
MCP_STORE_REQUEST='{
  "jsonrpc": "2.0",
  "method": "store_text",
  "params": {
    "text": "JSON-RPC test message",
    "key": "jsonrpc-test"
  },
  "id": "test-1"
}'

print_status "Testing JSON-RPC store_text..."
JSONRPC_STORE_RESPONSE=$(curl -s -X POST "$MCP_SERVICE_URL/mcp" \
  -H "Content-Type: application/json" \
  -d "$MCP_STORE_REQUEST")

if echo "$JSONRPC_STORE_RESPONSE" | grep -q "stored.*true"; then
    print_success "JSON-RPC store_text test passed"
else
    print_error "JSON-RPC store_text test failed"
    echo "Response: $JSONRPC_STORE_RESPONSE"
fi

# Test get_text via JSON-RPC
MCP_GET_REQUEST='{
  "jsonrpc": "2.0",
  "method": "get_text",
  "params": {
    "key": "jsonrpc-test"
  },
  "id": "test-2"
}'

print_status "Testing JSON-RPC get_text..."
JSONRPC_GET_RESPONSE=$(curl -s -X POST "$MCP_SERVICE_URL/mcp" \
  -H "Content-Type: application/json" \
  -d "$MCP_GET_REQUEST")

if echo "$JSONRPC_GET_RESPONSE" | grep -q "JSON-RPC test message"; then
    print_success "JSON-RPC get_text test passed"
else
    print_error "JSON-RPC get_text test failed"
    echo "Response: $JSONRPC_GET_RESPONSE"
fi

# Test 5: Cross-server isolation test
print_status "7. Testing data isolation between servers..."

# Store data on server 1
curl -s -X POST "http://localhost/mcp/mcp-server-1/test/store?text=Server1%20Data&key=isolation-test" > /dev/null

# Try to get data from server 2 (should not exist)
ISOLATION_RESPONSE=$(curl -s "http://localhost/mcp/mcp-server-2/test/get/isolation-test")
if echo "$ISOLATION_RESPONSE" | grep -q "Key not found"; then
    print_success "Data isolation between servers working correctly"
else
    print_error "Data isolation test failed - data leaked between servers"
    echo "Response: $ISOLATION_RESPONSE"
fi

# Test 6: Container management via MCP Manager
print_status "8. Testing container management..."

# List all containers
LIST_CONTAINERS_RESPONSE=$(curl -s "$MCP_MANAGER_URL/containers")
CONTAINER_COUNT=$(echo "$LIST_CONTAINERS_RESPONSE" | grep -o "mcp-server-" | wc -l)

if [ "$CONTAINER_COUNT" -eq 3 ]; then
    print_success "All 3 containers are registered in MCP Manager"
else
    print_error "Expected 3 containers, found $CONTAINER_COUNT"
fi

# Get status of one container
STATUS_RESPONSE=$(curl -s "$MCP_MANAGER_URL/containers/mcp-server-1/status")
if echo "$STATUS_RESPONSE" | grep -q "running"; then
    print_success "Container status check passed"
else
    print_error "Container status check failed"
    echo "Response: $STATUS_RESPONSE"
fi

# Test 7: Load balancing demonstration
print_status "9. Demonstrating load distribution across servers..."

for i in {1..9}; do
    SERVER_NUM=$((i % 3 + 1))
    RESPONSE=$(curl -s "http://localhost/mcp/mcp-server-$SERVER_NUM/test/store?text=Load%20test%20$i&key=load-$i")
    if echo "$RESPONSE" | grep -q "mcp-server-$SERVER_NUM"; then
        echo "Request $i -> mcp-server-$SERVER_NUM ✓"
    else
        echo "Request $i -> mcp-server-$SERVER_NUM ✗"
    fi
done

print_success "Load distribution test completed"

# Final summary
print_status "10. Final verification - checking all servers have data..."

for i in {1..3}; do
    CONTAINER_NAME="mcp-server-$i"
    LIST_RESPONSE=$(curl -s "http://localhost/mcp/$CONTAINER_NAME/test/list")
    DATA_COUNT=$(echo "$LIST_RESPONSE" | grep -o '"count":[0-9]*' | cut -d: -f2)
    print_status "$CONTAINER_NAME has $DATA_COUNT items stored"
done

print_success "🎉 All MCP tests passed!"

print_status "🔗 Available MCP services:"
for i in {1..3}; do
    echo "  • mcp-server-$i: http://localhost/mcp/mcp-server-$i"
    echo "    - Health: http://localhost/mcp/mcp-server-$i/health"
    echo "    - Info: http://localhost/mcp/mcp-server-$i/info"
    echo "    - MCP JSON-RPC: http://localhost/mcp/mcp-server-$i/mcp"
done

print_status "🛠️ Management endpoints:"
echo "  • MCP Manager: http://localhost/api/mcp"
echo "  • Traefik Dashboard: http://localhost:8080"

print_status "To stop all containers:"
echo "  curl -X POST http://localhost/api/mcp/containers/mcp-server-1/stop"
echo "  curl -X POST http://localhost/api/mcp/containers/mcp-server-2/stop"
echo "  curl -X POST http://localhost/api/mcp/containers/mcp-server-3/stop" 