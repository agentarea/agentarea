# Serverless MCP Design

## Overview

MCP instances should run in **serverless mode** by default:
- Scale to **zero** when not accessed
- **Cold start** on first request
- Use **K8s native autoscaling** (KEDA/Knative/HPA)
- **No reconciliation** to force "running" state
- **HTTPRoute** handles routing even to scaled-down services

## Deployment Modes

```yaml
# Mode 1: Always-On (current behavior)
spec:
  deploymentMode: "always-on"  # Or omit for default
  replicas: 1

# Mode 2: Serverless (new default)
spec:
  deploymentMode: "serverless"
  idleTimeout: "5m"           # Scale down after 5 min idle
  minReplicas: 0
  maxReplicas: 10
```

## Architecture

```
User Request
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Envoy Gateway (always running)                              │
│  - HTTPRoute: /mcp/{instance}/*                             │
│  - Timeout: 30s (allows cold start)                         │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Service (ClusterIP - always exists)                         │
│  - Points to nothing when scaled to zero                    │
│  - K8s routes to pod when available                         │
└─────────────────────────────────────────────────────────────┘
    │
    ▼ (cold start happens here)
┌─────────────────────────────────────────────────────────────┐
│  KEDA ScaledObject / Knative Service                        │
│  - Monitors HTTP requests or custom metrics                 │
│  - Scales from 0 → 1 on first request                       │
│  - Scales 1 → 0 after idleTimeout                           │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  MCP Container (ephemeral)                                   │
│  - Starts on demand                                          │
│  - Handles requests                                          │
│  - Stops after idle                                          │
└─────────────────────────────────────────────────────────────┘
```

## Implementation Options

### Option 1: KEDA (Recommended)

Use KEDA's `ScaledObject` with HTTP trigger:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: mcp-my-mcp
  namespace: mcp-system
spec:
  scaleTargetRef:
    name: mcp-my-mcp
  minReplicaCount: 0
  maxReplicaCount: 10
  triggers:
    - type: metrics-api
      metadata:
        targetValue: "1"
        url: "http://mcp-manager/metrics/active-connections?instance=my-mcp"
        valueLocation: "count"
  advanced:
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          stabilizationWindowSeconds: 300  # 5 min idle before scale down
```

**Pros:**
- Native K8s, no extra infrastructure
- Works with standard Deployments
- Flexible triggers (HTTP, custom metrics, cron)

**Cons:**
- Requires KEDA installed on cluster
- HTTP trigger needs metrics source

### Option 2: Knative Serving

Use Knative Service instead of Deployment:

```yaml
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: mcp-my-mcp
  namespace: mcp-system
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/minScale: "0"
        autoscaling.knative.dev/maxScale: "10"
        autoscaling.knative.dev/window: "5m"  # Scale down after 5 min
    spec:
      containers:
        - image: my-mcp-image
          ports:
            - containerPort: 8080
```

**Pros:**
- Purpose-built for serverless
- Automatic cold start handling
- Built-in traffic splitting

**Cons:**
- Requires Knative installed
- More complex infrastructure
- Different API (Service vs Deployment)

### Option 3: Custom Controller (Fallback)

If neither KEDA nor Knative available:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-my-mcp
  annotations:
    mcp.agentarea.io/scale-to-zero: "true"
    mcp.agentarea.io/idle-timeout: "5m"
spec:
  replicas: 0  # Start scaled to zero
  # ... normal deployment spec
```

MCP Manager watches for requests and scales up/down via K8s API.

**Pros:**
- No additional dependencies
- Full control over behavior

**Cons:**
- More code to maintain
- MCP Manager becomes scaling bottleneck

## Cold Start Handling

### The Problem

1. Request arrives at Envoy Gateway
2. Service exists but no endpoints (pod scaled to zero)
3. Request would fail with 503

### Solutions

**1. Envoy Retry Policy (Recommended)**

HTTPRoute with retries:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: mcp-my-mcp
spec:
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /mcp/my-mcp
      backendRefs:
        - name: mcp-my-mcp
          port: 80
      # Retry on connection failure (cold start)
      filters:
        - type: ExtensionRef
          extensionRef:
            group: gateway.envoyproxy.io
            kind: RetryPolicy
            name: cold-start-retry
---
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: RetryPolicy
metadata:
  name: cold-start-retry
spec:
  retryOn:
    - connect-failure
    - refused-stream
  numRetries: 10
  perRetry:
    timeout: 2s
    backoff:
      baseInterval: 1s
      maxInterval: 5s
