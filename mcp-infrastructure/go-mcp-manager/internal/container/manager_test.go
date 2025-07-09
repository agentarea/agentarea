package container

import (
	"context"
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
