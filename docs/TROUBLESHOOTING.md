# AgentArea Troubleshooting Guide

## 🚨 Quick Diagnostics

### Health Check Commands
```bash
# Check all services
docker compose -f docker-compose.dev.yaml ps

# Check service health
curl http://localhost:8000/health
curl http://localhost:7999/health

# Check logs
docker compose -f docker-compose.dev.yaml logs -f
```

### Service Status Overview
| Service | Port | Health Check | Expected Response |
|---------|------|--------------|------------------|
| Core API | 8000 | `curl http://localhost:8000/health` | `{"status": "healthy"}` |
| MCP Manager | 7999 | `curl http://localhost:7999/health` | `{"status": "healthy"}` |
| Traefik | 8080 | `curl http://localhost:8080/api/rawdata` | JSON response |
| Database | 5432 | Internal | Check via app logs |
| Redis | 6379 | Internal | Check via app logs |
| MinIO | 9000 | `curl http://localhost:9000/minio/health/live` | 200 OK |

## 🔧 Common Issues

### 1. Services Won't Start

#### Symptoms
- `docker compose up` fails
- Services exit immediately
- Port binding errors

#### Diagnosis
```bash
# Check Docker daemon
docker info

# Check port conflicts
lsof -i :8000
lsof -i :7999
lsof -i :8080

# Check Docker Compose file
docker compose -f docker-compose.dev.yaml config
```

#### Solutions

**Port Conflicts:**
```bash
# Kill processes using ports
sudo lsof -ti:8000 | xargs kill -9
sudo lsof -ti:7999 | xargs kill -9

# Or change ports in docker-compose.dev.yaml
```

**Docker Issues:**
```bash
# Restart Docker daemon
sudo systemctl restart docker  # Linux
# Or restart Docker Desktop on macOS/Windows

# Clean Docker system
docker system prune -a
docker volume prune
```

**Permission Issues:**
```bash
# Fix file permissions
sudo chown -R $USER:$USER .
chmod -R 755 .

# Or run with sudo (not recommended)
sudo docker compose -f docker-compose.dev.yaml up -d
```

### 2. Database Connection Errors

#### Symptoms
- "Connection refused" errors
- Migration failures
- App can't connect to database

#### Diagnosis
```bash
# Check database logs
docker compose -f docker-compose.dev.yaml logs db

# Test database connection
docker compose -f docker-compose.dev.yaml exec db psql -U agentarea -d agentarea -c "SELECT 1;"

# Check database container status
docker compose -f docker-compose.dev.yaml ps db
```

#### Solutions

**Database Not Ready:**
```bash
# Wait for database to start (30-60 seconds)
sleep 30

# Check if database is accepting connections
docker compose -f docker-compose.dev.yaml exec db pg_isready -U agentarea
```

**Connection String Issues:**
```bash
# Check environment variables
docker compose -f docker-compose.dev.yaml exec app env | grep DATABASE

# Verify .env file
cat .env | grep DATABASE
```

**Reset Database:**
```bash
# Complete database reset (DESTRUCTIVE)
docker compose -f docker-compose.dev.yaml down -v
docker compose -f docker-compose.dev.yaml up -d db
# Wait 30 seconds
docker compose -f docker-compose.dev.yaml up -d
```

### 3. Migration Issues

#### Symptoms
- Alembic migration errors
- "Revision not found" errors
- Database schema mismatches

#### Diagnosis
```bash
# Check current migration status
docker compose -f docker-compose.dev.yaml run --rm app alembic current

# Check migration history
docker compose -f docker-compose.dev.yaml run --rm app alembic history

# Check for migration conflicts
docker compose -f docker-compose.dev.yaml run --rm app alembic branches
```

#### Solutions

**Run Migrations:**
```bash
# Apply all pending migrations
docker compose -f docker-compose.dev.yaml run --rm app alembic upgrade head

# Downgrade to specific revision
docker compose -f docker-compose.dev.yaml run --rm app alembic downgrade <revision>
```

**Reset Migration State:**
```bash
# Mark current state as head (DANGEROUS)
docker compose -f docker-compose.dev.yaml run --rm app alembic stamp head

# Complete reset (DESTRUCTIVE)
docker compose -f docker-compose.dev.yaml down -v
docker compose -f docker-compose.dev.yaml up -d
```

### 4. Module Import Errors

#### Symptoms
- `ModuleNotFoundError`
- Import path issues
- Python package not found

#### Diagnosis
```bash
# Check Python path
docker compose -f docker-compose.dev.yaml exec app python -c "import sys; print('\n'.join(sys.path))"

# Check installed packages
docker compose -f docker-compose.dev.yaml exec app pip list

# Check if module exists
docker compose -f docker-compose.dev.yaml exec app find /app -name "*.py" | grep module_name
```

#### Solutions

**Rebuild Containers:**
```bash
# Rebuild without cache
docker compose -f docker-compose.dev.yaml build --no-cache
docker compose -f docker-compose.dev.yaml up -d
```

**Install Dependencies:**
```bash
# Install missing packages
docker compose -f docker-compose.dev.yaml exec app pip install package_name

# Or rebuild with updated requirements
docker compose -f docker-compose.dev.yaml build app
```

### 5. MCP Server Issues

#### Symptoms
- MCP servers not starting
- "Server not found" errors
- MCP communication failures

#### Diagnosis
```bash
# Check MCP server status
curl http://localhost:8000/v1/mcp-servers/

# Check MCP manager logs
docker compose -f docker-compose.dev.yaml logs mcp-manager

# Test MCP server directly
curl http://localhost:81/mcp/server-slug/mcp/
```

#### Solutions

