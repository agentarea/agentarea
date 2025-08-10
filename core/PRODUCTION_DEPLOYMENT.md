# Production Deployment Guide

This guide explains the best practices for deploying AgentArea in production with optimal connection management.

## Connection Management Strategy

AgentArea uses a **thread-safe singleton pattern** that provides:

### Key Benefits
- **Connection Reuse**: Redis and Temporal connections are reused across HTTP requests
- **Thread Safety**: Proper locking ensures safe concurrent access
- **Automatic Cleanup**: Proper resource cleanup on application shutdown
- **Health Monitoring**: Built-in health checks for connection status
- **Environment Awareness**: Adapts behavior based on environment

### How It Works
1. **First Request**: Creates singleton connections to Redis and Temporal
2. **Subsequent Requests**: Reuses existing connections (no overhead)
3. **Application Shutdown**: Properly closes all connections
4. **Health Checks**: Monitors connection status via `/health` endpoint

## Environment Configuration

The connection manager automatically detects the environment:

```bash
export ENVIRONMENT=production  # Optional: enables production logging
```

Or in your `.env` file:
```
ENVIRONMENT=production
```

## Production Features

AgentArea provides production-ready connection management:

### 1. Connection Reuse
- **Redis**: Single EventBroker instance reused across requests
- **Temporal**: Single ExecutionService instance with persistent client
- **Database**: SQLAlchemy async connection pooling (built-in)

### 2. Health Monitoring
- `/health` endpoint shows connection status
- Real-time monitoring of service availability
- Connection reuse metrics

### 3. Resource Management
- Thread-safe singleton pattern
- Proper cleanup on shutdown
- Memory-efficient resource usage

### 4. Monitoring Endpoints
- `/health` - Overall application health including connection status
- Connection reuse statistics

## Configuration Options

### Connection Settings
The connection manager uses sensible defaults that work well for most production scenarios:

```python
# Automatic configuration based on environment
class ConnectionManager:
    # Thread-safe singleton pattern
    # Automatic connection reuse
    # Proper cleanup on shutdown
    # Health monitoring built-in
```

### Advanced Configuration
For high-load scenarios, you can extend the connection manager:

```python
# Custom connection pooling (if needed)
# - Implement connection pools for specific use cases
# - Add circuit breakers for fault tolerance
# - Implement custom retry logic
# - Add detailed metrics collection
```

## Deployment Recommendations

### 1. Container Deployment
```dockerfile
# Set production environment
ENV ENVIRONMENT=production

# Optimize for production
ENV PYTHONOPTIMIZE=1
ENV PYTHONUNBUFFERED=1
```

### 2. Kubernetes Deployment
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agentarea-api
spec:
  template:
    spec:
      containers:
      - name: api
        env:
        - name: ENVIRONMENT
          value: "production"
        # Health check configuration
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
```

### 3. Load Balancer Configuration
```nginx
upstream agentarea_api {
    server api1:8000;
    server api2:8000;
    
    # Health checks
    health_check uri=/health;
}
```

## Monitoring

### Health Check Response
```json
{
  "status": "healthy",
  "service": "agentarea-api",
  "version": "0.1.0",
  "connections": {
    "environment": "development",
    "status": "healthy",
    "services": {
      "event_broker": "initialized",
      "execution_service": "initialized"
    },
    "connection_reuse": true,
    "singleton_pattern": true
  },
  "timestamp": "2025-01-07T12:00:00Z"
}
```

### Metrics to Monitor
- Connection pool utilization
- Health check success rate
- Average connection acquisition time
- Error rates and recovery times

## Troubleshooting

### Connection Issues
1. Check `/health` endpoint for service status
2. Review logs for connection errors
3. Verify Redis/Temporal connectivity
4. Check resource limits and scaling

### Performance Optimization
1. Adjust connection pool sizes based on load
2. Monitor connection acquisition times
3. Tune health check intervals
4. Consider horizontal scaling

## Migration from Development

To migrate from development to production:

1. Set `ENVIRONMENT=production`
2. Review connection pool settings
3. Update monitoring and alerting
4. Test health check endpoints
5. Verify graceful shutdown behavior

The system will automatically handle the transition and optimize connections for production use.