#!/bin/bash
# E2E Test: MCP Container with Auth
# This test creates an MCP container and verifies proxy authentication

set -e

echo "=========================================="
echo "E2E Test: MCP Container with Auth"
echo "=========================================="

# Configuration
REDIS_URL="redis://localhost:6379"
MCP_SECRET="sk-test-mcp-e2e"
INSTANCE_ID="test-mcp-$(date +%s)"
CONTAINER_NAME="mcp-${INSTANCE_ID:0:20}"

echo ""
echo "=== Test Configuration ==="
echo "Instance ID: $INSTANCE_ID"
echo "Container Name: $CONTAINER_NAME"
echo "MCP Secret: $MCP_SECRET"

# Step 1: Pull MCP image if needed
echo ""
echo "=== Step 1: Ensure MCP image available ==="
if ! docker image ls | grep -q "mcp/fetch"; then
    echo "Pulling mcp/fetch image..."
    docker pull mcp/fetch:latest
fi
echo "✓ MCP image available"

# Step 2: Verify MCP Manager is running
echo ""
echo "=== Step 2: Verify MCP Manager ==="
if ! curl -s http://localhost:8080/health > /dev/null 2>&1; then
    echo "Starting MCP Manager..."
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
    
    if ! curl -s http://localhost:8080/health > /dev/null 2>&1; then
        echo "ERROR: MCP Manager failed to start"
        cat /tmp/mcp-manager-e2e.log
        exit 1
    fi
fi
echo "✓ MCP Manager is healthy"

# Step 3: Cleanup any existing test containers
echo ""
echo "=== Step 3: Cleanup existing test containers ==="
docker ps -a --filter "name=mcp-test-" --format "{{.Names}}" | while read name; do
    echo "Removing old container: $name"
    docker rm -f "$name" 2>/dev/null || true
done
echo "✓ Cleanup complete"

# Step 4: Create MCP instance via Redis event
echo ""
echo "=== Step 4: Creating MCP container instance ==="

python3 << PYEOF
import redis
import json
from datetime import datetime, timezone

r = redis.Redis.from_url("$REDIS_URL")

event = {
    "specversion": "1.0",
    "type": "com.agentarea.mcp.instance.created",
    "source": "test/e2e",
    "id": f"evt-{int(datetime.now().timestamp())}-mcp",
    "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "datacontenttype": "application/json",
    "correlationid": f"corr-{int(datetime.now().timestamp())}",
    "data": {
        "instance_id": "$INSTANCE_ID",
        "name": "test-mcp-fetch",
        "server_spec_id": "fetch",
        "json_spec": {
            "type": "docker",
            "image": "mcp/fetch:latest",
            "slug": "$INSTANCE_ID",
            "port": 3000,
            "env_vars": {},
            "resource_limits": {
                "memory": "256m",
                "cpu": "0.5"
            }
        }
    }
}

r.publish("agentarea.events.mcp.instance.created", json.dumps(event))
print("✓ Event published")
PYEOF

# Step 5: Wait for container to start
echo ""
echo "=== Step 5: Waiting for container to start ==="
echo "Waiting up to 60 seconds..."

CONTAINER_ID=""
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
    echo ""
    echo "MCP Manager logs:"
    tail -100 /tmp/mcp-manager-e2e.log
    exit 1
fi

# Step 6: Verify container is healthy
echo ""
echo "=== Step 6: Verify container health ==="
sleep 5

CONTAINER_STATUS=$(docker inspect --format='{{.State.Status}}' "$CONTAINER_ID" 2>/dev/null)
if [ "$CONTAINER_STATUS" != "running" ]; then
    echo "ERROR: Container not running (status: $CONTAINER_STATUS)"
    echo "Container logs:"
    docker logs "$CONTAINER_ID" 2>&1 | tail -30 || true
    exit 1
fi
echo "✓ Container is running (status: $CONTAINER_STATUS)"

