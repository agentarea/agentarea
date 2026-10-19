package providers

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"testing"

	"github.com/agentarea/mcp-manager/internal/models"
)

// The hook sees the spec the workload will run with, storage included, and what
// it adds reaches the backend.
func TestBackendProviderHandsTheAssembledSpecToTheHook(t *testing.T) {
	backend := &capturingBackend{}
	provider := NewBackendProvider(backend, nil, storageIssuer(), slog.New(slog.NewTextHandler(io.Discard, nil)))
	var seen *models.MCPServerInstance
	provider.SetInstanceSpecHook(func(_ context.Context, instance *models.MCPServerInstance, spec *BackendInstanceSpec) error {
		seen = instance
		if spec.Environment["MCP_MANAGER_URL"] == "" {
			t.Errorf("the hook ran before storage was assembled: %v", spec.Environment)
		}
		spec.Environment["HTTPS_PROXY"] = "http://proxy:3128"
		if spec.Labels == nil {
			spec.Labels = map[string]string{}
		}
		spec.Labels[models.EgressLabel] = "exit-a"
		return nil
	})

	if err := provider.CreateInstance(context.Background(), optedInInstance()); err != nil {
		t.Fatalf("CreateInstance() error = %v", err)
	}
	if seen == nil || seen.InstanceID != "inst-1" {
		t.Fatalf("hook saw instance %+v", seen)
	}
	if backend.spec.Environment["HTTPS_PROXY"] != "http://proxy:3128" {
		t.Fatalf("hook environment did not reach the backend: %v", backend.spec.Environment)
	}
	if backend.spec.Labels[models.EgressLabel] != "exit-a" {
		t.Fatalf("hook label did not reach the backend: %v", backend.spec.Labels)
	}
	assertStorageEnvironment(t, backend.spec.Environment)
}

func TestBackendProviderDoesNotStartAnInstanceTheHookRefuses(t *testing.T) {
	backend := &capturingBackend{}
	provider := NewBackendProvider(backend, nil, storageIssuer(), slog.New(slog.NewTextHandler(io.Discard, nil)))
	refusal := errors.New("refused")
	provider.SetInstanceSpecHook(func(context.Context, *models.MCPServerInstance, *BackendInstanceSpec) error {
		return refusal
	})

	err := provider.CreateInstance(context.Background(), optedInInstance())
	if !errors.Is(err, refusal) {
		t.Fatalf("CreateInstance() error = %v, want the hook's refusal", err)
	}
	if backend.spec != nil {
		t.Fatal("the workload was created anyway")
	}
}

// A labelled pod leaves the default egress policy, so only the platform may
// label it.
func TestMemberLabelsCannotClaimTheEgressLabel(t *testing.T) {
	spec := newTestBackendProvider().convertToInstanceSpec(&models.MCPServerInstance{
		InstanceID: "inst-1",
		JSONSpec: map[string]any{
			"type":   "docker",
			"image":  "vendor/mcp:1.0",
			"labels": map[string]any{models.EgressLabel: "exit-a", "team": "a"},
		},
	})

	if _, ok := spec.Labels[models.EgressLabel]; ok {
		t.Fatalf("a member set the platform egress label: %v", spec.Labels)
	}
	if spec.Labels["team"] != "a" {
		t.Fatalf("other member labels were dropped: %v", spec.Labels)
	}
}

func TestProviderManagerRefusesAHookItCannotRun(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	hook := func(context.Context, *models.MCPServerInstance, *BackendInstanceSpec) error { return nil }

	urlOnly := NewProviderManager(nil, nil, NewURLProvider(logger))
	if err := urlOnly.SetInstanceSpecHook(hook); err == nil {
		t.Fatal("a URL-only manager accepted an instance-spec hook it would never call")
	}
	if err := urlOnly.SetInstanceSpecHook(nil); err != nil {
		t.Fatalf("clearing the hook failed: %v", err)
	}
}

