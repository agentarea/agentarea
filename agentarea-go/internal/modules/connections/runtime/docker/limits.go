package docker

import (
	"fmt"
	"math"
	"strconv"
	"strings"
)

// parseCPULimit reads a core count. NaN and Inf are refused: neither survives a
// comparison, so either would turn the host's ceiling off.
func parseCPULimit(value string) (float64, error) {
	parsed, err := strconv.ParseFloat(strings.TrimSpace(value), 64)
	if err != nil {
		return 0, err
	}
	if math.IsNaN(parsed) || math.IsInf(parsed, 0) {
		return 0, fmt.Errorf("%q is not a finite number", value)
	}
	if parsed <= 0 {
		return 0, fmt.Errorf("%q is not a positive number", value)
	}
	return parsed, nil
}

// parseMemoryLimit reads the runtime's memory syntax: a byte count with an
// optional b/k/m/g suffix. A suffix that overflows int64 is refused rather than
// wrapping negative under every maximum.
func parseMemoryLimit(value string) (int64, error) {
	trimmed := strings.TrimSpace(strings.ToLower(value))
	if trimmed == "" {
		return 0, fmt.Errorf("empty")
	}
	multiplier := int64(1)
	switch trimmed[len(trimmed)-1] {
	case 'b':
		trimmed = trimmed[:len(trimmed)-1]
	case 'k':
		multiplier, trimmed = 1024, trimmed[:len(trimmed)-1]
	case 'm':
		multiplier, trimmed = 1024*1024, trimmed[:len(trimmed)-1]
	case 'g':
		multiplier, trimmed = 1024*1024*1024, trimmed[:len(trimmed)-1]
	}
	amount, err := strconv.ParseInt(strings.TrimSpace(trimmed), 10, 64)
	if err != nil || amount <= 0 {
		return 0, fmt.Errorf("not a positive byte count")
	}
	if amount > math.MaxInt64/multiplier {
		return 0, fmt.Errorf("byte count %s does not fit in int64", value)
	}
	return amount * multiplier, nil
}

// enforceCeiling refuses a workload asking for more than the host allows. The
// limits are caller input; refusing keeps the outcome legible where clamping
// would fail later inside the workload.
func (c Config) enforceCeiling(memory, cpu string) error {
	if memory != "" {
		requested, err := parseMemoryLimit(memory)
		if err != nil {
			return fmt.Errorf("memory limit %q: %w", memory, err)
		}
		maximum, err := parseMemoryLimit(c.MaxMemory)
		if err != nil {
			return fmt.Errorf("AGENTAREA_MCP_MAX_MEMORY %q is unusable, refusing the requested %s: %w", c.MaxMemory, memory, err)
		}
		if requested > maximum {
			return fmt.Errorf("requested memory %s exceeds the %s this host allows", memory, c.MaxMemory)
		}
	}
	if cpu != "" {
		requested, err := parseCPULimit(cpu)
		if err != nil {
			return fmt.Errorf("cpu limit %q is not a positive number", cpu)
		}
		maximum, err := parseCPULimit(c.MaxCPU)
		if err != nil {
			return fmt.Errorf("AGENTAREA_MCP_MAX_CPU %q is unusable, refusing the requested %s", c.MaxCPU, cpu)
		}
		if requested > maximum {
			return fmt.Errorf("requested cpu %s exceeds the %s this host allows", cpu, c.MaxCPU)
		}
	}
	return nil
}

// defaultLimits is what a workload naming no limit starts with: CPU in
// millicores and memory in bytes, zero where none is configured.
func (c Config) defaultLimits() (cpuMillicores, memoryBytes int64, err error) {
	if c.DefaultCPU != "" {
		cpus, err := parseCPULimit(c.DefaultCPU)
		if err != nil {
			return 0, 0, fmt.Errorf("default cpu limit %q: %w", c.DefaultCPU, err)
		}
		cpuMillicores = int64(math.Round(cpus * 1000))
	}
	if c.DefaultMemory != "" {
		memoryBytes, err = parseMemoryLimit(c.DefaultMemory)
		if err != nil {
			return 0, 0, fmt.Errorf("default memory limit %q: %w", c.DefaultMemory, err)
		}
	}
	return cpuMillicores, memoryBytes, nil
}
