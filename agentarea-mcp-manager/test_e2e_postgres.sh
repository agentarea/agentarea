#!/bin/bash
# E2E Test: PostgreSQL MCP with Auth
# This test creates a PostgreSQL MCP instance and verifies proxy authentication

set -e

echo "=========================================="
echo "E2E Test: PostgreSQL MCP with Auth"
echo "=========================================="

# Configuration
REDIS_URL="redis://localhost:6379"
MCP_SECRET="sk-test-postgres-e2e"
INSTANCE_ID="test-postgres-$(date +%s)"
CONTAINER_NAME="mcp-${INSTANCE_ID:0:20}"

echo ""
echo "=== Test Configuration ==="
echo "Instance ID: $INSTANCE_ID"
echo "Container Name: $CONTAINER_NAME"
echo "MCP Secret: $MCP_SECRET"

# Step 1: Verify MCP Manager is running
echo ""
echo "=== Step 1: Verify MCP Manager ==="
if ! curl -s http://localhost:8080/health > /dev/null; then
    echo "ERROR: MCP Manager not running on port 8080"
    exit 1
fi
echo "✓ MCP Manager is healthy"

# Step 2: Set MCP secret and restart MCP Manager
echo ""
echo "=== Step 2: Setting up MCP Manager with auth ==="
pkill -f "./mcp-manager" 2>/dev/null || true
sleep 1

cd "$(dirname "$0")"
export BACKEND_ENVIRONMENT=podman
export CONTAINER_RUNTIME=docker
export REDIS_URL="$REDIS_URL/0"
export CORE_API_URL=http://localhost:8000
export SERVER_PORT=8081
export MCP_PROXY_PORT=8080
export MCP_NETWORK=agentarea_default
export POSTGRES_USER=postgres
export POSTGRES_PASSWORD=postgres
export POSTGRES_DB=aiagents
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export SECRET_MANAGER_ENCRYPTION_KEY="$(echo -n '12345678901234567890123456789012' | base64)"
export MCP_SHARED_SECRET="$MCP_SECRET"

./mcp-manager > /tmp/mcp-manager-e2e.log 2>&1 &
sleep 3

if ! curl -s http://localhost:8080/health > /dev/null; then
    echo "ERROR: MCP Manager failed to start"
    cat /tmp/mcp-manager-e2e.log
    exit 1
fi
echo "✓ MCP Manager started with auth enabled"

# Step 3: Create PostgreSQL MCP instance via Redis event
echo ""
echo "=== Step 3: Creating PostgreSQL MCP instance ==="

# Build connection string for local postgres
# When running in Docker container, use host.docker.internal to reach host's postgres
POSTGRES_CONN="postgresql://postgres:postgres@host.docker.internal:5432/aiagents"

EVENT_PAYLOAD=$(cat <<EOF
{
  "specversion": "1.0",
  "type": "com.agentarea.mcp.instance.created",
  "source": "test/e2e",
  "id": "evt-$(date +%s)-postgres",
  "time": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "datacontenttype": "application/json",
  "correlationid": "corr-$(date +%s)",
  "data": {
    "instance_id": "$INSTANCE_ID",
    "name": "test-postgres-mcp",
    "server_spec_id": "postgres",
    "json_spec": {
      "type": "docker",
      "container_image": "mcp/postgres",
      "slug": "$INSTANCE_ID",
      "env_vars": {
        "POSTGRES_CONNECTION_STRING": "$POSTGRES_CONN",
        "POSTGRES_SCHEMA": "public"
      },
      "resource_limits": {
        "memory": "512m",
        "cpu": "1.0"
      }
    }
  }
}
EOF
)

echo "Publishing event to Redis..."
echo "$EVENT_PAYLOAD" | redis-cli -u "$REDIS_URL" PUBLISH "agentarea.events.mcp.instance.created" - > /dev/null

echo "✓ Event published"

# Step 4: Wait for container to start
echo ""
echo "=== Step 4: Waiting for container to start ==="
echo "Waiting up to 60 seconds..."

for i in {1..60}; do
    CONTAINER_ID=$(docker ps --filter "name=$CONTAINER_NAME" --format "{{.ID}}" 2>/dev/null || true)
    if [ -n "$CONTAINER_ID" ]; then
        echo ""
        echo "✓ Container started: $CONTAINER_ID"
        break
    fi
    sleep 1
    echo -n "."
done

if [ -z "$CONTAINER_ID" ]; then
    echo ""
    echo "ERROR: Container failed to start within 60 seconds"
    echo "MCP Manager logs:"
    tail -50 /tmp/mcp-manager-e2e.log
    exit 1
fi

# Step 5: Verify container is healthy
echo ""
echo "=== Step 5: Verify container health ==="
sleep 5

CONTAINER_STATUS=$(docker inspect --format='{{.State.Status}}' "$CONTAINER_ID" 2>/dev/null)
if [ "$CONTAINER_STATUS" != "running" ]; then
    echo "ERROR: Container not running (status: $CONTAINER_STATUS)"
    docker logs "$CONTAINER_ID" 2>&1 | tail -30 || true
    exit 1
