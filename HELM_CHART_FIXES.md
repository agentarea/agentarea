# Helm Chart Issues and Fixes

## Summary of Issues Found

| Issue | Status | Impact |
|-------|--------|--------|
| Disk Space Exhaustion | 🔴 Critical | PostgreSQL fails, cascades to Kratos |
| ARM64 Image Compatibility | 🔴 Critical | Backend/Worker in ImagePullBackOff |
| MCP Manager RBAC Insufficient | 🔴 Critical | Cannot create K8s resources |
| MCP Manager Missing K8s Config | 🔴 Critical | Runs in Docker mode instead of K8s |
| Privileged Security Context | 🟡 Medium | Unnecessary for K8s backend |

---

## Quick Fix (Run These)

```bash
# 1. Free up minikube disk space
./scripts/cleanup-minikube.sh

# 2. Build ARM64 images and load into minikube
./scripts/build-images-minikube.sh all

# 3. Apply Helm chart fixes
helm upgrade agentarea charts/agentarea \
  --namespace agentarea \
  --create-namespace \
  -f charts/agentarea/values-minikube.yaml
```

---

## Detailed Issues and Fixes

### 1. Disk Space Exhaustion

**Problem:** Minikube out of disk space (63GB used, 0GB available)

**Fix:** Use cleanup script or recreate minikube
```bash
# Quick cleanup
./scripts/cleanup-minikube.sh

# Full cleanup (removes all unused images)
./scripts/cleanup-minikube.sh --full

# Or recreate minikube
minikube delete
minikube start --driver=docker --disk-size=100g --cpus=4 --memory=8192
```

---

### 2. ARM64 Image Compatibility

**Problem:** Images don't support ARM64
```
Failed to pull image "agentarea/agentarea-api:latest": 
no matching manifest for linux/arm64/v8 in the manifest list entries
```

**Fix Options:**

**A. Local Build (Immediate fix for development)**
```bash
./scripts/build-images-minikube.sh all
# Or build specific component:
./scripts/build-images-minikube.sh api
./scripts/build-images-minikube.sh worker
```

**B. CI/CD Multi-Arch Builds (Permanent fix)**

✅ Already applied to `.github/workflows/docker-build-push.yml`:
```yaml
platforms: linux/amd64,linux/arm64
```

This will build and push multi-arch images on next CI run.

---

### 3. MCP Manager RBAC Insufficient

**Problem:** RBAC only allows `namespaces: get, list`

**Fix Applied:** Updated `charts/agentarea/templates/rbac-mcp-manager.yaml`

New permissions:
- Core resources: `pods`, `services`, `configmaps`, `secrets`
- Apps: `deployments`, `replicasets`
- Gateway API: `httproutes`, `gateways`
- Events: `events`

---

### 4. MCP Manager Missing K8s Environment Variables

**Problem:** Config hardcoded for Docker mode (`TRAEFIK_NETWORK: "podman"`)

**Fix Applied:** Updated `charts/agentarea/templates/configs/mcpManager.env.tpl`

New environment variables:
```yaml
BACKEND_TYPE: "kubernetes"
KUBERNETES_ENABLED: "true"
KUBERNETES_NAMESPACE: "agentarea"
KUBERNETES_DOMAIN: "mcp.local"
KUBERNETES_GATEWAY_NAME: "envoy-gateway"
KUBERNETES_GATEWAY_NAMESPACE: "envoy-gateway-system"
KUBERNETES_RUNTIME_CLASS: ""
```

---

### 5. Privileged Security Context

**Problem:** `privileged: true` only needed for Docker/Podman backend

**Fix Applied:** 
- Updated `values.yaml`: `securityContext: {}` for K8s backend
- Updated deployment template: volumes only mounted for Docker mode
- Added `backend: "kubernetes"` option in values

---

## Files Modified

| File | Change |
|------|--------|
| `templates/rbac-mcp-manager.yaml` | Added full K8s RBAC permissions |
| `templates/configs/mcpManager.env.tpl` | Added K8s environment variables |
| `templates/agentarea-mcp-manager/deployment.yaml` | Conditional volumes for Docker mode |
| `values.yaml` | Added gateway config, backend option |
| `.github/workflows/docker-build-push.yml` | Added ARM64 platform |
| `values-minikube.yaml` | Created local dev values |
| `scripts/build-images-minikube.sh` | Created ARM64 build script |
| `scripts/cleanup-minikube.sh` | Created cleanup script |

---

## Verification

```bash
# Check pods are running
kubectl get pods -n agentarea

# Check MCP Manager logs
kubectl logs -n agentarea deployment/agentarea-mcp-manager

# Test MCP instance creation
curl -X POST http://localhost:8888/instances \
  -H "Content-Type: application/json" \
  -d '{"name":"test-mcp","image":"nginx:alpine","port":80}'

# Check HTTPRoute was created
kubectl get httproute -n agentarea
```
