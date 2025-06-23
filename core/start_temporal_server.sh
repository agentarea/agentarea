#!/bin/bash

# Start Temporal Server for AgentArea Development
echo "🚀 Starting Temporal Server for AgentArea..."
echo ""
echo "This will start Temporal server on localhost:7233"
echo "Web UI will be available at http://localhost:8080"
echo ""

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    echo "❌ Error: Docker is not running. Please start Docker first."
    exit 1
fi

echo "📦 Starting Temporal server with auto-setup..."

# Start Temporal with auto-setup
docker run --rm -p 7233:7233 -p 8080:8080 temporalio/temporal-auto-setup:latest

echo ""
echo "✅ Temporal server stopped" 