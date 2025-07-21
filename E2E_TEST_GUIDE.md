# AgentArea MCP End-to-End Test Guide

This guide will help you test the complete MCP workflow from frontend to container accessibility.

## 🎯 What This Test Validates

✅ **Frontend MCP Interface** - UI for creating/managing MCP servers  
✅ **API Integration** - Backend processing of MCP requests  
✅ **Status Transitions** - `pending` → `validating` → `starting` → `running`  
✅ **Event Flow** - Redis pub/sub between API and MCP Manager  
✅ **Container Creation** - Podman container orchestration  
✅ **Endpoint Accessibility** - MCP services reachable via proxy  

## 🚀 Quick Start (Automated)

Run the complete e2e test with one command:

```bash
./scripts/start_e2e_test.sh
```

This script will:
1. **Start all backend services** (API, Database, Redis, MCP Manager)
2. **Start the frontend** (Next.js on port 3000)
3. **Run automated tests** to verify the full workflow
4. **Keep services running** for manual testing

## 📋 Manual Testing Steps

After running the automated test, try these manual steps:

### 1. Open the Frontend
```
http://localhost:3000
```

### 2. Navigate to MCP Servers
- Go to **"MCP Servers"** section in the UI
- Click **"Add New MCP Server"**

### 3. Create a Test MCP Server
Use these settings:
- **Name**: `test-nginx`
- **Image**: `nginx:alpine`
- **Port**: `80`
- **Environment Variables**: (optional)
  ```
  NGINX_PORT=80
  ```

### 4. Watch Status Transitions
You should see the status change:
```
pending → validating → starting → running
```

### 5. Test MCP Endpoint
- Once status shows **"running"**, click on the server URL
- You should see the nginx welcome page
- URL format: `http://localhost:7999/mcp/{server-slug}`

## 🔧 Service Endpoints

While testing, these services are available:

| Service | URL | Purpose |
|---------|-----|---------|
| **Frontend** | http://localhost:3000 | Main UI |
| **API** | http://localhost:8000 | Backend API |
| **API Health** | http://localhost:8000/health | API status |
| **MCP Manager** | http://localhost:7999 | Container proxy |
| **MCP Health** | http://localhost:7999/health | MCP Manager status |
| **Database** | localhost:5432 | PostgreSQL |
| **Redis** | localhost:6379 | Event broker |

## 🐛 Troubleshooting

### API Not Starting
```bash
# Check API logs
docker-compose -f docker-compose.dev.yaml logs app

# Restart API only
docker-compose -f docker-compose.dev.yaml restart app
```

### MCP Manager Issues
```bash
# Check MCP Manager logs
docker-compose -f docker-compose.dev.yaml logs mcp-manager

# Test container creation manually
curl -X POST http://localhost:7999/api/mcp/instances \
  -H "Content-Type: application/json" \
  -d '{"name": "test", "image": "nginx:alpine", "port": 80}'
```

### Frontend Not Loading
```bash
# Check frontend logs
tail -f frontend.log

# Restart frontend
cd frontend && npm run dev
```

### Status Stuck on "pending"
This was the main issue we fixed! If it still happens:

1. **Check Redis connectivity**:
   ```bash
   redis-cli ping
   ```

2. **Check event publishing**:
   ```bash
   redis-cli monitor
   # Then create an MCP instance and watch for events
   ```

3. **Check MCP Manager logs**:
   ```bash
   docker logs mcp-manager
   ```

## 🧹 Cleanup

Stop all services:
```bash
# Automatic (if using start script)
Ctrl+C

# Manual
docker-compose -f docker-compose.dev.yaml down
```

## 📊 Expected Test Results

When everything works correctly, you should see:

```
🎯 AgentArea E2E MCP Test Starting...
🔍 Verifying infrastructure...
✅ API is healthy
✅ MCP Manager is healthy  
✅ Redis is healthy
📝 Creating MCP instance...
✅ MCP instance created: e2e-test-instance
👀 Monitoring status transitions...
📊 Status update: validating
📊 Status update: starting
📊 Status update: running
✅ Container reached running status
🌐 Verifying MCP endpoint accessibility...
🔗 Testing MCP endpoint: http://localhost:7999/mcp/e2e-nginx-test-xyz
✅ MCP endpoint is accessible
🧪 Testing MCP functionality...
✅ MCP functionality verified (nginx serving pages)
🧹 Cleaning up test instance...
✅ Test instance cleaned up
✅ E2E Test Completed Successfully!
🎉 All tests passed! Your MCP infrastructure is working correctly.
```

## 🎉 Success Criteria

Your MCP infrastructure is working if:

- [x] Frontend loads and shows MCP interface
- [x] MCP instances can be created via UI
- [x] Status transitions from "pending" to "running" 
- [x] MCP endpoints are accessible via URLs
- [x] Containers serve content correctly
- [x] Cleanup works properly

That's it! Your AgentArea MCP infrastructure is fully functional! 🚀 