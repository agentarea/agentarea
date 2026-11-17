// Package runtime is the MCP workload lifecycle (the merged mcp-manager): it
// loads an instance, builds its workload spec, starts it on demand under the
// instance's lifecycle lock, holds request leases, reaps idle workloads and
// retires them on deletion. It implements connections' service.Runtime and the
// gateway's Runtime.
package runtime

import (
	"errors"
	"fmt"
	"os"
	"slices"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
)

// Backends a deployment runs MCP workloads on (AGENTAREA_MCP_BACKEND).
const (
	BackendDocker     = "docker"
	BackendKubernetes = "kubernetes"
	BackendDataplane  = "dataplane"
)

const (
	defaultBaseImage = "agentarea/agentarea-mcp-base:latest"
	minSecretLength  = 32
)

// Config is the runtime's environment.
type Config struct {
	// Backend is AGENTAREA_MCP_BACKEND; empty detects kubernetes from the
	// service-account environment, else docker. The data plane is never detected.
	Backend string
	// GatewaySecret is AGENTAREA_MCP_GATEWAY_SECRET: it authenticates callers
	// of the gateway and derives each instance's context key and storage token.
	GatewaySecret  string
	LeaseTTL       time.Duration
	StartupTimeout time.Duration
	// IdleTimeout 0 disables the reaper.
	IdleTimeout   time.Duration
	SweepInterval time.Duration
	// BaseImage runs command instances (npx/uvx) on mcp-base.
	BaseImage string
}

// LoadConfig reads AGENTAREA_MCP_*: the lease, startup, idle and sweep
// durations are required, as the manager required them.
func LoadConfig(l *config.Loader) Config {
	c := Config{
		Backend:        LoadBackend(l),
		GatewaySecret:  l.RequiredEnv("AGENTAREA_MCP_GATEWAY_SECRET"),
		LeaseTTL:       requiredDuration(l, "AGENTAREA_MCP_LEASE_TTL", false),
		StartupTimeout: requiredDuration(l, "AGENTAREA_MCP_STARTUP_TIMEOUT", false),
		IdleTimeout:    requiredDuration(l, "AGENTAREA_MCP_IDLE_TIMEOUT", true),
		SweepInterval:  requiredDuration(l, "AGENTAREA_MCP_SWEEP_INTERVAL", false),
		BaseImage:      l.StringEnv("AGENTAREA_MCP_BASE_IMAGE", defaultBaseImage),
	}
	switch {
	case c.GatewaySecret != "" && len(c.GatewaySecret) < minSecretLength:
		l.Fail("AGENTAREA_MCP_GATEWAY_SECRET", fmt.Errorf("must contain at least %d bytes", minSecretLength))
	case slices.Contains(publishedGatewaySecrets(), c.GatewaySecret):
		l.Fail("AGENTAREA_MCP_GATEWAY_SECRET", errors.New("is a value published in the AgentArea repository; generate a new one and restart every service that shares it"))
	}
	return c
}

// LoadBackend reads AGENTAREA_MCP_BACKEND; unset detects kubernetes from the
// service-account environment, else docker. The data plane is never detected.
func LoadBackend(l *config.Loader) string {
	b := l.OneOfEnv("AGENTAREA_MCP_BACKEND", "", BackendDocker, BackendKubernetes, BackendDataplane)
	if b == "" {
		_, inCluster := l.OptionalEnv("KUBERNETES_SERVICE_HOST")
		b = detectBackend(inCluster)
	}
	return b
}

// requiredDuration reads a duration that must be set; "0" is accepted where
// zero is (the chart writes a bare 0 to disable the reaper).
func requiredDuration(l *config.Loader, name string, allowZero bool) time.Duration {
	raw := l.RequiredEnv(name)
	if raw == "" {
		return 0
	}
	if allowZero && raw == "0" {
		return 0
	}
	d, err := config.ParseDuration(raw)
	switch {
	case err != nil:
		l.Fail(name, err)
	case d < 0 || (!allowZero && d == 0):
		l.Fail(name, fmt.Errorf("must be %s", map[bool]string{true: "non-negative", false: "positive"}[allowZero]))
	}
	return d
}

// publishedGatewaySecrets are values .env.example and the dev compose file
// once shipped: anyone can sign gateway and storage tokens with them.
func publishedGatewaySecrets() []string {
	return []string{
		"dev-mcp-gateway-auth-secret-change-in-prod-00000000", // pragma: allowlist secret
		"agentarea-dev-mcp-gateway-secret-change-me",          // pragma: allowlist secret
	}
}

func detectBackend(inCluster bool) string {
	if inCluster {
		return BackendKubernetes
	}
	if _, err := os.Stat("/var/run/secrets/kubernetes.io/serviceaccount/token"); err == nil {
		return BackendKubernetes
	}
	return BackendDocker
}
