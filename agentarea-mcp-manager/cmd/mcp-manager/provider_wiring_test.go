package main

import (
	"context"
	"io"
	"log/slog"
	"testing"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/models"
)

type wiringBackendStub struct{}

func (wiringBackendStub) Initialize(context.Context) error { return nil }
func (wiringBackendStub) CreateInstance(context.Context, *backends.InstanceSpec) (*backends.InstanceResult, error) {
	return &backends.InstanceResult{}, nil
}
func (wiringBackendStub) DeleteInstance(context.Context, string) error { return nil }
func (wiringBackendStub) GetInstanceStatus(context.Context, string) (*backends.InstanceStatus, error) {
	return nil, backends.ErrInstanceNotFound
}
func (wiringBackendStub) ListInstances(context.Context) ([]*backends.InstanceStatus, error) {
	return nil, nil
}
func (wiringBackendStub) UpdateInstance(context.Context, string, *backends.InstanceSpec) error {
	return nil
}
func (wiringBackendStub) PerformHealthCheck(context.Context, string) (*backends.HealthCheckResult, error) {
	return &backends.HealthCheckResult{}, nil
}
func (wiringBackendStub) Cleanup(context.Context) error { return nil }

// A data-plane deployment used to fall through to the URL-only manager, so every
// container-backed instance failed with "no container provider available
// (docker, backend)" -- a 502 on the first MCP request and on retirement.
func TestDataPlaneDeploymentResolvesAContainerProvider(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	for _, envType := range []string{"dataplane", "kubernetes"} {
		t.Run(envType, func(t *testing.T) {
			manager := initProviderManager(envType, wiringBackendStub{}, nil, nil, logger)
			for _, instanceType := range []string{"docker", "command"} {
				instance := &models.MCPServerInstance{
					InstanceID: "abc-123",
					JSONSpec:   map[string]any{"type": instanceType},
				}
				provider, err := manager.GetProvider(instance)
				if err != nil {
					t.Fatalf("GetProvider(%s) error = %v, want a backend-backed provider", instanceType, err)
				}
				if provider == nil {
					t.Fatalf("GetProvider(%s) = nil", instanceType)
				}
			}
		})
	}
}

// URL-type instances stay on the URL provider: they are reached directly and
// never occupy the data plane.
func TestDataPlaneDeploymentKeepsURLInstancesOnTheURLProvider(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	manager := initProviderManager("dataplane", wiringBackendStub{}, nil, nil, logger)
	provider, err := manager.GetProvider(&models.MCPServerInstance{
		InstanceID: "abc-123",
		JSONSpec:   map[string]any{"type": "url", "endpoint_url": "https://mcp.example.com"},
	})
	if err != nil {
		t.Fatalf("GetProvider(url) error = %v", err)
	}
	if provider == nil {
		t.Fatal("GetProvider(url) = nil")
	}
}

func (wiringBackendStub) Shutdown(context.Context) error { return nil }
