# MCP Manager State Synchronization Architecture

## Overview

The MCP Manager uses a **reconciliation loop** pattern to ensure the actual state (Kubernetes resources) always matches the desired state (database records). This handles:

- **Startup recovery**: Recreates resources after cluster restart
- **Manual deletions**: Detects and recreates resources deleted by users
- **Crash recovery**: Handles partial failures and inconsistent states
- **Orphaned resources**: Identifies and cleans up resources without DB records

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Database      │     │   Reconciler     │     │   Kubernetes    │
│  (Desired State)│◄────┤   (Sync Loop)    ├────►│ (Actual State)  │
└─────────────────┘     └──────────────────┘     └─────────────────┘
         │                       │                       │
         │                       ▼                       │
         │              ┌──────────────────┐            │
         │              │   Watchers       │            │
         │              │  (Real-time)     │◄───────────┘
         │              └──────────────────┘
         │                       │
         ▼                       ▼
┌─────────────────────────────────────────────────────────┐
│                  Sync Results / Status                   │
└─────────────────────────────────────────────────────────┘
```

## Components

### 1. Reconciler (`internal/reconciler/`)

The core reconciliation engine that runs continuously.

**Features:**
- **Startup Sync**: On boot, checks all MCP instances and recreates missing resources
- **Periodic Sync**: Full reconciliation every 5 minutes (configurable)
- **Auto-recreate**: Automatically recreates missing resources
- **Auto-cleanup**: Optionally removes orphaned resources (disabled by default)

**States:**
| State | Description | Action |
|-------|-------------|--------|
| `synced` | DB and K8s match | None |
| `missing` | In DB, no K8s resources | Recreate if autoRecreate=true |
| `orphaned` | K8s exists, no DB record | Report/Cleanup if autoCleanup=true |
| `mismatch` | Resources unhealthy | Report/Recreate |
| `recreating` | Recreation in progress | Wait |

### 2. Watchers (`startWatchers()`)

Real-time K8s resource monitoring using informers.

**Monitored Resources:**
- Deployments
- Services
- HTTPRoutes (if Gateway API enabled)

**Behavior:**
- Detects deletions within seconds
- Triggers immediate reconciliation
- Batches rapid changes (5-second delay)

### 3. Repository (`internal/repository/`)

Database access layer for MCP instances.

**Methods:**
- `GetAll()` - All active MCP instances
- `GetByID()` - Single instance lookup
- `UpdateStatus()` - Update instance status
- `GetByStatus()` - Filter by status

## Configuration

```go
config := reconciler.Config{
    SyncInterval: 5 * time.Minute,  // How often to sync
    StartupSync:  true,             // Sync on startup
    AutoRecreate: true,             // Auto-recreate missing resources
    AutoCleanup:  false,            // Auto-delete orphaned resources (dangerous!)
    MaxResults:   100,              // Sync history to keep
}
```

## API Endpoints

### Get Sync Status
```bash
GET /reconcile/status

Response:
{
  "lastSync": "2026-02-19T16:00:00Z",
  "duration": 2.5,
  "totalInstances": 10,
  "synced": 8,
  "missing": 1,
  "orphaned": 1,
  "mismatch": 0,
  "recreated": 1,
  "errors": 0
}
```

### Trigger Manual Sync
```bash
POST /reconcile/trigger

Response:
{
  "status": "triggered",
  "message": "Reconciliation started in background"
}
```

### Get Recent Results
```bash
GET /reconcile/results?limit=20

Response:
{
  "results": [
    {
      "instanceId": "uuid",
      "instanceName": "my-mcp",
      "state": "synced",
      "message": "All resources healthy",
      "timestamp": "2026-02-19T16:00:00Z"
    }
  ],
  "count": 1
}
```

### Get Instance Status
```bash
GET /reconcile/instances/{name}

