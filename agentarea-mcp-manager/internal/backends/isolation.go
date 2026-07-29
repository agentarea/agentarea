package backends

import (
	"slices"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/models"
)

// resolveSpecIsolation turns a spec's declared tier into concrete settings.
//
// Both backends call this so the meaning of a tier is defined once. What each
// backend then does with it differs — Docker renders flags, Kubernetes builds a
// pod security context — but "what does untrusted mean" must not.
func resolveSpecIsolation(spec *InstanceSpec, defaultTier string) (models.Isolation, error) {
	tier := spec.IsolationTier
	if tier == "" {
		tier = defaultTier
	}

	isolation, err := config.ResolveIsolation(tier)
	if err != nil {
		return models.Isolation{}, err
	}

	// An explicit runtime/writable-path on the spec refines the tier. Neither
	// can weaken it: a runtime class is an addition, and marking paths writable
	// only takes effect together with a read-only root.
	if spec.RuntimeClass != "" {
		isolation.Runtime = spec.RuntimeClass
	}
	if len(spec.WritablePaths) > 0 {
		isolation.ReadOnlyRootFilesystem = true
		isolation.WritablePaths = spec.WritablePaths
	}

	return isolation, nil
}

// tightenDropCapabilities merges the operator's configured drops with the
// tier's. Dropping a capability twice is harmless; missing one is not, so the
// union is the safe combination.
func tightenDropCapabilities(configured []string, iso models.Isolation) []string {
	merged := append([]string(nil), configured...)
	for _, capability := range iso.DropCapabilities {
		if !slices.Contains(merged, capability) {
			merged = append(merged, capability)
		}
	}
	return merged
}

// tightenRuntimeClass picks the runtime class for a workload.
//
// The operator's cluster-wide class always wins: a per-workload request must
// never be able to drop a sandbox runtime the cluster enforces. Below that, a
// tier asking for a runtime (untrusted wanting gVisor) outranks a bare spec
// field, because the tier is the platform's judgement about the code and the
// spec field is the caller's.
func tightenRuntimeClass(configured string, iso models.Isolation, specRuntimeClass string) string {
	if configured != "" {
		return configured
	}
	if iso.Runtime != "" {
		return iso.Runtime
	}
	return specRuntimeClass
}
