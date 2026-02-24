# Ultra-Fast Cold Start for Serverless MCP

Target: **<100ms** cold start (vs 3-15s with standard approaches)

## 1. Firecracker Snapshots (Fastest: 50-200ms)

AWS Lambda uses this. Save VM state and restore instantly.

```
┌─────────────────────────────────────────────────────────────┐
│  Pre-created (before any request)                           │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Firecracker MicroVM                                  │  │
│  │  ├── Kernel booted                                    │  │
│  │  ├── Container runtime ready                          │  │
│  │  ├── MCP base image loaded                            │  │
│  │  └── Snapshot saved to disk                           │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼ Request arrives
┌─────────────────────────────────────────────────────────────┐
│  Restore (50-200ms)                                         │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Load snapshot → Memory restored                      │  │
│  │  Resume VM → Running in <100ms                        │  │
│  │  Inject MCP config (env vars)                         │  │
│  │  Ready to handle request!                             │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

**Implementation:**
```go
// 1. Pre-create base snapshot
vm := firecracker.CreateVM(
    kernelImage: "/var/lib/firecracker/kata-vmlinuz",
    rootFS: "/var/lib/firecracker/base-mcp.ext4",
)
vm.Boot()
vm.SaveSnapshot("/var/lib/snapshots/base-mcp.snap")

// 2. On request - restore
vm := firecracker.RestoreVM("/var/lib/snapshots/base-mcp.snap")
vm.Resume() // <100ms!
```

**Pros:**
- 50-200ms cold start
- Full VM isolation (Kata-level security)

**Cons:**
- Requires Firecracker (not standard K8s)
- Snapshots use RAM (256MB-512MB per snapshot)
- Complex to implement

---

## 2. Container Warm Pools (Fast: 200-500ms)

Keep pre-created containers ready, just inject the MCP image.

```
Pool (always running):
┌─────────────────────────────────────────────────────────────┐
│  Containerd - 10 warm containers in "created" state         │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│  │ Container 1  │ │ Container 2  │ │ Container 3  │ ...    │
│  │ - Namespace  │ │ - Namespace  │ │ - Namespace  │        │
│  │ - Cgroups    │ │ - Cgroups    │ │ - Cgroups    │        │
│  │ - Rootfs     │ │ - Rootfs     │ │ - Rootfs     │        │
│  │ - No process │ │ - No process │ │ - No process │        │
│  └──────────────┘ └──────────────┘ └──────────────┘        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼ Request for "my-mcp"
┌─────────────────────────────────────────────────────────────┐
│  1. Pull "my-mcp" image (if not cached)                     │
│  2. Mount image over warm container rootfs                  │
│  3. Start process                                           │
│  4. <200-500ms total!                                       │
└─────────────────────────────────────────────────────────────┘
```

**Implementation:**
```go
type WarmPool struct {
    available chan *PrecreatedContainer
}

func (p *WarmPool) GetContainer(image string, env map[string]string) (*Container, error) {
    // Get warm container from pool
    warm := <-p.available
    
    // Mount MCP image (overlayfs)
    warm.Mount(image)
    
    // Set env vars
    warm.SetEnv(env)
    
    // Start!
    warm.Start()
    
    return warm, nil
}
```

**Pros:**
- 200-500ms (vs 3-15s)
- Works with standard K8s
- Can use Kata or standard containers

**Cons:**
- Uses memory for warm pool (10 × 256MB = 2.5GB)
- Complex pool management

---

## 3. Zygote Process / Fork Pattern (Fastest for same-language: 10-50ms)

Keep a "zygote" process running, fork for each MCP.

```
┌─────────────────────────────────────────────────────────────┐
│  Zygote Process (always running)                            │
│  ├── Python/Node runtime loaded                             │
│  ├── Common libs imported (fastapi, etc.)                   │
│  ├── JSON-RPC handler ready                                 │
│  └── Waiting in loop...                                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼ Request for MCP
┌─────────────────────────────────────────────────────────────┐
│  fork() → Child process inherits everything                 │
│  exec() → Replace with MCP-specific code                    │
│  <10-50ms! (just fork overhead)                            │
└─────────────────────────────────────────────────────────────┘
```

**Used by:**
- PHP-FPM (process pool)
- Unreal Engine (zygote for game servers)

**Pros:**
- 10-50ms (fastest possible)
- Minimal memory overhead

**Cons:**
- Requires all MCPs use same language/runtime
- Complex security (shared memory between MCPs initially)
- Doesn't work for different container images

---

## 4. Unikernels (Fast: 10-100ms)

Single-purpose VMs that boot in milliseconds.

```
┌─────────────────────────────────────────────────────────────┐
│  OSv / Rumprun / MirageOS                                   │
│  ├── Only includes: kernel + app + minimal libs             │
│  ├── No init system, no shell, no unused drivers            │
│  └── Boots in 10-100ms                                      │
└─────────────────────────────────────────────────────────────┘
```

**Pros:**
- 10-100ms boot
- Tiny footprint (MB not GB)

**Cons:**
- MCPs must be built for specific unikernel
- Limited language support
- Can't run arbitrary containers

---

## 5. CRIU (Checkpoint/Restore in Userspace)

Freeze a running container, restore later.

```bash
# 1. Start and checkpoint
kubectl run mcp-base --image=mcp-runtime
kubectl exec mcp-base -- /app/init  # Pre-initialize
# Checkpoint
runc checkpoint mcp-base --image-path=/snapshots/base