```

**2. MCP Manager Pre-warming**

MCP Manager intercepts first request:

```go
func proxyHandler(w http.ResponseWriter, r *http.Request) {
    instance := getInstanceFromPath(r)
    
    // Check if scaled to zero
    if isScaledToZero(instance) {
        // Scale up first
        scaleUp(instance)
        
        // Wait for ready
        waitForReady(instance, timeout=30s)
    }
    
    // Now proxy
    proxy.ServeHTTP(w, r)
}
```

**3. Readiness Probe Hack**

Keep Service endpoints until pod is truly ready:

```yaml
spec:
  template:
    spec:
      containers:
        - name: mcp
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 0
            periodSeconds: 1
            failureThreshold: 60  # Wait up to 60s for cold start
```

## Database State Changes

Instead of:
```
status: "running" | "stopped" | "error"
```

Use:
```
status: "ready" | "scaled-to-zero" | "starting" | "error"
desiredState: "active" | "suspended"
lastAccessed: "2026-02-19T16:00:00Z"
accessCount: 42
```

### Reconciler Changes (Serverless Mode)

In serverless mode, reconciler only:
1. **Verifies resources exist** (not that they're running)
2. **Detects orphaned resources** (no DB record)
3. **Reports metrics** (scale-up time, cold start count)

Does NOT:
- Force pods to be running
- Recreate "missing" pods (they're intentionally scaled to zero)

```go
func reconcileServerless(instance) {
    // Check resources exist
    if !resourcesExist(instance) {
        // Create ScaledObject/Service/HTTPRoute
        createServerlessResources(instance)
    }
    
    // Check current scale
    replicas := getCurrentReplicas(instance)
    
    if replicas == 0 {
        updateStatus(instance, "scaled-to-zero")
    } else {
        updateStatus(instance, "ready")
    }
}
```

## Configuration

### Global Defaults

```yaml
# values.yaml
mcpManager:
  serverless:
    enabled: true                    # Enable serverless by default
    mode: "keda"                     # "keda", "knative", or "native"
    idleTimeout: "5m"                # Scale down after idle
    maxColdStartTime: "30s"          # Max time to wait for cold start
    minReplicas: 0
    maxReplicas: 10
```

### Per-Instance Override

```json
{
  "name": "my-mcp",
  "image": "my-mcp:latest",
  "serverless": {
    "enabled": true,
    "idleTimeout": "10m",
    "minReplicas": 0,
    "maxReplicas": 5
  }
}
```

### Always-On Override

```json
{
  "name": "critical-mcp",
  "image": "my-mcp:latest",
  "serverless": {
    "enabled": false,  // Always running
    "minReplicas": 1
  }
}
```

## Request Flow (Serverless)

```
1. User → Envoy Gateway: POST /mcp/my-mcp/invoke
                         
2. Envoy → Service:     Connection attempt
   (fails initially - no endpoints)
   
3. Envoy Retry:         Attempt 2, 3, 4...
   (KEDA detects traffic, scales up)
   
4. Pod Starts:          Container creating → Running
   (5-15s typical cold start)
   
5. Envoy → Pod:         Request succeeds
   
6. Response:            Returns to user
   (total: 6-16s with retries)
```

## Resource Creation Order

```yaml
# 1. ConfigMap/Secret (always needed)
apiVersion: v1
kind: ConfigMap
---
# 2. Service (always needed, even with 0 endpoints)
apiVersion: v1
kind: Service
---
# 3. HTTPRoute (always needed)
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
---
# 4. Deployment (scaled to 0 initially)
apiVersion: apps/v1
kind: Deployment
spec:
  replicas: 0
---
# 5. ScaledObject (KEDA - monitors and scales)
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
```

## Monitoring

### Metrics to Track

| Metric | Description |
|--------|-------------|
| `mcp_cold_start_duration` | Time from request to first response |
| `mcp_scale_up_count` | Number of scale-up events |
| `mcp_scale_down_count` | Number of scale-down events |
| `mcp_current_replicas` | Current replica count per MCP |
| `mcp_idle_time` | Time since last request |

### Alerts

```yaml
- alert: MCPColdStartTooSlow
  expr: mcp_cold_start_duration > 30s
  
- alert: MCPScaleUpFailing
  expr: rate(mcp_scale_up_count[5m]) > 0 AND 
        rate(mcp_scale_down_count[5m]) == 0
```

## Migration Path

1. **Phase 1**: Add serverless as option (default off)
2. **Phase 2**: Default new MCPs to serverless
3. **Phase 3**: Migrate existing MCPs to serverless
4. **Phase 4**: Remove always-on mode for most use cases

## Questions to Answer

1. **Do we require KEDA/Knative?** Or make it optional with fallback?
2. **What's acceptable cold start time?** 5s? 10s? 30s?
3. **Do we pre-warm popular MCPs?** Keep 1 replica always running?
4. **How do we handle WebSocket MCPs?** They can't scale to zero easily
