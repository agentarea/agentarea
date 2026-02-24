# KEDA vs Knative for Serverless MCP

## Quick Comparison

| Aspect | KEDA | Knative |
|--------|------|---------|
| **What it is** | Kubernetes Event-driven Autoscaling | Serverless platform for K8s |
| **Scope** | Just autoscaling | Full serverless lifecycle |
| **Scale-to-zero** | ✅ Yes (with HTTP trigger) | ✅ Native, purpose-built |
| **Cold start** | ~3-10s | ~2-5s (faster) |
| **Traffic routing** | Standard K8s Service | Advanced (traffic splitting, blue/green) |
| **Resource type** | Works with Deployments | Uses own "Service" CRD |
| **HTTP retries** | Requires Envoy config | Built-in (queue-proxy) |
| **Concurrency** | Per-pod scaling | Per-request (scale faster) |
| **Install size** | ~200MB | ~1GB+ ( heavier) |
| **Learning curve** | Low | Higher |

## Detailed Comparison

### 1. Architecture

**KEDA:**
```
┌─────────────────────────────────────────────────────────────┐
│  HPA (Horizontal Pod Autoscaler)                            │
│  └── Controlled by KEDA ScaledObject                        │
│      └── Monitors: HTTP requests, queue depth, etc.         │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Standard Deployment (scale 0 ↔ N)                          │
│  - Your container                                            │
│  - Standard K8s probes                                       │
└─────────────────────────────────────────────────────────────┘
```

**Knative:**
```
┌─────────────────────────────────────────────────────────────┐
│  Knative Service (Custom CRD)                               │
│  └── Controls: Revision, Deployment, Service, Ingress       │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Pod = queue-proxy (sidecar) + your container               │
│  - Queue-proxy handles: retries, metrics, scaling signals   │
│  - Activator handles: 0→1 scaling, request buffering        │
└─────────────────────────────────────────────────────────────┘
```

### 2. Resource Definitions

**KEDA (uses standard Deployment):**
```yaml
# Your existing Deployment - no changes needed
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-my-mcp
spec:
  replicas: 0  # KEDA controls this
  template:
    spec:
      containers:
        - name: mcp
          image: my-mcp:latest
          ports:
            - containerPort: 8080
---
# KEDA adds autoscaling
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: mcp-my-mcp
spec:
  scaleTargetRef:
    name: mcp-my-mcp
  minReplicaCount: 0
  maxReplicaCount: 10
  triggers:
    - type: metrics-api  # HTTP request count
      metadata:
        targetValue: "1"
        url: "http://prometheus/mcp_requests?instance=my-mcp"
```

**Knative (uses Knative Service):**
```yaml
# Replace Deployment with Knative Service
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: mcp-my-mcp
spec:
  template:
    metadata:
      annotations:
        # Scaling behavior
        autoscaling.knative.dev/minScale: "0"
        autoscaling.knative.dev/maxScale: "10"
        autoscaling.knative.dev/window: "5m"  # Scale down after 5 min idle
        autoscaling.knative.dev/class: "kpa.autoscaling.knative.dev"
    spec:
      containers:
        - image: my-mcp:latest
          ports:
            - containerPort: 8080
---
# No HPA, no KEDA - Knative handles everything
```

### 3. Cold Start Behavior

| Phase | KEDA | Knative |
|-------|------|---------|
| **Request arrives** | Hits Service, no endpoints | Hits Activator, buffered |
| **Scale trigger** | HPA detects, creates pod | Activator signals, creates pod |
| **Pod startup** | Container starts, probes pass | Container starts, queue-proxy ready |
| **Request handling** | Retried by Envoy | Routed by queue-proxy |
| **Total cold start** | 5-15s (depends on HPA reaction) | 2-5s (optimized path) |

**Why Knative is faster:**
- **Activator** buffers requests during scale-up (no retries needed)
- **Queue-proxy** is already running, only user container starts
- **Pre-warmed pause containers** for faster container creation

### 4. Traffic Handling

**KEDA:**
```
Request → Envoy Gateway → Service → (no endpoints, 503) 
                                           ↓
                                    [Envoy retries 5x]
                                           ↓
                                    Pod starts (5-15s)
                                           ↓
                                    Request succeeds
```
- Requires Envoy retry configuration
- Client may timeout if cold start > 30s

