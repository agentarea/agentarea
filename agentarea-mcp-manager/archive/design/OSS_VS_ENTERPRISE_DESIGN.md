# OSS vs Enterprise Feature Split

## The Problem

**OSS Users:**
- Small deployments, trusted workloads
- Simple Docker or K8s setup
- Cost-conscious (don't want warm pool overhead)
- "Just make it work"

**Enterprise Users:**
- Multi-tenant, untrusted workloads
- Need isolation (Kata)
- Need fast cold starts (warm pool)
- Willing to pay for infrastructure

## Solution: Runtime Feature Flags + Build Tags

### 1. Runtime Configuration (Per-Instance)

```yaml
# OSS Simple Mode (default)
spec:
  tier: "standard"  # Simple container, no warm pool
  
  # OR - true serverless (scale to zero)
  tier: "serverless"
  serverless:
    enabled: true
    minReplicas: 0

# Enterprise Mode
spec:
  tier: "enterprise"  # Warm pool + Kata
  isolation: "kata"
  warmPool:
    enabled: true
```

### 2. Code Organization

```
internal/
├── backends/
│   ├── interface.go              # Common interface
│   ├── kubernetes_backend.go     # OSS - standard K8s
│   ├── kubernetes_backend_oss.go # OSS implementations
│   └── kubernetes_backend_enterprise.go  # +build enterprise
├── warmpool/
│   ├── interface.go              # Common interface
│   ├── noop.go                   # OSS - no-op implementation
│   └── client.go                 # +build enterprise
└── config/
    ├── config.go                 # OSS config
    └── config_enterprise.go      # +build enterprise
```

### 3. Build Tags Approach

```go
// +build !enterprise

// file: internal/warmpool/noop.go
package warmpool

// NoopClient for OSS - warm pool disabled
type NoopClient struct{}

func (n *NoopClient) FindAvailablePod(ctx context.Context) (*corev1.Pod, error) {
    return nil, ErrWarmPoolDisabled
}

func NewNoopClient() Client {
    return &NoopClient{}
}
```

```go
// +build enterprise

// file: internal/warmpool/client.go
package warmpool

// Real implementation for enterprise
type Client struct {
    client    kubernetes.Interface
    namespace string
}

func (c *Client) FindAvailablePod(ctx context.Context) (*corev1.Pod, error) {
    // Real implementation...
}
```

### 4. Factory Pattern

```go
// internal/backends/factory.go
package backends

func CreateBackend(cfg *config.Config) (Backend, error) {
    switch cfg.Mode {
    case "docker":
        return NewDockerBackend(cfg)
    case "kubernetes":
        return NewKubernetesBackend(cfg)
    case "kubernetes-enterprise":
        return NewKubernetesEnterpriseBackend(cfg) // +build enterprise
    default:
        return nil, fmt.Errorf("unknown mode: %s", cfg.Mode)
    }
}
```

## Feature Matrix

| Feature | OSS | Enterprise |
|---------|-----|------------|
| **Docker backend** | ✅ | ✅ |
| **K8s standard containers** | ✅ | ✅ |
| **K8s scale-to-zero (KEDA)** | ✅ | ✅ |
| **State reconciliation** | ✅ | ✅ |
| **Kata runtime** | ❌ | ✅ |
| **Warm pool** | ❌ | ✅ |
| **Firecracker** | ❌ | ✅ |
| **Advanced isolation** | ❌ | ✅ |
| **Priority support** | ❌ | ✅ |

## Implementation Strategy

### Option 1: Single Binary with Runtime Flags (Recommended)

Single codebase, features enabled by license/config:

```go
// main.go
func main() {
    cfg := config.Load()
    
    // Check license for enterprise features
    if cfg.WarmPool.Enabled && !license.IsEnterprise() {
        log.Fatal("Warm pool requires enterprise license")
    }
    
    backend := backends.New(cfg)
    // ...
}
```

**Pros:**
- Single binary to maintain
- Easy for users to upgrade
- Clear error messages

**Cons:**
- Enterprise code visible in OSS repo
- Need license checking infra

### Option 2: Build Tags (Clean Separation)

```bash
# OSS build
go build -o mcp-manager ./cmd/mcp-manager

# Enterprise build
go build -tags enterprise -o mcp-manager-enterprise ./cmd/mcp-manager
```

```go
// internal/features/features.go
// +build !enterprise

package features

var Enterprise = false

func init() {
    // Register no-op implementations
    warmpool.RegisterProvider("noop", warmpool.NewNoopClient)
}
```

```go
// internal/features/features_enterprise.go
// +build enterprise

package features

var Enterprise = true

func init() {
    // Register enterprise implementations
    warmpool.RegisterProvider("kata", warmpool.NewKataClient)
    warmpool.RegisterProvider("firecracker", warmpool.NewFirecrackerClient)
}
```

**Pros:**
- Clean separation at build time
- OSS repo doesn't contain enterprise code
- Smaller OSS binary

**Cons:**
- Two binaries to maintain
- Merge conflicts between branches

### Option 3: Plugin Architecture (Most Flexible)

```go
// Enterprise features as plugins

// OSS core
package main

func main() {
    // Load plugins
    plugins.LoadAll("/usr/lib/mcp-manager/plugins/")
    
    backend := backends.New(cfg)
    // ...
}
```

```go
// Enterprise plugin (separate repo)
package main

import "github.com/agentarea/mcp-manager/sdk"

func init() {
    sdk.RegisterBackend("enterprise-k8s", NewEnterpriseBackend)
}
```

**Pros:**
- True separation (plugins in private repo)
- OSS can't accidentally use enterprise features
- Can sell individual features

**Cons:**
- Complex plugin system
- Version compatibility issues
- Harder to develop

## Recommended: Option 1 (Runtime Flags) + Option 2 (Build Tags for Clean OSS)

### Repository Structure

```
agentarea-mcp-manager/
├── cmd/
│   └── mcp-manager/
│       └── main.go
├── internal/
│   ├── backends/
│   │   ├── interface.go
│   │   ├── docker.go
│   │   ├── kubernetes.go
│   │   └── kubernetes_enterprise.go      # +build enterprise
│   ├── warmpool/
│   │   ├── interface.go
│   │   ├── noop.go                       # OSS default
│   │   └── client.go                     # +build enterprise
│   └── license/
│       ├── validator.go                  # OSS - always false
│       └── validator_enterprise.go       # +build enterprise
├── pkg/
│   └── api/                              # Public API
├── enterprise/                           # Enterprise-only (submodule or separate repo)
│   ├── backends/
│   ├── warmpool/
│   └── cmd/
└── build/
    ├── Dockerfile.oss
    └── Dockerfile.enterprise
```

### Build Process

```makefile
# Makefile

.PHONY: build-oss build-enterprise

build-oss:
	go build -o bin/mcp-manager ./cmd/mcp-manager

build-enterprise:
	go build -tags enterprise -o bin/mcp-manager-enterprise ./cmd/mcp-manager

# Or use separate enterprise repo
docker-oss:
	docker build -f build/Dockerfile.oss -t agentarea/mcp-manager:latest .

docker-enterprise:
	docker build -f build/Dockerfile.enterprise -t agentarea/mcp-manager:enterprise .
```

### Runtime Behavior

```go
// internal/config/config.go

type Config struct {
    Mode string // "docker", "kubernetes", "kubernetes-enterprise"
    
    // OSS features (always available)
    Docker     DockerConfig
    Kubernetes KubernetesConfig
    
    // Enterprise features (gated)
    Enterprise EnterpriseConfig `json:"enterprise,omitempty"`
}

type EnterpriseConfig struct {
    Enabled       bool          `json:"enabled"`
    LicenseKey    string        `json:"license_key"`
    WarmPool      WarmPoolConfig
    AdvancedIsolation bool
}
```

### Graceful Degradation

```go
func (p *KubernetesProvider) Create(ctx context.Context, instance *models.MCPServerInstance) error {
    // Check if warm pool requested
    if instance.Tier == "enterprise" {
        if !license.IsValid() {
            // Fallback to standard mode
            log.Warn("Enterprise tier requested but no license, falling back to standard")
            return p.createStandard(ctx, instance)
        }
        
        // Use enterprise warm pool
        return p.createWithWarmPool(ctx, instance)
    }
    
    // OSS standard path
    return p.createStandard(ctx, instance)
}
```

## Helm Chart Differences

### OSS Chart

```yaml
# values.yaml (OSS)
mcpManager:
  mode: "kubernetes"  # or "docker"
  
  standard:
    enabled: true
    minReplicas: 1    # Simple, always-on
```

### Enterprise Chart

```yaml
# values.yaml (Enterprise)
mcpManager:
  mode: "kubernetes-enterprise"
  
  enterprise:
    enabled: true
    licenseKey: "license-key-here"
    
    warmPool:
      enabled: true
      size: 10
      
    isolation:
      runtimeClass: "kata-qemu"
```

## Development Workflow

### OSS Development

```bash
# Clone OSS repo
git clone https://github.com/agentarea/mcp-manager.git
cd mcp-manager

# Build and run
go run ./cmd/mcp-manager
```

### Enterprise Development

```bash
# Clone enterprise repo (includes OSS as submodule or vendor)
git clone https://github.com/agentarea/mcp-manager-enterprise.git
cd mcp-manager-enterprise

# Pull OSS updates
git submodule update --remote

# Build with enterprise features
go build -tags enterprise ./cmd/mcp-manager
```

## Summary

| Approach | When to Use |
|----------|-------------|
| **Runtime flags** | Keep single binary, simple license check |
| **Build tags** | Clean OSS repo without enterprise code |
| **Separate repo** | True separation, enterprise is private |
| **Plugins** | Sell individual features |

### Recommendation

1. **Now**: Runtime flags in single repo
   - Easy to develop
   - Clear feature gating
   - OSS users get clear "enterprise feature" messages

2. **Later**: Split to separate repos
   - Move enterprise code to private repo
   - OSS repo imports enterprise as optional module
   - Clean separation

```go
// Clear error message for OSS users
tier := getTier(instance)
if tier == "enterprise" && !license.IsValid() {
    return fmt.Errorf(
        "tier 'enterprise' requires a license. " +
        "Contact sales@agentarea.ai or use tier 'standard' for OSS"
    )
}
```
