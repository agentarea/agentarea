// Package docker runs MCP workloads as Docker or Podman containers through
// the runtime's CLI. It holds no record of its own: every answer comes from
// the runtime, so a restart forgets nothing.
package docker

import (
	"errors"
	"fmt"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/runtime/workload"
)

// Config is the container host an MCP workload runs on.
type Config struct {
	// Runtime is the CLI binary: docker or podman.
	Runtime string
	// Network is the network containers join: the gateway's and nothing of
	// the platform's (no database, Valkey, Hydra or OpenFGA on it).
	Network string
	// NamePrefix starts every container name.
	NamePrefix string
	// MaxContainers is how many live workloads the host carries.
	MaxContainers int
	// DefaultMemory and DefaultCPU size a workload that names no limit.
	DefaultMemory string
	DefaultCPU    string
	// MaxMemory and MaxCPU are the most a workload may ask for.
	MaxMemory string
	MaxCPU    string
	// IsolationTier confines a workload whose spec names no tier.
	IsolationTier string
	// LogWorkloadOutput adds a failed workload's redacted output to the log.
	LogWorkloadOutput bool
}

// LoadConfig reads AGENTAREA_MCP_RUNTIME, AGENTAREA_MCP_NETWORK,
// AGENTAREA_MCP_NAME_PREFIX, AGENTAREA_MCP_MAX_CONTAINERS, AGENTAREA_MCP_MEMORY,
// AGENTAREA_MCP_CPU, AGENTAREA_MCP_MAX_MEMORY, AGENTAREA_MCP_MAX_CPU,
// AGENTAREA_MCP_ISOLATION and AGENTAREA_LOG_WORKLOAD. The maxima default to
// the defaults: a workload may size itself down, never up, unless the host says so.
func LoadConfig(l *config.Loader) Config {
	cfg := Config{
		Runtime:           l.OneOfEnv("AGENTAREA_MCP_RUNTIME", "docker", "docker", "podman"),
		Network:           l.StringEnv("AGENTAREA_MCP_NETWORK", "agentarea_mcp-network"),
		NamePrefix:        l.StringEnv("AGENTAREA_MCP_NAME_PREFIX", "mcp-"),
		MaxContainers:     l.IntEnv("AGENTAREA_MCP_MAX_CONTAINERS", 50),
		DefaultMemory:     l.StringEnv("AGENTAREA_MCP_MEMORY", "512m"),
		DefaultCPU:        l.StringEnv("AGENTAREA_MCP_CPU", "1.0"),
		IsolationTier:     l.OneOfEnv("AGENTAREA_MCP_ISOLATION", workload.IsolationUntrusted, workload.IsolationTiers()...),
		LogWorkloadOutput: l.BoolEnv("AGENTAREA_LOG_WORKLOAD", false),
	}
	cfg.MaxMemory = l.StringEnv("AGENTAREA_MCP_MAX_MEMORY", cfg.DefaultMemory)
	cfg.MaxCPU = l.StringEnv("AGENTAREA_MCP_MAX_CPU", cfg.DefaultCPU)
	for _, v := range []struct {
		name string
		err  error
	}{
		{"AGENTAREA_MCP_MEMORY", memoryErr(cfg.DefaultMemory)},
		{"AGENTAREA_MCP_MAX_MEMORY", memoryErr(cfg.MaxMemory)},
		{"AGENTAREA_MCP_CPU", cpuErr(cfg.DefaultCPU)},
		{"AGENTAREA_MCP_MAX_CPU", cpuErr(cfg.MaxCPU)},
	} {
		if v.err != nil {
			l.Fail(v.name, v.err)
		}
	}
	if cfg.MaxContainers < 1 {
		l.Fail("AGENTAREA_MCP_MAX_CONTAINERS", errors.New("must be at least 1"))
	}
	return cfg
}

func memoryErr(v string) error {
	_, err := parseMemoryLimit(v)
	return err
}

func cpuErr(v string) error {
	_, err := parseCPULimit(v)
	return err
}

func (c Config) validate() error {
	switch {
	case c.Runtime == "":
		return errors.New("docker backend: no container runtime configured")
	case c.Network == "":
		return errors.New("docker backend: no network configured")
	case c.Network == "host" || strings.HasSuffix(c.Network, "_default"):
		return fmt.Errorf("docker backend: network %q is shared with the platform's services (a compose project's default network, "+
			"or the host's); workloads need a network of their own that only the gateway also joins (AGENTAREA_MCP_NETWORK)", c.Network)
	case c.MaxContainers < 1:
		return fmt.Errorf("docker backend: max containers %d is below 1", c.MaxContainers)
	}
	if _, err := workload.ResolveIsolation(c.IsolationTier); err != nil {
		return fmt.Errorf("docker backend: %w", err)
	}
	return nil
}