// Docker is local development, but an instance the hook refuses must not start
// there either.
func TestDockerProviderHandsTheAssembledEnvironmentToTheHook(t *testing.T) {
	manager := &capturingContainerManager{}
	provider := NewDockerProvider(nil, manager, storageIssuer(), slog.New(slog.NewTextHandler(io.Discard, nil)))
	provider.SetInstanceSpecHook(func(_ context.Context, instance *models.MCPServerInstance, spec *BackendInstanceSpec) error {
		if instance.InstanceID != "inst-1" || spec.WorkspaceID != "ws-1" {
			t.Errorf("hook saw instance %q workspace %q", instance.InstanceID, spec.WorkspaceID)
		}
		if spec.Environment["MCP_MANAGER_URL"] == "" {
			t.Errorf("the hook ran before storage was assembled: %v", spec.Environment)
		}
		spec.Environment["HTTPS_PROXY"] = "http://proxy:3128"
		spec.Environment["APP_MODE"] = "overridden"
		return nil
	})

	if err := provider.CreateInstance(context.Background(), optedInInstance()); err != nil {
		t.Fatalf("CreateInstance() error = %v", err)
	}
	environment := manager.spec["environment"].(map[string]any)
	if environment["HTTPS_PROXY"] != "http://proxy:3128" || environment["APP_MODE"] != "overridden" {
		t.Fatalf("hook environment did not reach the container: %v", environment)
	}
	if environment["MCP_MANAGER_URL"] != "http://mcp-manager:80" {
		t.Fatalf("storage environment was lost: %v", environment)
	}
}

func TestDockerProviderDoesNotStartAnInstanceTheHookRefuses(t *testing.T) {
	manager := &capturingContainerManager{}
	provider := NewDockerProvider(nil, manager, storageIssuer(), slog.New(slog.NewTextHandler(io.Discard, nil)))
	refusal := errors.New("refused")
	provider.SetInstanceSpecHook(func(context.Context, *models.MCPServerInstance, *BackendInstanceSpec) error {
		return refusal
	})

	if err := provider.CreateInstance(context.Background(), optedInInstance()); !errors.Is(err, refusal) {
		t.Fatalf("CreateInstance() error = %v, want the hook's refusal", err)
	}
	if manager.spec != nil {
		t.Fatal("the container was created anyway")
	}
}

func TestProviderManagerInstallsTheHookOnItsDockerProvider(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	manager := &capturingContainerManager{}
	providers := NewProviderManager(NewDockerProvider(nil, manager, nil, logger), nil, NewURLProvider(logger))
	refusal := errors.New("refused")
	if err := providers.SetInstanceSpecHook(func(context.Context, *models.MCPServerInstance, *BackendInstanceSpec) error {
		return refusal
	}); err != nil {
		t.Fatalf("SetInstanceSpecHook() error = %v", err)
	}

	instance := &models.MCPServerInstance{InstanceID: "inst-1", JSONSpec: map[string]any{"type": "docker", "image": "vendor/mcp:1.0"}}
	provider, err := providers.GetProvider(instance)
	if err != nil {
		t.Fatalf("GetProvider() error = %v", err)
	}
	if err := provider.CreateInstance(context.Background(), instance); !errors.Is(err, refusal) {
		t.Fatalf("CreateInstance() error = %v, want the hook's refusal", err)
	}
	if manager.spec != nil {
		t.Fatal("the container was created anyway")
	}
}

func TestProviderManagerInstallsTheHookOnItsBackendProvider(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	backend := &capturingBackend{}
	manager := NewProviderManager(nil, NewBackendProvider(backend, nil, nil, logger), NewURLProvider(logger))
	refusal := errors.New("refused")
	if err := manager.SetInstanceSpecHook(func(context.Context, *models.MCPServerInstance, *BackendInstanceSpec) error {
		return refusal
	}); err != nil {
		t.Fatalf("SetInstanceSpecHook() error = %v", err)
	}

	instance := &models.MCPServerInstance{InstanceID: "inst-1", JSONSpec: map[string]any{"type": "docker", "image": "vendor/mcp:1.0"}}
	provider, err := manager.GetProvider(instance)
	if err != nil {
		t.Fatalf("GetProvider() error = %v", err)
	}
	if err := provider.CreateInstance(context.Background(), instance); !errors.Is(err, refusal) {
		t.Fatalf("CreateInstance() error = %v, want the hook's refusal", err)
	}
	if backend.spec != nil {
		t.Fatal("the workload was created anyway")
	}
}
