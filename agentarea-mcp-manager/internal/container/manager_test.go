package container

import (
	"context"
	"errors"
	"fmt"
	"testing"
	"time"

	"log/slog"
	"os"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/models"
)

func TestNewManager(t *testing.T) {
	cfg := &config.Config{
		Container: config.ContainerConfig{
			NamePrefix:    "test-",
			MaxContainers: 10,
		},
		Redis: config.RedisConfig{
			URL: "redis://localhost:6379",
		},
	}
	logger := slog.New(slog.NewTextHandler(os.Stdout, nil))

	manager := NewManager(cfg, logger)

	if manager == nil {
		t.Fatal("Expected manager to be created")
	}

	if len(manager.containers) != 0 {
		t.Errorf("Expected empty containers map, got %d containers", len(manager.containers))
	}
}

func TestGetRunningCount(t *testing.T) {
	cfg := &config.Config{
		Container: config.ContainerConfig{
			NamePrefix:    "test-",
			MaxContainers: 10,
		},
		Redis: config.RedisConfig{
			URL: "redis://localhost:6379",
		},
	}
	logger := slog.New(slog.NewTextHandler(os.Stdout, nil))
	manager := NewManager(cfg, logger)

	// Initially should be 0
	count := manager.GetRunningCount()
	if count != 0 {
		t.Errorf("Expected 0 running containers, got %d", count)
	}

	// Add a running container
	manager.containers["test-container"] = &models.Container{
		Name:   "test-container",
		Status: models.StatusRunning,
	}

	count = manager.GetRunningCount()
	if count != 1 {
		t.Errorf("Expected 1 running container, got %d", count)
	}

	// Add a stopped container
	manager.containers["test-container-2"] = &models.Container{
		Name:   "test-container-2",
		Status: models.StatusStopped,
	}

	count = manager.GetRunningCount()
	if count != 1 {
		t.Errorf("Expected 1 running container, got %d", count)
	}
}

// stubSecretResolver records the names it was asked to resolve and returns a
// fixed decrypted value per name, or err when set.
type stubSecretResolver struct {
	gotInstanceID string
	gotNames      []string
	values        map[string]string
	err           error
}

func (s *stubSecretResolver) ResolveInstanceEnvVars(instanceID string, names []string) (map[string]string, error) {
	s.gotInstanceID = instanceID
	s.gotNames = names
	if s.err != nil {
		return nil, s.err
	}
	out := make(map[string]string)
	for _, n := range names {
		if v, ok := s.values[n]; ok {
			out[n] = v
		}
	}
	return out, nil
}

func newTestManager(t *testing.T) *Manager {
	t.Helper()
	cfg := &config.Config{
		Container: config.ContainerConfig{NamePrefix: "test-", MaxContainers: 10},
		Redis:     config.RedisConfig{URL: "redis://localhost:6379"},
	}
	return NewManager(cfg, slog.New(slog.NewTextHandler(os.Stdout, nil)))
}

func TestResolveSecretEnvVars_DecryptsNamedSecrets(t *testing.T) {
	manager := newTestManager(t)
	stub := &stubSecretResolver{values: map[string]string{
		"TELEGRAM_API_ID":   "35280380",
		"TELEGRAM_API_HASH": "deadbeef",
	}}
	manager.SetSecretResolver(stub)

	jsonSpec := map[string]interface{}{
		"type":        "command",
		"environment": map[string]interface{}{}, // secrets stripped out at create time
		"env_vars":    []interface{}{"TELEGRAM_API_ID", "TELEGRAM_API_HASH"},
	}

	got, err := manager.ResolveSecretEnvVars("inst-1", jsonSpec)
	if err != nil {
		t.Fatalf("ResolveSecretEnvVars() error = %v, want nil", err)
	}

	if stub.gotInstanceID != "inst-1" {
		t.Errorf("expected resolver called with instance inst-1, got %q", stub.gotInstanceID)
	}
	if got["TELEGRAM_API_ID"] != "35280380" || got["TELEGRAM_API_HASH"] != "deadbeef" {
		t.Errorf("expected decrypted secrets, got %v", got)
	}
}

func TestResolveSecretEnvVars_NoResolverIsNoop(t *testing.T) {
	manager := newTestManager(t) // no SetSecretResolver
	got, err := manager.ResolveSecretEnvVars("inst-1", map[string]interface{}{
		"env_vars": []interface{}{"TELEGRAM_API_ID"},
	})
	if err != nil {
		t.Fatalf("ResolveSecretEnvVars() error = %v, want nil", err)
	}
	if len(got) != 0 {
		t.Errorf("expected empty map without a resolver, got %v", got)
	}
}

func TestResolveSecretEnvVars_NoEnvVarsIsNoop(t *testing.T) {
	manager := newTestManager(t)
	manager.SetSecretResolver(&stubSecretResolver{values: map[string]string{"X": "y"}})
	got, err := manager.ResolveSecretEnvVars("inst-1", map[string]interface{}{
		"environment": map[string]interface{}{"LOG_LEVEL": "info"},
	})
	if err != nil {
		t.Fatalf("ResolveSecretEnvVars() error = %v, want nil", err)
	}
	if len(got) != 0 {
		t.Errorf("expected empty map when json_spec has no env_vars, got %v", got)
	}
}

