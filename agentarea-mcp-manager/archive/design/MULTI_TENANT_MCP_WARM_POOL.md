# Multi-Tenant MCP Warm Pool (Realistic Design)

## The Problem

**You're right - I forgot the key constraint:**

```
User A: [mcp-nginx, mcp-postgres, mcp-custom-1]  ← 3 different images
User B: [mcp-redis, mcp-custom-2]                ← 2 different images  
User C: [mcp-custom-3, mcp-custom-4, ...]        ← N different images

Total: 1000s of unique MCP images across all users
```

**Can't use `minReplicas: 1` per MCP** - that would be:
- 1000 users × 5 MCPs each = 5000 pods always running
- $$$$$ even when idle

## The Solution: Generic Warm Pool

Keep **generic** pods warm, inject MCP-specific code on-demand.

```
┌─────────────────────────────────────────────────────────────────────┐
│  WARM POOL (generic, shared across all users)                       │
│                                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐          ┌──────────┐      │
│  │ Pod 1    │ │ Pod 2    │ │ Pod 3    │    ...   │ Pod N    │      │
│  │ (empty)  │ │ (empty)  │ │ (empty)  │          │ (empty)  │      │
│  │ 256MB    │ │ 256MB    │ │ 256MB    │          │ 256MB    │      │
│  └──────────┘ └──────────┘ └──────────┘          └──────────┘      │
│                                                                     │
│  Image: agentarea/mcp-runner:latest                                 │
│  Contains: Container runtime, networking, base tools                │
│  Does NOT contain: Any MCP-specific code                            │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼ User A requests "mcp-custom-1"
┌─────────────────────────────────────────────────────────────────────┐
│  FAST START (200-500ms)                                             │
│                                                                     │
│  1. Pick Pod 2 from warm pool                                       │
│  2. Download mcp-custom-1 image/code                                │
│  3. Overlay mount into running container                            │
│  4. Start MCP process                                               │
│  5. Route traffic                                                   │
│                                                                     │
│  Total: 200-500ms vs 5-15s cold start!                              │
└─────────────────────────────────────────────────────────────────────┘
```

## Architecture

### Components

```
User Request
    │
    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Envoy Gateway                                                      │
│  └── Route: /mcp/{user-id}/{mcp-name}                               │
│  └── If no backend: Forward to MCP Manager (activation)             │
└─────────────────────────────────────────────────────────────────────┘
    │
    ▼ No pod running
┌─────────────────────────────────────────────────────────────────────┐
│  MCP Manager - Activation Service                                   │
│                                                                     │
│  1. Check warm pool for available pod                               │
│  2. Assign pod: label it with user-id + mcp-name                    │
│  3. Trigger "activation" in pod                                     │
│     └── Download MCP image → Extract → Mount → Start                │
│  4. Update Service endpoints                                        │
│  5. Return pod IP to Envoy                                          │
└─────────────────────────────────────────────────────────────────────┘
    │
    ▼ Pod now ready
┌─────────────────────────────────────────────────────────────────────┐
│  MCP Pod (was generic, now specialized)                             │
│                                                                     │
│  Base: agentarea/mcp-runner (pre-warmed)                            │
│  + Overlay: mcp-custom-1 code (downloaded on-demand)                │
│  + Process: MCP server running                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Generic Runner Image

```dockerfile
# agentarea/mcp-runner:latest
FROM alpine:latest

# Base tools
RUN apk add --no-cache curl tar gzip

# MCP runtime (language-specific)
COPY mcp-runtime /usr/local/bin/mcp-runtime

# Activation script - downloads and starts MCP
COPY activate.sh /usr/local/bin/activate

# Default: wait for activation
CMD ["/usr/local/bin/wait-for-activation"]
```

### Activation Flow

```bash
#!/bin/bash
# activate.sh - Runs inside warm pod when assigned to an MCP

MCP_IMAGE="$1"      # e.g., "user123/mcp-custom:v1"
MCP_CONFIG="$2"     # JSON config

# 1. Download MCP image layers (if not cached)
crane pull "$MCP_IMAGE" /tmp/mcp-layers

# 2. Extract to overlay directory
mkdir -p /app/mcp-overlay
 tar -xzf /tmp/mcp-layers -C /app/mcp-overlay

# 3. Overlay mount on top of base
# /app/mcp = /app/base + /app/mcp-overlay
mount -t overlay overlay -o lowerdir=/app/base,upperdir=/app/mcp-overlay,workdir=/app/work /app/mcp

# 4. Set environment from config
export MCP_CONFIG="$MCP_CONFIG"

# 5. Start MCP process
exec /app/mcp/start.sh
```

## Implementation Options

### Option 1: K8s Mutating Webhook (Cleanest)

Webhook intercepts pod creation, injects warm pool logic:

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: MutatingWebhookConfiguration
metadata:
  name: mcp-warm-pool-webhook
webhooks:
  - name: mcp.agentarea.io
    rules:
      - operations: ["CREATE"]
        apiGroups: [""]
        apiVersions: ["v1"]
        resources: ["pods"]
        scope: Namespaced
```

