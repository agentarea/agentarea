package providers

import (
	"context"
	"io"
	"log/slog"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/activationauth"
	"github.com/agentarea/mcp-manager/internal/mcpstorage"
	"github.com/agentarea/mcp-manager/internal/models"
)

type capturingContainerManager struct{ spec map[string]any }

func (c *capturingContainerManager) HandleMCPInstanceCreated(_ context.Context, _, _, _ string, jsonSpec map[string]any) error {
	c.spec = jsonSpec
	return nil
}

func (c *capturingContainerManager) HandleMCPInstanceDeleted(context.Context, string) error {
	return nil
}

type capturingBackend struct{ spec *BackendInstanceSpec }

func (c *capturingBackend) CreateInstance(_ context.Context, spec *BackendInstanceSpec) (*BackendInstanceResult, error) {
	c.spec = spec
	return &BackendInstanceResult{}, nil
}

func (c *capturingBackend) DeleteInstance(context.Context, string) error { return nil }

var storageSecret = []byte("0123456789abcdef0123456789abcdef")

func storageIssuer() *mcpstorage.Issuer {
	return mcpstorage.NewIssuer(storageSecret, "http://mcp-manager:80")
}

func optedInInstance() *models.MCPServerInstance {
	return &models.MCPServerInstance{
		InstanceID: "inst-1", WorkspaceID: "ws-1",
		JSONSpec: map[string]any{
			"type":        "docker",
			"image":       "ghcr.io/acme/app:1",
			"port":        8080.0,
			"storage":     map[string]any{"enabled": true},
			"environment": map[string]any{"APP_MODE": "prod", "MCP_STORAGE_TOKEN": "spoofed"},
		},
	}
}

func assertStorageEnvironment(t *testing.T, environment map[string]string) {
	t.Helper()
	if environment["MCP_MANAGER_URL"] != "http://mcp-manager:80" {
		t.Fatalf("MCP_MANAGER_URL = %q", environment["MCP_MANAGER_URL"])
	}
	granted := activationauth.Identity{WorkspaceID: "ws-1", InstanceID: "inst-1"}
	if err := activationauth.Verify(environment["MCP_STORAGE_TOKEN"], storageSecret, activationauth.ScopeStorage, granted, activationauth.BodySHA256(nil), time.Now()); err != nil {
		t.Fatalf("token does not grant its instance: %v", err)
	}
	if environment["APP_MODE"] != "prod" {
		t.Fatalf("the spec's own environment was dropped: %v", environment)
	}
}

func TestDockerProviderInjectsStorageIntoAnOptedInContainer(t *testing.T) {
	manager := &capturingContainerManager{}
	provider := NewDockerProvider(nil, manager, storageIssuer(), slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err := provider.CreateInstance(context.Background(), optedInInstance()); err != nil {
		t.Fatalf("CreateInstance() error = %v", err)
	}
	environment := map[string]string{}
	for key, value := range manager.spec["environment"].(map[string]any) {
		environment[key] = value.(string)
	}
	assertStorageEnvironment(t, environment)
}

func TestBackendProviderInjectsStorageIntoAnOptedInWorkload(t *testing.T) {
	backend := &capturingBackend{}
	provider := NewBackendProvider(backend, nil, storageIssuer(), slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err := provider.CreateInstance(context.Background(), optedInInstance()); err != nil {
		t.Fatalf("CreateInstance() error = %v", err)
	}
	assertStorageEnvironment(t, backend.spec.Environment)
}

func TestProvidersLeaveOtherInstancesWithoutStorage(t *testing.T) {
	instance := optedInInstance()
	delete(instance.JSONSpec, "storage")
	backend := &capturingBackend{}
	provider := NewBackendProvider(backend, nil, storageIssuer(), slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err := provider.CreateInstance(context.Background(), instance); err != nil {
		t.Fatalf("CreateInstance() error = %v", err)
	}
	if _, ok := backend.spec.Environment["MCP_MANAGER_URL"]; ok {
		t.Fatalf("an instance that did not opt in got %v", backend.spec.Environment)
	}
}

func TestProvidersRefuseToStartAnOptedInInstanceWithoutStorage(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	manager := &capturingContainerManager{}
	if err := NewDockerProvider(nil, manager, nil, logger).CreateInstance(context.Background(), optedInInstance()); err == nil || !strings.Contains(err.Error(), "storage") {
		t.Fatalf("docker CreateInstance() error = %v", err)
	}
	if manager.spec != nil {
		t.Fatal("the container was created anyway")
	}
	backend := &capturingBackend{}
	if err := NewBackendProvider(backend, nil, nil, logger).CreateInstance(context.Background(), optedInInstance()); err == nil {
		t.Fatal("backend CreateInstance() accepted it")
	}
	if backend.spec != nil {
		t.Fatal("the workload was created anyway")
	}
}
