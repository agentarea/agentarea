package container

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"log/slog"
	"os"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/models"
	redis "github.com/go-redis/redis/v8"
)

// TestContainerLifecycleIntegration tests the full container lifecycle with Redis events
func TestContainerLifecycleIntegration(t *testing.T) {
	// Skip if running in CI or if no podman available
	if os.Getenv("CI") != "" || os.Getenv("SKIP_INTEGRATION") != "" {
		t.Skip("Skipping integration test in CI environment")
	}

	cfg := &config.Config{
		Container: config.ContainerConfig{
			NamePrefix:    "test-integration-",
			MaxContainers: 10,
		},
		Redis: config.RedisConfig{
			URL: "redis://localhost:6379",
		},
	}
	logger := slog.New(slog.NewTextHandler(os.Stdout, nil))

	// Create Redis client for monitoring events
	rdb := redis.NewClient(&redis.Options{
		Addr: "localhost:6379",
	})
	defer rdb.Close()

	// Test Redis connection
	_, err := rdb.Ping(context.Background()).Result()
	if err != nil {
		t.Skipf("Redis not available, skipping integration test: %v", err)
	}

	// Subscribe to status change events
	pubsub := rdb.Subscribe(context.Background(), "MCPServerInstanceStatusChanged")
	defer pubsub.Close()

	manager := NewManager(cfg, logger)

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	instanceID := "test-integration-instance"
	name := "test-nginx-integration"
	jsonSpec := map[string]interface{}{
		"image": "nginx:alpine",
		"port":  80,
		"environment": map[string]interface{}{
			"NGINX_PORT": "80",
		},
	}

	// Start container creation in goroutine
	errChan := make(chan error, 1)
	go func() {
		err := manager.HandleMCPInstanceCreated(ctx, instanceID, name, jsonSpec)
		errChan <- err
	}()

	// Monitor events and container creation
	statusUpdates := make([]string, 0)
	eventTimeout := time.After(45 * time.Second)
	creationTimeout := time.After(50 * time.Second)

	for {
		select {
		case msg := <-pubsub.Channel():
			t.Logf("Received event: %s", msg.Payload)

			var eventData map[string]interface{}
			if err := json.Unmarshal([]byte(msg.Payload), &eventData); err != nil {
				t.Logf("Failed to parse event: %v", err)
				continue
			}

			if data, ok := eventData["data"].(map[string]interface{}); ok {
				if eventData, ok := data["data"].(map[string]interface{}); ok {
					if instanceIDFromEvent, ok := eventData["instance_id"].(string); ok && instanceIDFromEvent == instanceID {
						if status, ok := eventData["status"].(string); ok {
							statusUpdates = append(statusUpdates, status)
							t.Logf("Status update for %s: %s", instanceID, status)

							if status == "running" {
								t.Log("Container reached running status - test successful!")

								// Verify container is in manager's tracking
								containerName := manager.config.GetContainerName(name)
								if container, exists := manager.containers[containerName]; exists {
									if container.Status != models.StatusRunning {
										t.Errorf("Container status in manager (%s) doesn't match event (%s)",
											container.Status, status)
									}
								} else {
									t.Error("Container not found in manager's tracking map")
								}

								// Cleanup: stop the container
								if err := manager.HandleMCPInstanceDeleted(ctx, instanceID); err != nil {
									t.Logf("Warning: Failed to cleanup container: %v", err)
								}
								return
							}

							if status == "failed" {
								t.Error("Container failed to start")
								return
							}
						}
					}
				}
			}

		case err := <-errChan:
			if err != nil {
				t.Errorf("Container creation failed: %v", err)
			} else {
				t.Log("Container creation completed without error")
			}

		case <-eventTimeout:
			t.Errorf("Timeout waiting for status events. Received updates: %v", statusUpdates)
			return

		case <-creationTimeout:
			t.Error("Timeout waiting for container creation to complete")
			return

		case <-ctx.Done():
			t.Error("Test context cancelled")
			return
		}
	}
}

