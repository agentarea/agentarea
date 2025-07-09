#!/bin/bash

# AgentArea E2E Test Startup Script
# This script starts all services and runs end-to-end tests

set -e

echo "🚀 Starting AgentArea E2E Test Environment"
echo "==========================================="

# Function to check if a service is healthy
check_service() {
    local name=$1
    local url=$2
    local timeout=${3:-30}
    
    echo "⏳ Waiting for $name to be ready..."
    for i in $(seq 1 $timeout); do
        if curl -s "$url" > /dev/null 2>&1; then
            echo "✅ $name is ready"
            return 0
        fi
        echo "   Attempt $i/$timeout - waiting..."
        sleep 2
    done
    echo "❌ $name failed to start within $timeout attempts"
    return 1
}

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "🧹 Cleaning up..."
    if [ "$FRONTEND_PID" != "" ]; then
        echo "Stopping frontend (PID: $FRONTEND_PID)"
        kill $FRONTEND_PID 2>/dev/null || true
    fi
    
    echo "Stopping backend services..."
    docker-compose -f docker-compose.dev.yaml down
    
    echo "✅ Cleanup completed"
}

# Trap to ensure cleanup on script exit
trap cleanup EXIT INT TERM

# Step 1: Start backend infrastructure
echo ""
echo "📦 Starting backend infrastructure..."
echo "This includes: API, Database, Redis, MCP Manager, etc."

# Build and start services
docker-compose -f docker-compose.dev.yaml build --no-cache mcp-manager
docker-compose -f docker-compose.dev.yaml up -d

echo "⏳ Waiting for infrastructure to be ready..."

# Check each service
check_service "Database" "http://localhost:5432" 10 || true  # DB doesn't have HTTP endpoint
check_service "Redis" "http://localhost:6379" 10 || true    # Redis doesn't have HTTP endpoint  
check_service "API" "http://localhost:8000/health" 20
check_service "MCP Manager" "http://localhost:7999/health" 15

echo ""
echo "✅ Backend infrastructure is ready!"

# Step 2: Start frontend
echo ""
echo "🌐 Starting frontend..."
cd frontend

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo "📦 Installing frontend dependencies..."
    npm install
fi

# Start frontend in background
echo "🚀 Starting Next.js development server..."
npm run dev > ../frontend.log 2>&1 &
FRONTEND_PID=$!

cd ..

# Wait for frontend to be ready
check_service "Frontend" "http://localhost:3000" 15

echo ""
echo "✅ Frontend is ready!"

# Step 3: Install Python dependencies for e2e test
echo ""
echo "🐍 Installing Python test dependencies..."
pip install requests redis 2>/dev/null || echo "⚠️ pip install failed - continuing anyway"

# Step 4: Run e2e test
echo ""
echo "🧪 Running E2E Tests..."
echo "========================"

python3 scripts/test_e2e.py

# Step 5: Instructions for manual testing
echo ""
echo "🎉 E2E Test Completed!"
echo ""
echo "💡 For manual testing, these services are now running:"
echo "   📊 Frontend:     http://localhost:3000"
echo "   🔧 API:          http://localhost:8000"
echo "   📈 MCP Manager:  http://localhost:7999"
echo "   🗄️  Database:     localhost:5432"
echo "   📮 Redis:        localhost:6379"
echo ""
echo "🔗 To test the UI manually:"
echo "   1. Open http://localhost:3000 in your browser"
echo "   2. Navigate to MCP Servers section"
echo "   3. Add a new MCP server (try nginx:alpine)"
echo "   4. Watch the status transition from 'pending' to 'running'"
echo "   5. Click on the server URL to test accessibility"
echo ""
echo "⚠️  Note: Services will continue running until you stop this script (Ctrl+C)"
echo "    Or run: docker-compose -f docker-compose.dev.yaml down"

# Keep services running and wait for user input
echo ""
echo "🔄 Services are running. Press Ctrl+C to stop all services..."
wait 