**Flow:**
1. User creates MCP instance
2. Webhook intercepts
3. Instead of creating new pod, assigns warm pool pod
4. Labels pod with MCP identity

### Option 2: MCP Manager Controls Assignment (Simpler)

MCP Manager owns the warm pool:

```go
type WarmPool struct {
    client kubernetes.Interface
    namespace string
    
    // Warm pods waiting for assignment
    available chan *WarmPod
    
    // Assigned pods (user-id -> pod)
    assigned map[string]*WarmPod
}

func (p *WarmPool) ActivateMCP(userID, mcpName, mcpImage string) (*WarmPod, error) {
    // 1. Get warm pod from pool
    pod := <-p.available
    
    // 2. Label it
    pod.Labels["mcp.user"] = userID
    pod.Labels["mcp.name"] = mcpName
    pod.Labels["mcp.status"] = "activating"
    p.client.CoreV1().Pods(p.namespace).Update(pod)
    
    // 3. Trigger activation
    err := p.activatePod(pod, mcpImage)
    if err != nil {
        // Return to pool
        p.available <- pod
        return nil, err
    }
    
    // 4. Mark ready
    pod.Labels["mcp.status"] = "ready"
    p.client.CoreV1().Pods(p.namespace).Update(pod)
    
    return pod, nil
}
```

### Option 3: Containerd/Kubernetes Image Warm + CRI (Advanced)

Pre-pull all MCP images to nodes:

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: mcp-image-warmer
spec:
  template:
    spec:
      containers:
        - name: warmer
          image: agentarea/image-warmer
          command:
            - /bin/sh
            - -c
            - |
              # Pre-pull popular MCP base images
              ctr images pull docker.io/agentarea/mcp-base-python:latest
              ctr images pull docker.io/agentarea/mcp-base-node:latest
              
              # Watch for new MCP images via API
              # Pull them in background
              sleep infinity
```

Then regular pod creation is fast (image already on node).

## Resource Math

### Without Warm Pool (Scale-to-Zero)
```
1000 users × 5 MCPs = 5000 MCPs
All scaled to 0 when idle

Cold start: 5-15s each
Cost when idle: $0
```

### With Warm Pool (Generic)
```
Pool size: 20 pods (configurable)
Each: 256MB RAM

Cost: 20 × 256MB = 5GB RAM always
     (~$10-20/month on cloud)

Cold start: 200-500ms
Can handle 20 concurrent activations
```

### With minReplicas: 1 per MCP (Expensive!)
```
1000 users × 5 MCPs × 256MB = 1.25TB RAM!
Cost: $1000s/month

Cold start: 0ms
```

## Trade-offs

| Approach | Cold Start | Cost at Idle | Complexity | Best For |
|----------|------------|--------------|------------|----------|
| **True scale-to-zero** | 5-15s | $0 | Low | Rarely used MCPs |
| **Generic warm pool** | 200-500ms | ~$20/month | Medium | Most MCPs |
| **minReplicas:1 per MCP** | 0ms | $$$$ | Low | Never (too expensive) |

## Recommended Design

### Tiered Approach

```yaml
# mcp-instance.yaml
spec:
  tier: "hot"       # Always keep warm (for popular MCPs)
  # OR
  tier: "warm"      # Use generic warm pool (default)
  # OR
  tier: "cold"      # True scale-to-zero (rarely used)
```

### Implementation

```go
func (m *MCPManager) StartMCP(instance *MCPInstance) error {
    switch instance.Tier {
    case "hot":
        // Regular Deployment with replicas: 1
        return m.createAlwaysOn(instance)
        
    case "warm":
        // Assign from warm pool
        return m.warmPool.Activate(instance)
        
    case "cold":
        // KEDA scale-to-zero
        return m.createServerless(instance)
    }
}
```

## Simplest Viable Implementation

**Phase 1: Warm Pool Only**

1. **DaemonSet** keeps N generic pods running
2. **MCP Manager** assigns on request
3. **Service** updated with endpoint
4. **Envoy** retries during activation

```yaml
# Warm pool DaemonSet
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: mcp-warm-pool
spec:
  template:
    spec:
      containers:
        - name: warm-pod
          image: agentarea/mcp-runner:latest
          command: ["wait-for-assignment"]
---
# Activation via MCP Manager API
# POST /activate
# {
#   "user_id": "user-123",
#   "mcp_name": "custom-mcp",
#   "mcp_image": "user123/mcp-custom:v1"
# }
```

**Trade-off:**
- Simple to implement
- 200-500ms activation
- Fixed cost (~$20/month for 20 warm pods)
- Each node has warm pods (DaemonSet)

## Questions

1. **How many warm pods per node?**
   - 5-10 is probably enough (activations are fast)
   
2. **What if all warm pods busy?**
   - Fall back to cold start (create new pod)
   - Or queue and wait
   
3. **Security isolation?**
   - Use Kata for warm pods too (VM-level isolation)
   - Each warm pod is its own VM
   - Activation happens inside VM

4. **Image caching?**
   - Pull MCP images to node on first use
   - Keep in containerd cache
   - Subsequent activations faster (just mount)