# 2. On request - restore (100-300ms)
runc restore mcp-base --image-path=/snapshots/base
```

**Pros:**
- 100-300ms restore
- Works with standard containers
- Pre-initialized state

**Cons:**
- Complex (CRIU requires kernel patches sometimes)
- Snapshots large (full memory dump)
- Not widely supported in K8s

---

## 6. "Fast Path" with Pre-warmed Generic Containers

Hybrid approach: Pre-warm generic runtime, load MCP code dynamically.

```yaml
# Deployment with generic MCP runner
spec:
  replicas: 3  # Always 3 warm pods
  template:
    spec:
      containers:
        - name: mcp-runner
          image: agentarea/mcp-runner:latest  # Generic runner
          env:
            - name: MCP_CODE_URL
              value: "s3://mcp-code/{instance-id}/code.tar.gz"
```

On request:
1. Route to warm pod
2. Pod downloads MCP code (if not cached)
3. Start MCP in subprocess
4. Total: 200-500ms

**Pros:**
- Simple to implement
- Works with KEDA
- Warm pods always ready

**Cons:**
- Pods always consume resources (not true scale-to-zero)
- Security concern (shared runner)

---

## Comparison

| Approach | Cold Start | Isolation | Complexity | Best For |
|----------|------------|-----------|------------|----------|
| **Standard + KEDA** | 3-10s | Process | Low | General use |
| **Kata + KEDA** | 8-15s | VM | Medium | Security |
| **Firecracker Snapshots** | 50-200ms | MicroVM | High | Maximum speed |
| **Warm Pools** | 200-500ms | Container | Medium | Fast + standard K8s |
| **Zygote/Fork** | 10-50ms | Process | High | Same-language MCPs |
| **Unikernels** | 10-100ms | VM | Very High | Specialized builds |
| **CRIU** | 100-300ms | Container | High | Pre-init containers |
| **Pre-warmed Generic** | 200-500ms | Shared | Low | Simple implementation |

---

## Recommended for AgentArea

### Phase 1: Warm Pools (Fast + Practical)

```go
// MCP Manager maintains warm pool
type WarmPool struct {
    size int
    containers chan *WarmContainer
}

func (p *WarmPool) acquire(image string) (*Container, error) {
    warm := <-p.containers  // Wait for warm container
    
    // Mount MCP image
    overlay.Mount(warm.rootfs, image)
    
    // Start process
    warm.Start()
    
    // Refill pool asynchronously
    go p.warmUpOne()
    
    return warm, nil
}
```

**Trade-off:** Use 2-3GB RAM for warm pool → Get 200-500ms cold start

### Phase 2: Firecracker (If needed)

For untrusted MCPs that need both speed AND isolation:
- Snapshot pre-created VMs
- Restore in 50-200ms
- Requires separate infrastructure from K8s

### Phase 3: Hybrid per MCP

```yaml
spec:
  coldStartMode: "standard"     # 3-10s, scale-to-zero
  # OR
  coldStartMode: "warm-pool"    # 200-500s, uses memory
  # OR
  coldStartMode: "always-on"    # 0s, always running
```

---

## What AWS Lambda Actually Does

```
1. Firecracker microVMs
2. Pre-warmed execution environments (snapshots)
3. Zygote process for runtime (Java, Python, Node)
4. Code loaded via virtio-fs (copy-on-write)

Result: 50-200ms cold start for new container
        <10ms for "warm" container (already ran recently)
```

To match Lambda, we'd need similar infrastructure.

---

## Simplest Fast Option for Now

**Keep 1 replica always running (minReplicas: 1)**

```yaml
spec:
  serverless:
    enabled: true
    minReplicas: 1  # Always keep 1 warm
    maxReplicas: 10
    idleTimeout: "30m"  # Scale to zero only after 30 min
```

- First request: 0ms (warm)
- After 30min idle: scales to zero
- Next request: 3-15s (full cold start)

**Trade-off:** Pay for 1 replica always running, but fast for active MCPs.