**Restart MCP Services:**
```bash
# Restart MCP manager
docker compose -f docker-compose.dev.yaml restart mcp-manager

# Restart specific MCP server via API
curl -X POST http://localhost:8000/v1/mcp-servers/server-id/restart
```

**Check MCP Configuration:**
```bash
# Verify MCP server config
docker compose -f docker-compose.dev.yaml exec app python -c "from core.config import settings; print(settings.MCP_SERVERS)"
```

### 6. Authentication Issues

#### Symptoms
- 401 Unauthorized errors
- Token validation failures
- Login not working

#### Diagnosis
```bash
# Test login endpoint
curl -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "test", "password": "test"}'

# Check auth configuration
docker compose -f docker-compose.dev.yaml exec app env | grep AUTH
```

#### Solutions

**Reset Auth State:**
```bash
# Clear Redis sessions
docker compose -f docker-compose.dev.yaml exec redis redis-cli FLUSHALL

# Restart auth services
docker compose -f docker-compose.dev.yaml restart app
```

### 7. Performance Issues

#### Symptoms
- Slow API responses
- High memory usage
- CPU spikes

#### Diagnosis
```bash
# Check resource usage
docker stats

# Check API response times
time curl http://localhost:8000/health

# Check database performance
docker compose -f docker-compose.dev.yaml exec db psql -U agentarea -d agentarea -c "SELECT * FROM pg_stat_activity;"
```

#### Solutions

**Resource Optimization:**
```bash
# Increase Docker memory limits
# Edit Docker Desktop settings or docker-compose.dev.yaml

# Clean up unused resources
docker system prune
docker volume prune
```

## 🔍 Advanced Debugging

### Enable Debug Logging
```bash
# Set debug environment variables
echo "LOG_LEVEL=DEBUG" >> .env
echo "DEBUG=true" >> .env

# Restart services
docker compose -f docker-compose.dev.yaml restart
```

### Database Debugging
```bash
# Connect to database
docker compose -f docker-compose.dev.yaml exec db psql -U agentarea -d agentarea

# Check table structure
\dt
\d table_name

# Check recent queries
SELECT query, state, query_start FROM pg_stat_activity WHERE state = 'active';
```

### Network Debugging
```bash
# Check Docker networks
docker network ls
docker network inspect agentarea_default

# Test internal connectivity
docker compose -f docker-compose.dev.yaml exec app ping db
docker compose -f docker-compose.dev.yaml exec app ping redis
```

### File System Debugging
```bash
# Check file permissions
docker compose -f docker-compose.dev.yaml exec app ls -la /app

# Check disk space
docker compose -f docker-compose.dev.yaml exec app df -h

# Check mounted volumes
docker compose -f docker-compose.dev.yaml exec app mount | grep /app
```

## 🚨 Emergency Procedures

### Complete System Reset
```bash
# WARNING: This will destroy all data
docker compose -f docker-compose.dev.yaml down -v
docker system prune -a
docker volume prune

# Remove all AgentArea containers and images
docker ps -a | grep agentarea | awk '{print $1}' | xargs docker rm -f
docker images | grep agentarea | awk '{print $3}' | xargs docker rmi -f

# Start fresh
docker compose -f docker-compose.dev.yaml up -d
```

### Backup and Restore
```bash
# Backup database
docker compose -f docker-compose.dev.yaml exec db pg_dump -U agentarea agentarea > backup.sql

# Restore database
docker compose -f docker-compose.dev.yaml exec -T db psql -U agentarea -d agentarea < backup.sql

# Backup volumes
docker run --rm -v agentarea_db_data:/data -v $(pwd):/backup alpine tar czf /backup/db_backup.tar.gz /data
```

## 📊 Monitoring and Logs

### Log Locations
```bash
# Application logs
docker compose -f docker-compose.dev.yaml logs app

# Database logs
docker compose -f docker-compose.dev.yaml logs db

# MCP Manager logs
docker compose -f docker-compose.dev.yaml logs mcp-manager

# All logs with timestamps
docker compose -f docker-compose.dev.yaml logs -f -t
```

### Log Analysis
```bash
# Filter error logs
docker compose -f docker-compose.dev.yaml logs app 2>&1 | grep -i error

# Search for specific patterns
docker compose -f docker-compose.dev.yaml logs app 2>&1 | grep "database"

# Export logs to file
docker compose -f docker-compose.dev.yaml logs app > app.log
```

### Health Monitoring
```bash
# Continuous health check
watch -n 5 'curl -s http://localhost:8000/health | jq .'

# Monitor resource usage
watch -n 2 'docker stats --no-stream'
```

## 🆘 Getting Help

### Information to Gather
When reporting issues, include:

1. **System Information:**
   ```bash
   uname -a
   docker --version
   docker compose version
   ```

2. **Service Status:**
   ```bash
   docker compose -f docker-compose.dev.yaml ps
   ```

3. **Recent Logs:**
   ```bash
   docker compose -f docker-compose.dev.yaml logs --tail=50
   ```

4. **Configuration:**
   ```bash
   cat .env | grep -v PASSWORD | grep -v SECRET
   ```

### Support Channels
- **Documentation**: [Documentation Index](DOCUMENTATION_INDEX.md)
- **API Reference**: [API Reference](API_REFERENCE.md)
- **Architecture**: [System Architecture](../core/docs/SYSTEM_ARCHITECTURE.md)
- **Team Support**: Contact development team

### Known Issues
- **Issue #1**: MCP servers may take 30-60 seconds to start
- **Issue #2**: Database migrations require manual intervention on schema conflicts
- **Issue #3**: WebSocket connections may timeout after 5 minutes of inactivity

---

*Troubleshooting guide last updated: January 2025*
*For additional help, refer to the [Getting Started Guide](GETTING_STARTED.md) or contact the development team.*