# MCP Service Testing Guide

This directory contains comprehensive test scripts to verify the MCP (Model Context Protocol) hosting service functionality across both Docker and Kubernetes backends.

## Test Scripts Overview

### 1. `test_mcp.sh` - Complete Test Runner
**Recommended for quick testing**

A bash script that handles the entire test lifecycle:
- Builds the service
- Starts it with proper configuration  
- Runs tests
- Cleans up automatically

```bash
# Run complete test suite
./test_mcp.sh test

# Other useful commands
./test_mcp.sh build           # Just build
./test_mcp.sh start          # Start service (runs until Ctrl+C)
./test_mcp.sh health         # Check if service is healthy
./test_mcp.sh logs           # Show recent logs
./test_mcp.sh stop           # Stop running service
```

### 2. `simple_test.py` - Lightweight API Tests
**No external dependencies - uses only Python standard library**

Tests core functionality:
- Service health checks
- Instance lifecycle (create, get, delete)
- Monitoring endpoints
- Validation
- Legacy endpoint compatibility

```bash
# Run against local service
python3 simple_test.py

# Run against remote service
python3 simple_test.py --host production.example.com --port 443 --protocol https

# Custom timeout
python3 simple_test.py --timeout 60
```

### 3. `test_mcp_service.py` - Comprehensive Test Suite
**Requires `requests` library - more detailed testing**

Advanced testing with:
- Detailed error reporting
- Instance readiness waiting
- Resource validation
- Backend-specific behavior testing

```bash
# Install dependencies
pip install requests

# Run comprehensive tests
python3 test_mcp_service.py

# Test specific backend type
python3 test_mcp_service.py --backend kubernetes

# Include legacy endpoint testing
python3 test_mcp_service.py --legacy
```

## Quick Start

### Option 1: Automated Testing (Recommended)
```bash
# Clone and navigate to the project
cd mcp-infrastructure/go-mcp-manager

# Run the complete test suite
./test_mcp.sh test
```

### Option 2: Manual Testing
```bash
# Build and start the service
go build ./cmd/mcp-manager
./mcp-manager &

# Run tests in another terminal
python3 simple_test.py

# Stop the service
pkill mcp-manager
```

## What the Tests Verify

### Core Functionality
- ✅ Service health and readiness
- ✅ Instance creation with proper specifications
- ✅ Instance status tracking and updates
- ✅ Instance deletion and cleanup
- ✅ Resource limits and configuration
- ✅ Environment variable handling

### Backend-Specific Behavior
- ✅ **Docker Backend**: Container management via Podman
- ✅ **Kubernetes Backend**: Native K8s resources (Deployments, Services, Ingress)
- ✅ **Environment Detection**: Automatic backend selection

### API Endpoints
- ✅ `GET /health` - Service health check
- ✅ `GET /instances` - List all instances
- ✅ `POST /instances` - Create new instance
- ✅ `GET /instances/{id}` - Get instance details
- ✅ `PUT /instances/{id}` - Update instance
- ✅ `DELETE /instances/{id}` - Delete instance
- ✅ `POST /instances/validate` - Validate instance spec
- ✅ `GET /instances/{id}/health` - Instance health check
- ✅ `GET /monitoring/status` - Overall monitoring status

### Legacy Compatibility
- ✅ `GET /containers` - Legacy container listing (Docker backend only)
- ✅ Backward compatibility with existing clients

## Test Instance Specifications

The tests use a simple nginx-based test instance:

```json
{
  "instance_id": "test-12345678",
  "name": "test-mcp-instance",
  "service_name": "test-service",
  "image": "nginx:alpine",
  "port": 80,
  "environment": {
    "TEST_MODE": "true"
  },
  "workspace_id": "test-workspace",
  "resources": {
    "requests": {
      "cpu": "100m",
      "memory": "128Mi"
    },
    "limits": {
      "cpu": "200m",
      "memory": "256Mi"
    }
  }
}
```

## Environment Configuration

The test scripts can be configured via environment variables:

```bash
# Service connection
export SERVICE_HOST="localhost"
export SERVICE_PORT="8000"

# Backend selection (for service)
export BACKEND_ENVIRONMENT="docker"     # or "kubernetes"
export KUBERNETES_ENABLED="true"       # for K8s backend

# Logging
export LOG_LEVEL="DEBUG"
export LOG_FORMAT="json"

# CORS (for web testing)
export CORS_ENABLED="true"
```

## Expected Test Results

### Successful Test Run
```
[INFO] Starting MCP Service tests against http://localhost:8000
============================================================
--- Service Health ---
✅ PASS Health endpoint accessibility
✅ PASS Service health status: Status: healthy
✅ PASS Version field present: Version: 0.1.0

--- Instance Lifecycle ---
✅ PASS Instance creation: Instance ID: test-12345678
✅ PASS Get instance details
✅ PASS Instance health check: Status: 200
✅ PASS Instance cleanup

============================================================
TEST SUMMARY
============================================================
Total Tests: 15
Passed: 15 ✅
Failed: 0 ❌
Success Rate: 100.0%
Duration: 12.34s
============================================================
🎉 All tests passed!
```

## Troubleshooting

### Service Won't Start
```bash
# Check if port is already in use
lsof -i :8000

# Check service logs
./test_mcp.sh logs

# Try different port
SERVICE_PORT=8001 ./test_mcp.sh test
```

### Tests Fail
```bash
# Run with more verbose logging
LOG_LEVEL=DEBUG ./test_mcp.sh test

# Test service health manually
curl http://localhost:8000/health

# Check for missing dependencies
python3 -c "import requests" || pip install requests
```

### Docker Backend Issues
```bash
# Check if Podman/Docker is running
podman version
# or
docker version

# Check container runtime
podman ps
```

### Kubernetes Backend Issues
```bash
# Check if kubectl is configured
kubectl cluster-info

# Verify namespace access
kubectl get ns

# Force Kubernetes backend
export BACKEND_ENVIRONMENT="kubernetes"
```

## Integration with CI/CD

The test scripts are designed to work in CI/CD environments:

```yaml
# GitHub Actions example
- name: Test MCP Service
  run: |
    cd mcp-infrastructure/go-mcp-manager
    ./test_mcp.sh test

# Exit codes:
# 0 = All tests passed
# 1 = Some tests failed
# 130 = Interrupted by user
```

## Extending the Tests

To add new tests, modify the test scripts:

1. **Simple tests**: Add new methods to `SimpleMCPTester` class
2. **Comprehensive tests**: Add new methods to `MCPServiceTester` class
3. **Update test runner**: Add new test cases to the main test sequence

Example new test:
```python
def test_custom_functionality(self):
    """Test custom MCP functionality"""
    response = self.make_request('GET', '/custom-endpoint')
    
    success = self.test_assert(
        response['status_code'] == 200,
        "Custom endpoint test"
    )
    
    return success
```

## Performance Testing

For load testing, consider using tools like:
- `ab` (Apache Bench): `ab -n 1000 -c 10 http://localhost:8000/health`
- `wrk`: `wrk -t12 -c400 -d30s http://localhost:8000/health`
- Custom Python scripts with concurrent requests

The test scripts focus on functional correctness rather than performance, but provide a foundation for performance testing.