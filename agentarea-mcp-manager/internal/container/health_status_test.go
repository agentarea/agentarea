package container

import (
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/models"
)

func unreachable(containerID string) *HealthCheckResult {
	return &HealthCheckResult{ContainerID: containerID, Status: models.StatusRunning, Error: "connect: connection refused"}
}

func reachable(containerID string) *HealthCheckResult {
	return &HealthCheckResult{ContainerID: containerID, Status: models.StatusRunning, Healthy: true, HTTPReachable: true}
}

// mcp-base opens its port only after the stdio server initializes, which for
// an npx package includes the install. A probe landing in that window must not
// report the start as failed; once the workload has answered, or the window has
// passed, an unreachable endpoint is a failure again.
func TestHealthProbeReportsFailureOnlyAfterTheWorkloadCouldHaveStarted(t *testing.T) {
	manager := &Manager{config: testConfig("docker"), logger: discardLogger(),
		containerHealth: map[string]*HealthCheckResult{}}

	starting := &models.Container{ID: "first", Name: "mcp-starting", Status: models.StatusRunning, CreatedAt: time.Now()}
	manager.updateContainerHealth(starting, unreachable("first"))
	if starting.Status != models.StatusRunning {
		t.Fatalf("status = %q while the workload is still starting, want running", starting.Status)
	}
	manager.updateContainerHealth(starting, reachable("first"))
	manager.updateContainerHealth(starting, unreachable("first"))
	if starting.Status != models.StatusError {
		t.Fatalf("status = %q after a workload that answered stopped answering, want error", starting.Status)
	}

	// The idle sweep reclaims it and the next call starts a new container under
	// the same name; the old container's answers do not make this one late.
	restarted := &models.Container{ID: "second", Name: "mcp-starting", Status: models.StatusRunning, CreatedAt: time.Now()}
	manager.updateContainerHealth(restarted, unreachable("second"))
	if restarted.Status != models.StatusRunning {
		t.Fatalf("status = %q for a restarted workload still starting, want running", restarted.Status)
	}

	window := manager.config.Container.StartupTimeout
	late := &models.Container{ID: "late", Name: "mcp-late", Status: models.StatusRunning, CreatedAt: time.Now().Add(-2 * window)}
	manager.updateContainerHealth(late, unreachable("late"))
	if late.Status != models.StatusError {
		t.Fatalf("status = %q for a workload that never listened within %s, want error", late.Status, window)
	}
}
