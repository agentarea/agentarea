# AgentArea Helm Chart - Initialization Order

## How Dependencies Are Installed

### Question: "Is PostgreSQL installed? How is initialization order handled?"

**Answer**: Yes, PostgreSQL (and Redis, MinIO) are installed as Helm chart dependencies. Here's how we ensure proper initialization order:

## Installation Sequence

### 1. Helm Hook Weights (Execution Order)

```
┌─────────────────────────────────────────────────────────┐
│ Hook Weight -1 (Pre-Install/Pre-Upgrade)               │
│ • Secrets (PostgreSQL, Redis, MinIO, App)              │
│ • ConfigMaps (centralized env-configmap)               │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ Default Weight 0 (Normal Installation)                  │
│ • PostgreSQL (Bitnami chart - has readiness probes)    │
│ • Redis (Bitnami chart - has readiness probes)         │
│ • MinIO (Bitnami chart - has readiness probes)         │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ Hook Weight 5 (Pre-Install/Pre-Upgrade)                │
│ • Migration Job                                         │
│   - Init Container: Wait for PostgreSQL                │
│   - Main Container: Run database migrations            │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ Hook Weight 10 (Post-Install/Post-Upgrade)             │
│ • Bootstrap Job                                         │
│   - Init Container: Wait for PostgreSQL                │
│   - Init Container: Wait for MinIO                     │
│   - Main Container: Bootstrap data & create admin      │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ No Hook (Normal Deployment)                            │
│ • Backend API                                           │
│ • Frontend                                              │
│ • Worker                                                │
│ • MCP Manager                                           │
│ • Temporal                                              │
│ • Temporal UI                                           │
└─────────────────────────────────────────────────────────┘
```

## How We Ensure Proper Ordering

### 1. Helm Hooks Pattern

Helm hooks allow us to run jobs at specific points in the release lifecycle:

- `pre-install`: Before any resources are installed
- `post-install`: After all resources are installed
- `pre-upgrade`: Before any resources are upgraded
- `post-upgrade`: After all resources are upgraded

### 2. Hook Weights

Lower numbers run first:

```yaml
# Secrets and ConfigMaps (weight -1)
annotations:
  "helm.sh/hook": "pre-install,pre-upgrade"
  "helm.sh/hook-weight": "-1"

# Migration Job (weight 5)
annotations:
  "helm.sh/hook": "pre-install,pre-upgrade"
  "helm.sh/hook-weight": "5"

# Bootstrap Job (weight 10)
annotations:
  "helm.sh/hook": "post-install,post-upgrade"
  "helm.sh/hook-weight": "10"
```

### 3. Init Containers Best Practice

Even with hook weights, we add init containers that actively wait for services to be ready:

#### Migration Job Init Container

```yaml
initContainers:
  - name: wait-for-postgres
    image: postgres:15-alpine
    command:
      - sh
      - -c
      - |
        until pg_isready -h agentarea-postgresql -p 5432 -U postgres; do
          echo "Waiting for PostgreSQL to be ready..."
          sleep 2
        done
```

#### Bootstrap Job Init Containers

```yaml
initContainers:
  - name: wait-for-postgres
    # Waits for PostgreSQL to accept connections

  - name: wait-for-minio
    # Waits for MinIO health endpoint to respond
```

### 4. Bitnami Charts Have Built-in Readiness

The Bitnami PostgreSQL, Redis, and MinIO charts already include:
- **Readiness Probes**: Pods won't be marked "Ready" until they can accept connections
- **Liveness Probes**: Pods restart if they become unhealthy
- **StatefulSets**: Ordered deployment for databases

### AgentArea's Implementation:
1. ✅ Helm hooks for jobs (migration, bootstrap)
2. ✅ Hook weights (-1, 5, 10)
3. ✅ Init containers with active waiting
4. ✅ Bitnami charts for PostgreSQL, Redis, MinIO
5. ✅ Centralized ConfigMap with lifecycle hooks

## Why This Works

### 1. Secrets Created First (Weight -1)
PostgreSQL, Redis, and MinIO need credentials to start. By creating secrets first, they're available when Bitnami charts start.

### 2. Dependencies Install (Weight 0)
Bitnami charts deploy with default weight. They won't be "Ready" until their health checks pass.

### 3. Migration Waits for PostgreSQL (Weight 5)
The init container actively polls `pg_isready` until PostgreSQL accepts connections. Only then does the migration run.

### 4. Bootstrap Waits for Everything (Weight 10)
Runs AFTER migrations complete. Init containers ensure both PostgreSQL and MinIO are ready.

### 5. Application Pods Start (No Hook)
Normal deployment happens after all hooks complete. Services can safely connect to databases.

## Troubleshooting

### If Migration Job Fails:

1. **Check PostgreSQL is running:**
   ```bash
   kubectl get pods -n agentarea -l app.kubernetes.io/name=postgresql
   ```

2. **Check migration job logs:**
   ```bash
   kubectl logs -n agentarea job/agentarea-migration
   ```

3. **Check init container logs:**
   ```bash
   kubectl logs -n agentarea job/agentarea-migration -c wait-for-postgres
   ```

### If Bootstrap Job Fails:

1. **Check migration completed:**
   ```bash
   kubectl get jobs -n agentarea
   ```

2. **Check MinIO is running:**
   ```bash
   kubectl get pods -n agentarea -l app.kubernetes.io/name=minio
   ```

3. **Check bootstrap logs:**
   ```bash
   kubectl logs -n agentarea job/agentarea-bootstrap
   kubectl logs -n agentarea job/agentarea-bootstrap -c wait-for-postgres
   kubectl logs -n agentarea job/agentarea-bootstrap -c wait-for-minio
   ```

### If Application Pods Crash:

Usually means migration or bootstrap didn't complete successfully. Check:

```bash
# View all jobs
kubectl get jobs -n agentarea

# Check migration status
kubectl describe job agentarea-migration -n agentarea

# Check bootstrap status
kubectl describe job agentarea-bootstrap -n agentarea
```

## Key Files

- **Secrets with hooks**: [templates/secrets.yaml](./agentarea/templates/secrets.yaml)
- **ConfigMap with hooks**: [templates/env-configmap.yaml](./agentarea/templates/env-configmap.yaml)
- **Migration job**: [templates/jobs/migration-job.yaml](./agentarea/templates/jobs/migration-job.yaml)
- **Bootstrap job**: [templates/jobs/bootstrap-job.yaml](./agentarea/templates/jobs/bootstrap-job.yaml)
- **Dependencies**: [Chart.yaml](./agentarea/Chart.yaml) (lines 27-44)

## Summary

**Yes, PostgreSQL is installed** as a Helm chart dependency along with Redis and MinIO.

**We handle initialization order** using:
1. Helm hooks with explicit weights
2. Init containers that wait for services
3. Bitnami charts' built-in readiness probes

This follows a battle-tested pattern used for production deployments.