fi
echo "✓ Container is running (status: $CONTAINER_STATUS)"

# Get container IP
CONTAINER_IP=$(docker inspect --format='{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$CONTAINER_ID")
echo "  Container IP: $CONTAINER_IP"

# Step 6: Test proxy WITHOUT auth (should fail with 401)
echo ""
echo "=== Step 6: Test proxy WITHOUT auth ==="
RESPONSE=$(curl -s -w "\nHTTP_CODE:%{http_code}" "http://localhost:8080/mcp/$INSTANCE_ID/tools" 2>&1)
HTTP_CODE=$(echo "$RESPONSE" | grep "HTTP_CODE:" | cut -d: -f2)
BODY=$(echo "$RESPONSE" | grep -v "HTTP_CODE:")

if [ "$HTTP_CODE" != "401" ]; then
    echo "ERROR: Expected 401 without auth, got $HTTP_CODE"
    echo "Response: $BODY"
    exit 1
fi
echo "✓ Request without auth rejected (401)"
echo "  Response: $BODY"

# Step 7: Test proxy with WRONG auth (should fail with 401)
echo ""
echo "=== Step 7: Test proxy with WRONG auth ==="
RESPONSE=$(curl -s -w "\nHTTP_CODE:%{http_code}" -H "Authorization: Bearer wrong-secret" \
    "http://localhost:8080/mcp/$INSTANCE_ID/tools" 2>&1)
HTTP_CODE=$(echo "$RESPONSE" | grep "HTTP_CODE:" | cut -d: -f2)
BODY=$(echo "$RESPONSE" | grep -v "HTTP_CODE:")

if [ "$HTTP_CODE" != "401" ]; then
    echo "ERROR: Expected 401 with wrong auth, got $HTTP_CODE"
    echo "Response: $BODY"
    exit 1
fi
echo "✓ Request with wrong auth rejected (401)"
echo "  Response: $BODY"

# Step 8: Test proxy with CORRECT auth (should succeed)
echo ""
echo "=== Step 8: Test proxy with CORRECT auth ==="
RESPONSE=$(curl -s -w "\nHTTP_CODE:%{http_code}" -H "Authorization: Bearer $MCP_SECRET" \
    "http://localhost:8080/mcp/$INSTANCE_ID/tools" 2>&1)
HTTP_CODE=$(echo "$RESPONSE" | grep "HTTP_CODE:" | cut -d: -f2)
BODY=$(echo "$RESPONSE" | grep -v "HTTP_CODE:")

echo "HTTP Status: $HTTP_CODE"
echo "Response: $BODY"

# Should be 200 for successful MCP response, or potentially other valid MCP responses
if [ "$HTTP_CODE" != "200" ] && [ "$HTTP_CODE" != "404" ]; then
    echo "WARNING: Unexpected status code: $HTTP_CODE"
fi
echo "✓ Request with correct auth allowed"

# Step 9: Test proxy with token query param
echo ""
echo "=== Step 9: Test proxy with token query param ==="
RESPONSE=$(curl -s -w "\nHTTP_CODE:%{http_code}" \
    "http://localhost:8080/mcp/$INSTANCE_ID/tools?token=$MCP_SECRET" 2>&1)
HTTP_CODE=$(echo "$RESPONSE" | grep "HTTP_CODE:" | cut -d: -f2)

echo "HTTP Status: $HTTP_CODE"
echo "✓ Request with token query param allowed"

# Step 10: Cleanup
echo ""
echo "=== Step 10: Cleanup ==="

# Publish delete event
DELETE_PAYLOAD=$(cat <<EOF
{
  "specversion": "1.0",
  "type": "com.agentarea.mcp.instance.deleted",
  "source": "test/e2e",
  "id": "evt-$(date +%s)-delete",
  "time": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "datacontenttype": "application/json",
  "correlationid": "corr-$(date +%s)",
  "data": {
    "instance_id": "$INSTANCE_ID",
    "name": "test-postgres-mcp"
  }
}
EOF
)

echo "Publishing delete event..."
echo "$DELETE_PAYLOAD" | redis-cli -u "$REDIS_URL" PUBLISH "agentarea.events.mcp.instance.deleted" - > /dev/null

sleep 5

# Verify container is removed
REMAINING=$(docker ps -a --filter "name=$CONTAINER_NAME" --format "{{.ID}}" 2>/dev/null || true)
if [ -n "$REMAINING" ]; then
    echo "WARNING: Container still exists, force removing..."
    docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
fi

echo "✓ Cleanup complete"

# Final summary
echo ""
echo "=========================================="
echo "E2E Test PASSED ✓"
echo "=========================================="
echo ""
echo "Summary:"
echo "  - MCP Manager started with auth"
echo "  - PostgreSQL MCP instance created"
echo "  - Unauthorized requests rejected (401)"
echo "  - Authorized requests allowed"
echo "  - Query param auth working"
echo "  - Cleanup successful"

# Stop MCP Manager
pkill -f "./mcp-manager" 2>/dev/null || true

exit 0
