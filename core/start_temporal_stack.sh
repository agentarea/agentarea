#!/bin/bash

# Temporal Stack Startup Script
# This script starts the complete Temporal + AgentArea stack

set -e

echo "🚀 Starting Temporal + AgentArea Stack"
echo "======================================"

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Check if docker-compose is available
if ! command -v docker-compose > /dev/null 2>&1; then
    echo "❌ docker-compose not found. Please install docker-compose."
    exit 1
fi

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p temporal-config
mkdir -p logs

# Stop any existing containers
echo "🛑 Stopping existing containers..."
docker-compose -f docker-compose.temporal.yml down --remove-orphans || true

# Clean up volumes (optional - comment out to preserve data)
echo "🧹 Cleaning up volumes..."
docker-compose -f docker-compose.temporal.yml down -v || true

# Pull latest images
echo "📥 Pulling latest images..."
docker-compose -f docker-compose.temporal.yml pull

# Start the stack
echo "🚀 Starting Temporal stack..."
docker-compose -f docker-compose.temporal.yml up -d temporal-postgresql temporal

# Wait for PostgreSQL to be ready
echo "⏳ Waiting for PostgreSQL to be ready..."
sleep 10

# Start Temporal server
echo "🚀 Starting Temporal server..."
docker-compose -f docker-compose.temporal.yml up -d temporal

# Wait for Temporal to be ready
echo "⏳ Waiting for Temporal server to be ready..."
sleep 15

# Check Temporal health
echo "🩺 Checking Temporal health..."
max_retries=30
retry_count=0

while [ $retry_count -lt $max_retries ]; do
    if curl -s http://localhost:7233/api/v1/namespaces > /dev/null 2>&1; then
        echo "✅ Temporal server is healthy!"
        break
    else
        echo "⏳ Waiting for Temporal... (attempt $((retry_count + 1))/$max_retries)"
        sleep 2
        retry_count=$((retry_count + 1))
    fi
done

if [ $retry_count -eq $max_retries ]; then
    echo "❌ Temporal server failed to start properly"
    echo "📋 Checking logs..."
    docker-compose -f docker-compose.temporal.yml logs temporal
    exit 1
fi

# Start Temporal UI
echo "🚀 Starting Temporal Web UI..."
docker-compose -f docker-compose.temporal.yml up -d temporal-ui

# Start AgentArea services
echo "🚀 Starting AgentArea services..."
docker-compose -f docker-compose.temporal.yml up -d redis agentarea-db

# Wait for databases to be ready
echo "⏳ Waiting for databases to be ready..."
sleep 10

# Start AgentArea core service
echo "🚀 Starting AgentArea core service..."
docker-compose -f docker-compose.temporal.yml up -d agentarea-core

# Start AgentArea worker
echo "🚀 Starting AgentArea worker..."
docker-compose -f docker-compose.temporal.yml up -d agentarea-worker

# Wait for services to stabilize
echo "⏳ Waiting for services to stabilize..."
sleep 10

# Show status
echo ""
echo "📊 Service Status:"
echo "=================="
docker-compose -f docker-compose.temporal.yml ps

echo ""
echo "🔗 Service URLs:"
echo "==============="
echo "Temporal Web UI:    http://localhost:8080"
echo "AgentArea API:      http://localhost:8000"
echo "Temporal Server:    localhost:7233"
echo "PostgreSQL (AgentArea): localhost:5432"
echo "PostgreSQL (Temporal):  localhost:5433"
echo "Redis:              localhost:6379"

echo ""
echo "🧪 Running integration tests..."
echo "==============================="

# Run integration test
if docker exec agentarea-core python test_temporal_docker.py; then
    echo ""
    echo "🎉 Stack started successfully!"
    echo "✅ All services are running and tests passed"
else
    echo ""
    echo "⚠️ Stack started but tests failed"
    echo "📋 Check logs for issues:"
    echo "  docker-compose -f docker-compose.temporal.yml logs agentarea-core"
    echo "  docker-compose -f docker-compose.temporal.yml logs agentarea-worker"
fi

echo ""
echo "📋 Useful commands:"
echo "=================="
echo "View logs:          docker-compose -f docker-compose.temporal.yml logs -f [service]"
echo "Stop stack:         docker-compose -f docker-compose.temporal.yml down"
echo "Restart service:    docker-compose -f docker-compose.temporal.yml restart [service]"
echo "Run tests:          docker exec agentarea-core python test_temporal_docker.py"
echo "Shell into core:    docker exec -it agentarea-core bash"

echo ""
echo "🎯 Next steps:"
echo "============="
echo "1. Open Temporal UI: http://localhost:8080"
echo "2. Test the API: curl http://localhost:8000/api/v1/health"
echo "3. Run integration tests: python tests/integration/test_temporal_workflow_integration.py" 