# Get container details
CONTAINER_IP=$(docker inspect --format='{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$CONTAINER_ID")
CONTAINER_PORT=$(docker inspect --format='{{range $k, $v := .NetworkSettings.Ports}}{{if $v}}{{(index $v 0).HostPort}}{{end}}{{end}}' "$CONTAINER_ID")
echo "  Container IP: $CONTAINER_IP"

# Step 7: Test proxy WITHOUT auth (should fail with 401)
echo ""
echo "=== Step 7: Test proxy WITHOUT auth ==="
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

# Step 8: Test proxy with WRONG auth (should fail with 401)
echo ""
echo "=== Step 8: Test proxy with WRONG auth ==="
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

# Step 9: Test proxy with CORRECT auth (should succeed or get valid MCP response)
echo ""
echo "=== Step 9: Test proxy with CORRECT auth (Bearer header) ==="
RESPONSE=$(curl -s -w "\nHTTP_CODE:%{http_code}" -H "Authorization: Bearer $MCP_SECRET" \
    --max-time 10 \
    "http://localhost:8080/mcp/$INSTANCE_ID/tools" 2>&1)
HTTP_CODE=$(echo "$RESPONSE" | grep "HTTP_CODE:" | cut -d: -f2)
BODY=$(echo "$RESPONSE" | grep -v "HTTP_CODE:")

echo "HTTP Status: $HTTP_CODE"
echo "Response: ${BODY:0:200}"

# MCP fetch server may return different responses, but auth should work
if [ "$HTTP_CODE" == "401" ] || [ "$HTTP_CODE" == "403" ]; then
    echo "ERROR: Auth failed even with correct token!"
    exit 1
fi
echo "✓ Request with correct Bearer auth allowed"

# Step 10: Test proxy with token query param
echo ""
echo "=== Step 10: Test proxy with token query param ==="
RESPONSE=$(curl -s -w "\nHTTP_CODE:%{http_code}" \
    --max-time 10 \
    "http://localhost:8080/mcp/$INSTANCE_ID/tools?token=$MCP_SECRET" 2>&1)
HTTP_CODE=$(echo "$RESPONSE" | grep "HTTP_CODE:" | cut -d: -f2)

echo "HTTP Status: $HTTP_CODE"
if [ "$HTTP_CODE" == "401" ] || [ "$HTTP_CODE" == "403" ]; then
    echo "ERROR: Query param auth failed!"
    exit 1
fi
echo "✓ Request with token query param allowed"

# Step 11: Test direct container access (for comparison)
echo ""
echo "=== Step 11: Test direct container access ==="
RESPONSE=$(curl -s -w "\nHTTP_CODE:%{http_code}" \
    --max-time 5 \
    "http://$CONTAINER_IP:3000/tools" 2>&1 || true)
HTTP_CODE=$(echo "$RESPONSE" | grep "HTTP_CODE:" | cut -d: -f2 || echo "000")
echo "Direct container access HTTP Status: $HTTP_CODE"

# Step 12: Cleanup
echo ""
echo "=== Step 12: Cleanup ==="

python3 << PYEOF
import redis
import json
from datetime import datetime, timezone

r = redis.Redis.from_url("$REDIS_URL")

event = {
    "specversion": "1.0",
    "type": "com.agentarea.mcp.instance.deleted",
    "source": "test/e2e",
    "id": f"evt-{int(datetime.now().timestamp())}-delete",
    "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "datacontenttype": "application/json",
    "correlationid": f"corr-{int(datetime.now().timestamp())}",
    "data": {
        "instance_id": "$INSTANCE_ID",
        "name": "test-mcp-fetch"
    }
}

r.publish("agentarea.events.mcp.instance.deleted", json.dumps(event))
print("✓ Delete event published")
PYEOF

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
echo "  - MCP image available"
echo "  - MCP Manager running with auth"
echo "  - MCP container instance created via Redis event"
echo "  - Container started and healthy"
echo "  - Unauthorized requests rejected (401)"
echo "  - Authorized requests allowed (Bearer token)"
echo "  - Query param auth working"
echo "  - Cleanup successful"

exit 0