// A container that starts without the secrets its spec asked for looks healthy
// and fails somewhere downstream, against whatever the missing credential was
// guarding. Reporting the failure is what lets the caller skip the container.
func TestResolveSecretEnvVars_ResolverFailureIsReported(t *testing.T) {
	manager := newTestManager(t)
	manager.SetSecretResolver(&stubSecretResolver{err: errors.New("secret lookup failed")})

	got, err := manager.ResolveSecretEnvVars("inst-1", map[string]interface{}{
		"env_vars": []interface{}{"TELEGRAM_API_ID"},
	})
	if err == nil {
		t.Fatalf("ResolveSecretEnvVars() error = nil, want the resolver failure; got env %v", got)
	}
	if got != nil {
		t.Errorf("ResolveSecretEnvVars() env = %v, want nil alongside an error", got)
	}
}

func TestHandleMCPInstanceCreated_ValidationOnly(t *testing.T) {
	cfg := &config.Config{
		Container: config.ContainerConfig{
			NamePrefix:    "test-",
			MaxContainers: 10,
		},
		Redis: config.RedisConfig{
			URL: "redis://localhost:6379",
		},
	}
	logger := slog.New(slog.NewTextHandler(os.Stdout, nil))
	manager := NewManager(cfg, logger)

	ctx := context.Background()
	instanceID := "test-instance-123"
	name := "test-nginx"
	jsonSpec := map[string]interface{}{
		"image": "nginx:alpine",
		"port":  80,
		"environment": map[string]interface{}{
			"TEST_VAR": "test_value",
		},
	}

	// This test focuses on validation without actually creating containers
	// We expect this to fail because we're not running podman in test environment
	err := manager.HandleMCPInstanceCreated(ctx, instanceID, name, jsonSpec)

	// We expect an error since we can't actually create containers in tests
	// But we want to ensure the validation logic runs without panics/deadlocks
	if err == nil {
		t.Error("Expected error when trying to create container without podman")
	}

	// Verify the container was not added to tracking map due to failure
	containerName := manager.config.GetContainerName(name)
	if _, exists := manager.containers[containerName]; exists {
		t.Error("Container should not be in tracking map after failed creation")
	}
}

func TestDeadlockPrevention(t *testing.T) {
	cfg := &config.Config{
		Container: config.ContainerConfig{
			NamePrefix:    "test-",
			MaxContainers: 10,
		},
		Redis: config.RedisConfig{
			URL: "redis://localhost:6379",
		},
	}
	logger := slog.New(slog.NewTextHandler(os.Stdout, nil))
	manager := NewManager(cfg, logger)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	// This should complete within timeout and not deadlock
	done := make(chan bool, 1)
	go func() {
		// Call GetRunningCount multiple times concurrently to test for deadlocks
		for i := 0; i < 100; i++ {
			manager.GetRunningCount()
		}
		done <- true
	}()

	select {
	case <-done:
		// Test passed - no deadlock
	case <-ctx.Done():
		t.Fatal("Deadlock detected - GetRunningCount calls did not complete within timeout")
	}
}

// A container that is stopped or failed holds no memory, no CPU and no port on
// the host — it is a record of something that used to run. Counting it against
// MaxContainers spends a ceiling meant to protect the host's RAM on corpses.
//
// This is not hypothetical. Eleven such records — every one pinned to a registry
// deleted with the previous cluster, all stopped or error — filled the RU host's
// eight slots for two days, and every MCP launch failed with "maximum container
// limit reached (8)" while the machine sat idle.
func TestOccupiedSlotsIgnoresDeadContainers(t *testing.T) {
	cfg := &config.Config{
		Container: config.ContainerConfig{
			NamePrefix:    "test-",
			MaxContainers: 8,
		},
		Redis: config.RedisConfig{
			URL: "redis://localhost:6379",
		},
	}
	manager := NewManager(cfg, slog.New(slog.NewTextHandler(os.Stdout, nil)))

	dead := []models.ContainerStatus{
		models.StatusStopped,
		models.StatusError,
		models.StatusStopped,
	}
	for i, status := range dead {
		manager.containers[fmt.Sprintf("dead-%d", i)] = &models.Container{
			Name:   fmt.Sprintf("dead-%d", i),
			Status: status,
		}
	}

	if got := manager.occupiedSlotsUnsafe(); got != 0 {
		t.Fatalf("dead containers must not occupy slots, got %d", got)
	}

	// Everything else is a workload the host is actually carrying, including the
	// states on the way up and down — admitting more while one is still starting
	// is how a host is over-committed.
	alive := []models.ContainerStatus{
		models.StatusStarting,
		models.StatusRunning,
		models.StatusHealthy,
		models.StatusUnhealthy,
		models.StatusStopping,
	}
	for i, status := range alive {
		manager.containers[fmt.Sprintf("alive-%d", i)] = &models.Container{
			Name:   fmt.Sprintf("alive-%d", i),
			Status: status,
		}
	}

	if got, want := manager.occupiedSlotsUnsafe(), len(alive); got != want {
		t.Fatalf("expected %d occupied slots, got %d", want, got)
	}
}
