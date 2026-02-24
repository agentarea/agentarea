# Simple K8s-Native Fast Cold Start

## The Answer: `minReplicas: 1` with HPA/KEDA

This is the **most Kubernetes-native** and **simplest** way to get fast starts:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: mcp-my-mcp
spec:
  scaleTargetRef:
    name: mcp-my-mcp
  minReplicaCount: 1  # ← Always keep 1 warm!
  maxReplicaCount: 10
  triggers:
    - type: metrics-api
      metadata:
        targetValue: "10"
```

**Result:**
- ✅ First request: **0ms** (pod already running)
- ✅ Scales to 10 under load
- ✅ True scale-to-zero possible with trade-off (see below)

---

## Comparison: Native K8s Options

| Approach | Cold Start | Setup | Resource Cost | Best For |
|----------|-----------|-------|---------------|----------|
| **HPA minReplicas: 1** | 0ms | 1 line | 1 pod always | Most MCPs |
| **KEDA minReplicas: 0** | 3-10s | Install KEDA | $0 when idle | Rarely used MCPs |
| **KEDA minReplicas: 1** | 0ms | Install KEDA | 1 pod + KEDA | Auto-scaling needed |

---

## Option 1: HPA (Built into K8s - Simplest)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-my-mcp
spec:
  replicas: 1  # ← Always 1
  template:
    spec:
      containers:
        - name: mcp
          image: my-mcp:latest
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: mcp-my-mcp
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: mcp-my-mcp
  minReplicas: 1  # ← Never scale to 0
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 50
```

**Pros:**
- Built into K8s (no extra operators)
- Zero cold start (always 1 running)
- Scales under load

**Cons:**
- Always paying for 1 pod
- Can't scale to zero

---

## Option 2: KEDA (More Flexible)

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: mcp-my-mcp
spec:
  scaleTargetRef:
    name: mcp-my-mcp
  minReplicaCount: 1  # ← Keep 1 warm
  maxReplicaCount: 10
  triggers:
    - type: metrics-api
      metadata:
        targetValue: "5"
        url: "http://prometheus/mcp_requests?instance=my-mcp"
```

**Pros:**
- Scale on custom metrics (requests, not just CPU)
- Can do minReplicas: 0 for true serverless
- Same config for warm and cold modes

**Cons:**
- Need to install KEDA operator

---

## Option 3: True Scale-to-Zero with Fast Start (Optimization)

If you want **both**:
- Scale to zero (save money)
- Fast cold start when needed

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: mcp-my-mcp
spec:
  scaleTargetRef:
    name: mcp-my-mcp
  minReplicaCount: 0  # ← Scale to zero
  maxReplicaCount: 10
  cooldownPeriod: 300  # 5 min idle before scale down
  triggers:
    - type: metrics-api
      metadata:
        targetValue: "1"
```

**Optimization tricks for faster cold start:**

### 1. Small Base Image
```dockerfile
# Use distroless or alpine
FROM gcr.io/distroless/python3-debian12
# Not: FROM python:3.11 (500MB)
# Result: 3-5s faster pull
```

### 2. Pre-pull Images
```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: image-prewarmer
spec:
  template:
    spec:
      initContainers:
        - name: pull
          image: my-mcp:latest
          command: ["true"]
```

### 3. Containerd Image Pull Optimization
```bash
# On node startup, pre-pull common MCP images
ctr images pull docker.io/agentarea/mcp-base:latest
```

### 4. Startup Probe (not Liveness)
```yaml
spec:
  template:
    spec:
      containers:
        - name: mcp
          startupProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 0
            periodSeconds: 1
            failureThreshold: 30  # Wait up to 30s
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 30  # Only after startup
```

---

## Recommendation by Use Case

### Default: HPA with minReplicas: 1

```yaml
spec:
  scaling:
    mode: "hpa"           # or "keda"
    minReplicas: 1        # Always warm
    maxReplicas: 10
```

**When:**
- Most MCPs (expected to be used regularly)
- Want simplicity
- Don't need true scale-to-zero

### For Rarely-Used MCPs: KEDA minReplicas: 0

```yaml
spec:
  scaling:
    mode: "keda"
    minReplicas: 0        # Scale to zero
    maxReplicas: 5
    idleTimeout: "10m"    # Wait 10min before scaling down
```

**When:**
- MCPs used once per day/week
- OK with 3-10s cold start
- Want to save costs

### Per-MCP Override

```json
{
  "name": "popular-mcp",
  "image": "popular:latest",
  "scaling": {
    "mode": "hpa",
    "minReplicas": 1  // Always warm, 0ms start
  }
}
```

```json
{
  "name": "rare-mcp",
  "image": "rare:latest",
  "scaling": {
    "mode": "keda",
    "minReplicas": 0,  // Scale to zero, 3-10s start
    "idleTimeout": "30m"
  }
}
```

---

## Summary

| Goal | Solution | Config |
|------|----------|--------|
| **Fastest + Simplest** | HPA minReplicas: 1 | `minReplicas: 1` |
| **True serverless** | KEDA minReplicas: 0 | `minReplicas: 0` |
| **Best of both** | KEDA minReplicas: 1 | `minReplicas: 1`, can change per-MCP |

**Simplest K8s-native answer:**
```yaml
minReplicas: 1  # Just this one line!
```

No custom code, no warm pools, no snapshots. Just keep 1 replica running.