**Knative:**
```
Request → Envoy Gateway → Knative Ingress → Activator
                                                  ↓
                                           [Buffered, no 503]
                                                  ↓
                                           Pod starts (2-5s)
                                                  ↓
                                           Queue-proxy → Container
```
- No 503 errors during cold start
- Request held in Activator queue
- Automatic retry with backoff

### 5. Concurrency & Scaling

**KEDA:**
- Scales based on: CPU, memory, custom metrics, HTTP request rate
- One metric = one scaler
- Example: Scale up when > 10 requests/sec per pod

```yaml
triggers:
  - type: metrics-api
    metadata:
      targetValue: "10"  # 10 requests per pod
```

**Knative:**
- Scales based on: Concurrent requests per pod
- Built-in request queue per pod
- Example: Scale up when > 100 concurrent requests

```yaml
annotations:
  autoscaling.knative.dev/target-concurrency: "100"
```

### 6. Operational Complexity

**KEDA:**
```
✅ Pros:
- Works with existing Deployments
- Just one operator to install
- Standard K8s debugging (kubectl logs, etc.)
- Can use HPA metrics you're familiar with

❌ Cons:
- Need separate solution for request buffering (Envoy retries)
- HPA has 30-60s reaction time (slower scaling)
- HTTP metrics require Prometheus or similar
```

**Knative:**
```
✅ Pros:
- Purpose-built for serverless
- Request buffering built-in
- Faster cold starts
- Advanced traffic management (canary, blue/green)
- Auto-TLS with cert-manager integration

❌ Cons:
- Steep learning curve (new abstractions)
- Heavier install (Serving + Eventing optional)
- Debugging through queue-proxy layer
- Not standard K8s resources
```

### 7. Integration with MCP Manager

**KEDA Integration:**
```go
// MCP Manager creates:
1. Deployment (replicas: 0)
2. Service
3. HTTPRoute (with retry policy)
4. ScaledObject (references Deployment)

// KEDA watches metrics, scales Deployment
```

**Knative Integration:**
```go
// MCP Manager creates:
1. Knative Service (replaces Deployment+Service)
2. HTTPRoute (points to Knative Service)

// Knative handles everything internally
// No need for separate ScaledObject
```

## Decision Matrix

| Use Case | Recommendation |
|----------|----------------|
| Simple scale-to-zero | **KEDA** (simpler, uses standard K8s) |
| Fast cold starts critical | **Knative** (2-5s vs 5-15s) |
| Already using Knative | **Knative** (native fit) |
| Minimal infrastructure changes | **KEDA** (adds to existing) |
| Advanced traffic splitting | **Knative** (built-in) |
| WebSocket MCPs | **Neither** (can't scale to zero easily) |
| Mixed workload (some always-on) | **KEDA** (gradual adoption) |
| Multi-tenant with isolation | **Knative** (stronger boundaries) |

## Recommendation for AgentArea

### Phase 1: KEDA (Start Here)
- Easier to adopt (standard Deployments)
- Simpler operational model
- Works with your current Helm charts
- Good enough for most use cases

```yaml
# Minimal setup
helm install keda kedacore/keda
# Add ScaledObject to your templates
# Done!
```

### Phase 2: Knative (If Needed)
- If cold start latency becomes critical
- If you need advanced traffic management
- If you want full serverless experience

```yaml
# More complex setup
kubectl apply -f https://github.com/knative/serving/releases/download/knative-v1.14.0/serving-crds.yaml
kubectl apply -f https://github.com/knative/serving/releases/download/knative-v1.14.0/serving-core.yaml
# Configure networking layer (Istio/Contour/Envoy)
# Update MCP Manager to create Knative Services
```

## Implementation Priority

1. **Now**: Design for KEDA (standard Deployments)
2. **Later**: Add Knative option if users demand faster cold starts
3. **Config**: Let users choose per MCP instance:

```yaml
spec:
  serverless:
    mode: "keda"      # or "knative" or "disabled"
    idleTimeout: "5m"
```
