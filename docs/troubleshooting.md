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