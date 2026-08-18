package connectorcomposition

import (
	"context"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/connectorproto"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime"
)

type fakeKubernetesAdapter struct {
	backends.Backend
	sandboxruntime.ManagedRuntime
}

type fakeDockerAdapter struct {
	backends.Backend
	initialized bool
}

func (d *fakeDockerAdapter) InitializeMCPHost(context.Context) error {
	d.initialized = true
	return nil
}

func (d *fakeDockerAdapter) Shutdown(context.Context) error { return nil }

func TestDispatcherFailsClosedForMissingAdapter(t *testing.T) {
	dispatcher := (&Runtime{}).Dispatcher()
	result, err := dispatcher.DispatchOperation(context.Background(), &connectorproto.OperationStart{
		OperationId:    &connectorproto.OperationID{Value: "operation-a"},
		Kind:           connectorproto.OperationKind_OPERATION_KIND_MCP_LIST,
		RequestPayload: []byte(`{}`),
		ContentType:    "application/json",
	})
	if err != nil {
		t.Fatal(err)
	}
	if result.GetStatus() != connectorproto.OperationResultStatus_OPERATION_RESULT_STATUS_FAILED || result.GetError().GetCode() != connectorproto.ErrorCode_ERROR_CODE_UNAVAILABLE {
		t.Fatalf("unexpected fail-closed result: %#v", result)
	}
}

func TestDecodeJSONRejectsTrailingPayload(t *testing.T) {
	var value struct{}
	if err := decodeJSON([]byte(`{} {}`), &value); err == nil {
		t.Fatal("accepted trailing JSON payload")
	}
}

func testCompositionConfig() Config {
	return Config{
		DataPlaneID:         "plane-a",
		MCPProvider:         ProviderDisabled,
		SandboxProvider:     ProviderDisabled,
		KubernetesNamespace: "execution",
		SandboxTaskLeaseTTL: time.Minute,
	}
}

func TestDisabledProvidersExposeNoCapabilities(t *testing.T) {
	runtime, err := New(context.Background(), testCompositionConfig(), Dependencies{})
	if err != nil {
		t.Fatal(err)
	}
	mcp, sandbox := runtime.Capabilities()
	if mcp || sandbox || runtime.MCP() != nil || runtime.Sandbox() != nil {
		t.Fatalf("disabled composition exposed adapters: mcp=%v sandbox=%v", mcp, sandbox)
	}
}

func TestKubernetesAdaptersAreTheOnlyAdvertisedCapabilities(t *testing.T) {
	cfg := testCompositionConfig()
	cfg.MCPProvider = ProviderKubernetes
	cfg.SandboxProvider = ProviderKubernetes
	called := 0
	runtime, err := New(context.Background(), cfg, Dependencies{NewKubernetesAdapter: func(got Config) (KubernetesAdapter, error) {
		called++
		if got.KubernetesNamespace != "execution" {
			t.Fatalf("namespace = %q", got.KubernetesNamespace)
		}
		return fakeKubernetesAdapter{}, nil
	}})
	if err != nil {
		t.Fatal(err)
	}
	mcp, sandbox := runtime.Capabilities()
	if called != 1 || !mcp || !sandbox || runtime.MCP() == nil || runtime.Sandbox() == nil {
		t.Fatalf("unexpected initialized adapters: called=%d mcp=%v sandbox=%v", called, mcp, sandbox)
	}
}

func TestDockerMCPInitializesBeforeAdvertisingMCP(t *testing.T) {
	cfg := testCompositionConfig()
	cfg.MCPProvider = ProviderDocker
	cfg.DockerRuntime, cfg.DockerNetwork, cfg.DockerNamePrefix, cfg.DockerMaxContainers = "docker", "bridge", "agentarea-mcp-", 2
	adapter := &fakeDockerAdapter{}
	runtime, err := New(context.Background(), cfg, Dependencies{NewDockerMCPAdapter: func(Config) (DockerMCPAdapter, error) { return adapter, nil }})
	if err != nil {
		t.Fatal(err)
	}
	mcp, sandbox := runtime.Capabilities()
	if !adapter.initialized || !mcp || sandbox {
		t.Fatalf("docker capabilities: initialized=%v mcp=%v sandbox=%v", adapter.initialized, mcp, sandbox)
	}
}

func TestDockerMCPAndExternalSandboxAdvertiseBothCapabilities(t *testing.T) {
	cfg := testCompositionConfig()
	cfg.MCPProvider = ProviderDocker
	cfg.SandboxProvider = "opensandbox"
	cfg.SandboxStateRedisURL = "redis://127.0.0.1:6379/0"
	cfg.DockerRuntime, cfg.DockerNetwork, cfg.DockerNamePrefix, cfg.DockerMaxContainers = "docker", "bridge", "agentarea-mcp-", 2
	docker := &fakeDockerAdapter{}
	closed := false
	runtime, err := New(context.Background(), cfg, Dependencies{
		NewDockerMCPAdapter: func(Config) (DockerMCPAdapter, error) { return docker, nil },
		NewExternalSandbox: func(context.Context, Config) (sandboxruntime.ManagedRuntime, func() error, error) {
			return fakeKubernetesAdapter{}, func() error { closed = true; return nil }, nil
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	mcp, sandbox := runtime.Capabilities()
	if !docker.initialized || !mcp || !sandbox {
		t.Fatalf("mixed capabilities: initialized=%v mcp=%v sandbox=%v", docker.initialized, mcp, sandbox)
	}
	if err := runtime.Close(context.Background()); err != nil {
		t.Fatal(err)
	}
	if !closed {
		t.Fatal("external sandbox state was not closed")
	}
}

func TestRemoteDataPlaneMCPInitializesBeforeAdvertising(t *testing.T) {
	cfg := testCompositionConfig()
	cfg.MCPProvider = ProviderDataPlane
	adapter := &backendStub{}
	runtime, err := New(context.Background(), cfg, Dependencies{
		NewDataPlaneMCP: func(Config) (backends.Backend, error) { return adapter, nil },
	})
	if err != nil {
		t.Fatal(err)
	}
	mcp, sandbox := runtime.Capabilities()
	if !adapter.initialized || !mcp || sandbox {
		t.Fatalf("remote data plane capabilities: initialized=%v mcp=%v sandbox=%v", adapter.initialized, mcp, sandbox)
	}
}

func TestLegacyDataPlaneOwnershipIsTranslatedAfterRemoteEnforcement(t *testing.T) {
	backend := &statusBackendStub{status: &backends.InstanceStatus{
		ID: "instance-a", Labels: map[string]string{"agentarea.io/dataplane-id": "10.42.0.10"},
	}}
	adapter := &legacyDataPlaneAdapter{Backend: backend, dataPlaneID: "logical-plane-a"}
	status, err := adapter.GetInstanceStatus(context.Background(), "instance-a")
	if err != nil {
		t.Fatal(err)
	}
	if status.Labels["agentarea.io/dataplane-id"] != "logical-plane-a" {
		t.Fatalf("translated labels = %#v", status.Labels)
	}
	if backend.status.Labels["agentarea.io/dataplane-id"] != "10.42.0.10" {
		t.Fatal("translation mutated the remote ownership proof")
	}
}

type backendStub struct {
	backends.Backend
	initialized bool
}

func (b *backendStub) Initialize(context.Context) error { b.initialized = true; return nil }
func (b *backendStub) Shutdown(context.Context) error   { return nil }

type statusBackendStub struct {
	backends.Backend
	status *backends.InstanceStatus
}

func (b *statusBackendStub) GetInstanceStatus(context.Context, string) (*backends.InstanceStatus, error) {
	return b.status, nil
}