Response:
{
  "instanceId": "uuid",
  "instanceName": "my-mcp",
  "state": "synced",
  "message": "All resources healthy",
  "timestamp": "2026-02-19T16:00:00Z"
}
```

## Scenarios Handled

### 1. Cluster Restart

**Before:**
```
DB: my-mcp (status: running)
K8s: No resources (cluster restarted)
```

**After Startup Sync:**
```
DB: my-mcp (status: running)
K8s: Deployment, Service created
Log: "Recreating K8s resources: my-mcp"
```

### 2. Manual Resource Deletion

**User deletes deployment:**
```bash
kubectl delete deployment mcp-my-mcp -n mcp-system
```

**Watcher detects deletion:**
```
Log: "Detected K8s resource deletion: type=deployment"
Log: "Starting full reconciliation"
...
Log: "Recreating K8s resources: my-mcp"
```

### 3. Orphaned Resources

**DB record deleted but K8s resources remain:**
```
DB: No record for old-mcp
K8s: Deployment, Service still exist
```

**Periodic sync detects:**
```
Log: "Found orphaned K8s resource: name=old-mcp"
Stats: orphaned=1
```

**Manual cleanup:**
```bash
# Enable autoCleanup or use cleanup API
```

### 4. Partial Failure

**Instance creation fails halfway:**
```
DB: my-mcp (status: starting)
K8s: Service created, Deployment failed
```

**Next sync:**
```
State: mismatch
Message: "Resources unhealthy: deployment=false, service=true"
Action: Recreate both resources
```

## Safety Features

1. **Auto-cleanup disabled by default**: Orphaned resources are logged but not deleted
2. **Status updates**: Instance status changes to "recreating" during recovery
3. **Error handling**: Failed recreations are logged and retried on next sync
4. **Batching**: Rapid changes are batched to avoid thundering herd
5. **Timeouts**: All K8s operations have timeouts to prevent blocking

## Best Practices

### Manual Resource Deletion

If you need to delete an MCP instance's resources manually:

```bash
# 1. Delete from database first
curl -X DELETE http://mcp-manager/instances/my-mcp

# 2. Or mark for cleanup and trigger sync
curl -X POST http://mcp-manager/reconcile/trigger
```

### Debugging State Issues

```bash
# Check sync status
curl http://mcp-manager/reconcile/status

# View recent sync results
curl http://mcp-manager/reconcile/results

# Check specific instance
curl http://mcp-manager/reconcile/instances/my-mcp

# Trigger manual sync
curl -X POST http://mcp-manager/reconcile/trigger
```

### Monitoring

Key metrics to monitor:
- `missing` > 0: Resources need recreation (check logs)
- `orphaned` > 0: Cleanup may be needed
- `errors` increasing: Check reconciler logs
- `duration` > 30s: Large number of instances or K8s issues

## Implementation Notes

### Database Schema

```sql
CREATE TABLE mcp_server_instances (
    id UUID PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    service_name VARCHAR(255),
    status VARCHAR(50) NOT NULL, -- running, starting, stopped, error, recreating
    url TEXT,
    internal_url TEXT,
    image VARCHAR(500),
    port INTEGER,
    environment JSONB,
    labels JSONB,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    deleted_at TIMESTAMP  -- Soft delete
);
```

### K8s Resource Labels

All MCP Manager resources have these labels for identification:

```yaml
labels:
  app.kubernetes.io/managed-by: mcp-manager
  app.kubernetes.io/component: mcp-server
  app.kubernetes.io/instance: my-mcp
  agentarea.io/instance: my-mcp
```

### Startup Behavior

```
1. MCP Manager starts
2. Connects to database
3. Initializes K8s backend
4. Starts reconciler
5. Reconciler runs startup sync
6. All MCP instances verified/recreated
7. Periodic sync begins
8. Watchers start
```

## Future Enhancements

1. **Leader Election**: Only one MCP Manager runs reconciler in HA mode
2. **Events**: Publish sync events to Redis for audit trail
3. **Metrics**: Prometheus metrics for sync operations
4. **Dry Run**: Preview what changes would be made
5. **Selective Sync**: Only sync specific instances
