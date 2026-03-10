# Feature Flags

<Info>
Control feature rollout with a pluggable feature flag system. Enable gradual rollouts, A/B testing, and environment-specific configurations.
</Info>

## Overview

AgentArea uses a flexible feature flag system for:

- **Gradual Rollouts**: Enable features for subsets of users
- **Environment Configuration**: Different features per environment
- **A/B Testing**: Test new features with control groups
- **Emergency Toggles**: Quickly disable problematic features

---

## Available Features

| Feature | Description | Default |
|---------|-------------|---------|
| `warm_pool` | Enable warm pool fast activation | `false` |
| `gateway_api` | Use Gateway API HTTPRoute | `false` |
| `state_reconciler` | Background state reconciliation | `false` |

---

## Configuration

### Environment Variables

```bash
# Enable features via environment variable
MCP_FEATURES_ENABLED=warm_pool,gateway_api,state_reconciler
```

### Configuration File

```yaml
# config/features.yaml
features:
  warm_pool:
    enabled: true
    description: "Enable warm pool for fast MCP activation"
    
  gateway_api:
    enabled: false
    description: "Use Gateway API instead of Ingress"
    
  state_reconciler:
    enabled: true
    description: "Background reconciliation of MCP state"
```

---

## Implementation

### Feature Flag Provider

```go
// internal/features/features.go
type Provider interface {
    IsEnabled(feature string) bool
    GetConfig(feature string) (map[string]interface{}, error)
    GetAll() map[string]bool
}

// Environment-based provider
type EnvProvider struct {
    enabled map[string]bool
}

func NewEnvProvider() *EnvProvider {
    enabledStr := os.Getenv("MCP_FEATURES_ENABLED")
    enabled := make(map[string]bool)
    
    for _, feature := range strings.Split(enabledStr, ",") {
        feature = strings.TrimSpace(feature)
        if feature != "" {
            enabled[feature] = true
        }
    }
    
    return &EnvProvider{enabled: enabled}
}

func (p *EnvProvider) IsEnabled(feature string) bool {
    return p.enabled[feature]
}
```

### Usage in Code

```go
// Check if feature is enabled
if features.IsEnabled("warm_pool") {
    // Use warm pool activation
    err := m.warmPoolClient.Activate(instance)
} else {
    // Standard container creation
    err := m.backend.CreateInstance(instance)
}
```

### Feature-Gated Routes

```go
// Conditional route registration
if features.IsEnabled("gateway_api") {
    router.HandleFunc("/instances", handlers.CreateInstance).Methods("POST")
} else {
    router.HandleFunc("/instances", handlers.CreateInstanceLegacy).Methods("POST")
}
```

---

## Provider Types

### Environment Provider

Simple on/off based on environment variables:

```go
provider := NewEnvProvider()
// MCP_FEATURES_ENABLED=warm_pool,gateway_api
```

### Config Provider

Load from configuration file:

```go
provider := NewConfigProvider("config/features.yaml")
```

### Hybrid Provider

Combine multiple sources with precedence:

```go
provider := NewHybridProvider(
    NewEnvProvider(),      // Highest priority
    NewConfigProvider(),   // Fallback
)
```

---

## Best Practices

<Accordion>
  <AccordionItem title="Feature Naming">
    - Use snake_case for feature names
    - Be descriptive: `enable_raft_consensus` vs `new_feature`
    - Group related features: `billing_v2`, `billing_v2_invoices`
  </AccordionItem>
  
  <AccordionItem title="Rollout Strategy">
    - Start with features disabled
    - Enable in development first
    - Use staging for validation
    - Gradual production rollout
  </AccordionItem>
  
  <AccordionItem title="Cleanup">
    - Remove feature flags after full rollout
    - Document removal timeline
    - Update configuration files
  </AccordionItem>
</Accordion>

---

## Monitoring

### Feature Metrics

```yaml
# Prometheus metrics
feature_flag_enabled{feature="warm_pool"} 1
feature_flag_enabled{feature="gateway_api"} 0
feature_flag_check_total{feature="warm_pool", result="enabled"} 1523
feature_flag_check_total{feature="warm_pool", result="disabled"} 42
```

---

## Next Steps

<CardGroup cols={2}>
  <Card title="Warm Pool" icon="bolt" href="/warm-pool">
    Fast MCP activation
  </Card>
  <Card title="Deployment" icon="server" href="/deployment">
    Deploy with feature flags
  </Card>
</CardGroup>
