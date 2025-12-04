# AgentArea Helm Chart

Official Helm chart for deploying AgentArea platform on Kubernetes.

## Overview

AgentArea is a comprehensive AI agent platform. This chart deploys all necessary components including:

- **Backend API** - Core application server
- **Frontend** - Next.js web interface
- **Worker** - Temporal workflow worker
- **MCP Manager** - Model Context Protocol container manager
- **Temporal** - Workflow engine + UI
- **Infisical** - Secrets management
- **PostgreSQL** - Database (optional, can use external)
- **Redis** - Caching and events (optional, can use external)
- **MinIO** - S3-compatible storage (optional, can use external)

## Prerequisites

- Kubernetes 1.20+
- Helm 3.8+
- PV provisioner support (for PostgreSQL persistence)

## Installation

### Quick Start (Minikube)

```bash
# Add Bitnami repository for dependencies
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update

# Install with default values
helm install agentarea ./charts/agentarea

# Or with custom values
helm install agentarea ./charts/agentarea -f my-values.yaml
```

### Using External Infrastructure

If you have existing PostgreSQL, Redis, or MinIO:

```yaml
# values.yaml
postgresql:
  enabled: false

redis:
  enabled: false

minio:
  enabled: false

global:
  database:
    host: "my-postgres.example.com"
    port: 5432
    database: "agentarea"
  redis:
    host: "my-redis.example.com"
    port: 6379
  storage:
    endpoint: "https://s3.amazonaws.com"
    bucket: "my-bucket"
    region: "us-east-1"
```

## Configuration

### Global Settings

| Parameter | Description | Default |
|-----------|-------------|---------|
| `global.image.registry` | Custom image registry | `""` |
| `global.image.pullPolicy` | Image pull policy | `IfNotPresent` |
| `global.secrets.postgresql` | PostgreSQL secret name | `agentarea-postgresql-secret` |
| `global.secrets.redis` | Redis secret name | `agentarea-redis-secret` |
| `global.secrets.minio` | MinIO secret name | `agentarea-minio-secret` |

### Component Settings

Each component supports:

- `enabled` - Enable/disable component
- `replicaCount` - Number of replicas
- `image.repository` - Image repository
- `image.tag` - Image tag
- `resources` - Resource limits/requests
- `extraEnv` - Additional environment variables

Example:

```yaml
backend:
  enabled: true
  replicaCount: 2
  resources:
    limits:
      cpu: 1000m
      memory: 1Gi
    requests:
      cpu: 500m
      memory: 512Mi
  extraEnv:
    - name: CUSTOM_VAR
      value: "custom-value"
```

## Secrets Management

The chart auto-generates secrets if they don't exist. For production, create secrets manually:

```bash
kubectl create secret generic agentarea-postgresql-secret \
  --from-literal=username=postgres \
  --from-literal=password=<your-password> \
  --from-literal=postgres-password=<your-password>

kubectl create secret generic agentarea-redis-secret \
  --from-literal=redis-password=<your-password>

kubectl create secret generic agentarea-minio-secret \
  --from-literal=root-user=<access-key> \
  --from-literal=root-password=<secret-key>

kubectl create secret generic agentarea-app-secrets \
  --from-literal=auth-secret=$(openssl rand -base64 32) \
  --from-literal=encryption-key=$(openssl rand -hex 16)
```

## Upgrading

```bash
helm upgrade agentarea ./charts/agentarea -f values.yaml
```

## Uninstalling

```bash
helm uninstall agentarea
```

## Development

Build images for local testing:

```bash
# Build all images
docker build -t agentarea/agentarea-backend:latest -f core/apps/api/Dockerfile core/
docker build -t agentarea/agentarea-worker:latest -f core/apps/worker/Dockerfile core/
docker build -t agentarea/agentarea-frontend:latest -f frontend/Dockerfile frontend/
docker build -t agentarea/mcp-manager:latest -f agentarea-mcp-manager/Dockerfile agentarea-mcp-manager/
docker build -t agentarea/agentarea-bootstrap:latest -f agentarea-bootstrap/Dockerfile agentarea-bootstrap/

# For Minikube
eval $(minikube docker-env)
# Then rebuild images
```

## License

See the main project LICENSE file.