// TestEventPublishing tests that the event publisher works correctly
func TestEventPublishing(t *testing.T) {
	if os.Getenv("CI") != "" || os.Getenv("SKIP_INTEGRATION") != "" {
		t.Skip("Skipping integration test in CI environment")
	}

	cfg := &config.Config{
		Redis: config.RedisConfig{
			URL: "redis://localhost:6379",
		},
	}
	logger := slog.New(slog.NewTextHandler(os.Stdout, nil))

	// Create Redis client for monitoring events
	rdb := redis.NewClient(&redis.Options{
		Addr: "localhost:6379",
	})
	defer rdb.Close()

	// Test Redis connection
	_, err := rdb.Ping(context.Background()).Result()
	if err != nil {
		t.Skipf("Redis not available, skipping integration test: %v", err)
	}

	// Subscribe to status change events
	pubsub := rdb.Subscribe(context.Background(), "MCPServerInstanceStatusChanged")
	defer pubsub.Close()

	manager := NewManager(cfg, logger)
	ctx := context.Background()

	instanceID := "test-event-instance"
	name := "test-event-container"

	// Publish a status update
	err = manager.eventPublisher.PublishRunning(ctx, instanceID, name, "test-container-id", "http://localhost:8080")
	if err != nil {
		t.Fatalf("Failed to publish event: %v", err)
	}

	// Wait for event
	select {
	case msg := <-pubsub.Channel():
		t.Logf("Received event: %s", msg.Payload)

		var eventData map[string]interface{}
		if err := json.Unmarshal([]byte(msg.Payload), &eventData); err != nil {
			t.Fatalf("Failed to parse event: %v", err)
		}

		// Verify event structure
		if data, ok := eventData["data"].(map[string]interface{}); ok {
			if eventType, ok := data["event_type"].(string); !ok || eventType != "MCPServerInstanceStatusChanged" {
				t.Errorf("Expected event_type 'MCPServerInstanceStatusChanged', got %v", eventType)
			}

			if eventData, ok := data["data"].(map[string]interface{}); ok {
				if actualInstanceID, ok := eventData["instance_id"].(string); !ok || actualInstanceID != instanceID {
					t.Errorf("Expected instance_id '%s', got %v", instanceID, actualInstanceID)
				}
				if status, ok := eventData["status"].(string); !ok || status != "running" {
					t.Errorf("Expected status 'running', got %v", status)
				}
			} else {
				t.Error("Event data missing nested data field")
			}
		} else {
			t.Error("Event data missing data field")
		}

	case <-time.After(5 * time.Second):
		t.Fatal("Timeout waiting for published event")
	}
}

// TestContainerLifecycleValidationFlow tests the validation and event flow without creating real containers
func TestContainerLifecycleValidationFlow(t *testing.T) {
	if os.Getenv("CI") != "" || os.Getenv("SKIP_INTEGRATION") != "" {
		t.Skip("Skipping integration test in CI environment")
	}

	cfg := &config.Config{
		Container: config.ContainerConfig{
			NamePrefix:    "test-flow-",
			MaxContainers: 10,
		},
		Redis: config.RedisConfig{
			URL: "redis://localhost:6379",
		},
	}
	logger := slog.New(slog.NewTextHandler(os.Stdout, nil))

	// Create Redis client for monitoring events
	rdb := redis.NewClient(&redis.Options{
		Addr: "localhost:6379",
	})
	defer rdb.Close()

	// Test Redis connection
	_, err := rdb.Ping(context.Background()).Result()
	if err != nil {
		t.Skipf("Redis not available, skipping integration test: %v", err)
	}

	// Subscribe to status change events
	pubsub := rdb.Subscribe(context.Background(), "MCPServerInstanceStatusChanged")
	defer pubsub.Close()

	manager := NewManager(cfg, logger)

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	instanceID := "test-flow-instance"
	name := "test-flow-container"

	// Test case 1: Invalid specification should trigger validation failure
	invalidSpec := map[string]interface{}{
		"image": "nonexistent-image-12345",
		"port":  80,
	}

	// Monitor events
	statusUpdates := make([]string, 0)
	eventTimeout := time.After(15 * time.Second)

	// Start validation in goroutine
	errChan := make(chan error, 1)
	go func() {
		err := manager.HandleMCPInstanceCreated(ctx, instanceID, name, invalidSpec)
		errChan <- err
	}()

	// Wait for validation events
	expectedEvents := []string{"validating", "failed"}
	receivedEvents := 0

	for receivedEvents < len(expectedEvents) {
		select {
		case msg := <-pubsub.Channel():
			t.Logf("Received event: %s", msg.Payload)

			var eventData map[string]interface{}
			if err := json.Unmarshal([]byte(msg.Payload), &eventData); err != nil {
				t.Logf("Failed to parse event: %v", err)
				continue
			}

			if data, ok := eventData["data"].(map[string]interface{}); ok {
				if eventData, ok := data["data"].(map[string]interface{}); ok {
					if instanceIDFromEvent, ok := eventData["instance_id"].(string); ok && instanceIDFromEvent == instanceID {
						if status, ok := eventData["status"].(string); ok {
							statusUpdates = append(statusUpdates, status)
							t.Logf("Status update %d for %s: %s", len(statusUpdates), instanceID, status)
							receivedEvents++

							if status == "failed" {
								t.Log("Validation flow completed - container properly failed validation")

								// Verify the expected sequence
								if len(statusUpdates) >= 2 {
									if statusUpdates[0] != "validating" {
										t.Errorf("Expected first status to be 'validating', got '%s'", statusUpdates[0])
									}
									if statusUpdates[1] != "failed" {
										t.Errorf("Expected second status to be 'failed', got '%s'", statusUpdates[1])
									}
								}
								goto testComplete
							}
						}
					}
				}
			}

		case err := <-errChan:
			if err == nil {
				t.Error("Expected validation to fail for invalid image")
			} else {
				t.Logf("Validation properly failed with error: %v", err)
			}

		case <-eventTimeout:
			t.Errorf("Timeout waiting for validation events. Received updates: %v", statusUpdates)
			return

		case <-ctx.Done():
			t.Error("Test context cancelled")
			return
		}
	}

testComplete:
	t.Logf("Test completed successfully. Event sequence: %v", statusUpdates)
}
