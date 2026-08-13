package container

import (
	"testing"

	"github.com/agentarea/mcp-manager/internal/models"
)

// A ceiling is only a ceiling if it can be compared. ParseFloat accepts NaN and
// Inf: every comparison with NaN is false, so a NaN maximum admits any request,
// and an Inf maximum is above every finite one. Either leaves the host's limit
// nominally configured and actually off, which is the same fail-open the
// unreadable-maximum case already refuses.
func TestNonFiniteCPUCeilingRefusesRatherThanAdmittingEverything(t *testing.T) {
	runtime, _ := stubRuntime(t)

	for name, tc := range map[string]struct{ maxCPU, requested string }{
		"nan maximum":   {"NaN", "4"},
		"inf maximum":   {"Inf", "64"},
		"nan requested": {"1.0", "NaN"},
		"inf requested": {"1.0", "+Inf"},
	} {
		manager := &Manager{config: testConfig(runtime), logger: discardLogger(),
			containers: map[string]*models.Container{}}
		manager.config.Container.MaxMemoryLimit = "512m"
		manager.config.Container.MaxCPULimit = tc.maxCPU

		err := manager.enforceResourceCeiling(&models.Container{
			Name: "c", MemoryLimit: "256m", CPULimit: tc.requested,
		})
		if err == nil {
			t.Fatalf("%s: max %q accepted %q; a ceiling that cannot be compared must refuse",
				name, tc.maxCPU, tc.requested)
		}
	}
}

func TestFiniteCPURequestInsideTheCeilingIsStillAdmitted(t *testing.T) {
	runtime, _ := stubRuntime(t)

	manager := &Manager{config: testConfig(runtime), logger: discardLogger(),
		containers: map[string]*models.Container{}}
	manager.config.Container.MaxMemoryLimit = "512m"
	manager.config.Container.MaxCPULimit = "2"

	err := manager.enforceResourceCeiling(&models.Container{
		Name: "c", MemoryLimit: "256m", CPULimit: "1.5",
	})
	if err != nil {
		t.Fatalf("refused a request inside the ceiling: %v", err)
	}
}
