package mcpgateway

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/agentarea/mcp-manager/internal/providers"
)

// runtimeBackendStub embeds the Backend interface so only the two lifecycle
// calls the demand runtime uses need bodies; any other call is a nil-pointer
// panic that names the unexpected dependency.
type runtimeBackendStub struct {
	backends.Backend
	mu         sync.Mutex
	statuses   []statusReply
	statusCall int
}

type statusReply struct {
	status string
	err    error
}

func (b *runtimeBackendStub) GetInstanceStatus(context.Context, string) (*backends.InstanceStatus, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	reply := b.statuses[min(b.statusCall, len(b.statuses)-1)]
	b.statusCall++
	if reply.err != nil {
		return nil, reply.err
	}
	return &backends.InstanceStatus{Status: reply.status}, nil
}

func (b *runtimeBackendStub) statusCalls() int {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.statusCall
}

type runtimeProviderStub struct {
	mu      sync.Mutex
	creates int
	deletes int
	err     error
}

func (p *runtimeProviderStub) CreateInstance(context.Context, *models.MCPServerInstance) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.creates++
	return p.err
}

func (p *runtimeProviderStub) DeleteInstance(context.Context, string, string) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.deletes++
	return nil
}

func (p *runtimeProviderStub) counts() (int, int) {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.creates, p.deletes
}

type selectorStub struct{ provider providers.Provider }

func (s selectorStub) GetProvider(*models.MCPServerInstance) (providers.Provider, error) {
	return s.provider, nil
}

func testProviderRuntime(t *testing.T, backend backends.Backend, provider providers.Provider, startup time.Duration) *ProviderRuntime {
	t.Helper()
	runtime, err := NewProviderRuntime(
		selectorStub{provider: provider},
		backend,
		&config.Config{Environment: "docker"},
		startup,
	)
	if err != nil {
		t.Fatal(err)
	}
	return runtime
}

func dockerInstance() *models.MCPServerInstance {
	return &models.MCPServerInstance{
		InstanceID: "8ca9f331-9cc9-4a51-9933-27d7bb73860b",
		Name:       "8ca9f331-9cc9-4a51-9933-27d7bb73860b",
		JSONSpec:   map[string]any{"type": "docker"},
	}
}

// TestOnlyAMissingInstanceTriggersCreation is the typed-error contract: an
// unreadable status is an inspection failure, not evidence that the workload is
// absent. Treating every error as "not found" made an RBAC or API outage
// silently create a second workload for an instance that already had one.
func TestOnlyAMissingInstanceTriggersCreation(t *testing.T) {
	for name, statusErr := range map[string]error{
		"rbac denied": errors.New("instances is forbidden: user cannot list resource"),
		"api timeout": context.DeadlineExceeded,
	} {
		t.Run(name, func(t *testing.T) {
			backend := &runtimeBackendStub{statuses: []statusReply{{err: statusErr}}}
			provider := &runtimeProviderStub{}
			_, err := testProviderRuntime(t, backend, provider, time.Second).
				EnsureReady(context.Background(), dockerInstance())
			if err == nil {
				t.Fatal("an unreadable runtime status was treated as a successful activation")
			}
			creates, deletes := provider.counts()
			if creates != 0 {
				t.Fatalf("creates = %d; an inspection failure was mistaken for a missing workload", creates)
			}
			if deletes != 0 {
				t.Fatalf("deletes = %d; an inspection failure tore down a workload it never observed", deletes)
			}
		})
	}
}

func TestMissingInstanceIsCreatedOnce(t *testing.T) {
	backend := &runtimeBackendStub{statuses: []statusReply{
		{err: backends.ErrInstanceNotFound},
		{status: "running"},
	}}
	provider := &runtimeProviderStub{}
	endpoint, err := testProviderRuntime(t, backend, provider, 2*time.Second).
		EnsureReady(context.Background(), dockerInstance())
	if err != nil {
		t.Fatalf("EnsureReady() error = %v", err)
	}
	if endpoint == "" {
		t.Fatal("EnsureReady() returned no endpoint")
	}
	creates, deletes := provider.counts()
	if creates != 1 || deletes != 0 {
		t.Fatalf("creates=%d deletes=%d, want a single creation and no teardown", creates, deletes)
	}
}

// TestReadyWorkloadIsNeitherRecreatedNorTornDown protects the steady state: a
// healthy workload must survive activation untouched.
func TestReadyWorkloadIsNeitherRecreatedNorTornDown(t *testing.T) {
	backend := &runtimeBackendStub{statuses: []statusReply{{status: "running"}}}
	provider := &runtimeProviderStub{}
	if _, err := testProviderRuntime(t, backend, provider, time.Second).
		EnsureReady(context.Background(), dockerInstance()); err != nil {
		t.Fatalf("EnsureReady() error = %v", err)
	}
	creates, deletes := provider.counts()
	if creates != 0 || deletes != 0 {
		t.Fatalf("creates=%d deletes=%d, want a ready workload left alone", creates, deletes)
	}
	if backend.statusCalls() != 1 {
		t.Fatalf("status calls = %d, want a single check for an already-ready workload", backend.statusCalls())
	}
}

// TestFailedColdStartCleansUpTheWorkload closes the leak: a workload that never
// became ready used to stay behind, and the reaper never selected it because it
// had never reached the ready state.
func TestFailedColdStartCleansUpTheWorkload(t *testing.T) {
	backend := &runtimeBackendStub{statuses: []statusReply{
		{err: backends.ErrInstanceNotFound},
		{status: "pending"},
	}}
	provider := &runtimeProviderStub{}
	_, err := testProviderRuntime(t, backend, provider, 300*time.Millisecond).
		EnsureReady(context.Background(), dockerInstance())
	if err == nil {
		t.Fatal("a workload that never became ready reported a successful activation")
	}
	creates, deletes := provider.counts()
	if creates != 1 || deletes != 1 {
		t.Fatalf("creates=%d deletes=%d, want the failed start torn down", creates, deletes)
	}
}

// TestColdStartAbandonedByTheGatewayCleansUpTheWorkload covers the gateway's own
// deadline expiring. Only the gateway may end a start: the caller's request
// context is deliberately not wired here (see Gateway.ServeHTTP), because a
// client giving up on one request is not a statement that the workload is
// unwanted — it will retry, and the retry wants this workload.
func TestColdStartAbandonedByTheGatewayCleansUpTheWorkload(t *testing.T) {
	backend := &runtimeBackendStub{statuses: []statusReply{
		{err: backends.ErrInstanceNotFound},
		{status: "pending"},
	}}
	provider := &runtimeProviderStub{}
	ctx, cancel := context.WithCancel(context.Background())
	go func() {
		time.Sleep(50 * time.Millisecond)
		cancel()
	}()
	_, err := testProviderRuntime(t, backend, provider, time.Minute).EnsureReady(ctx, dockerInstance())
	if err == nil {
		t.Fatal("an abandoned activation reported success")
	}
	creates, deletes := provider.counts()
	if creates != 1 || deletes != 1 {
		t.Fatalf("creates=%d deletes=%d, want the abandoned start torn down", creates, deletes)
	}
}

// TestStatusErrorDuringStartCleansUpTheWorkload covers the other half of the
// leak: the failure arrives as an unreadable status rather than a timeout.
func TestStatusErrorDuringStartCleansUpTheWorkload(t *testing.T) {
	backend := &runtimeBackendStub{statuses: []statusReply{
		{err: backends.ErrInstanceNotFound},
		{err: errors.New("kubernetes API unavailable")},
	}}
	provider := &runtimeProviderStub{}
	_, err := testProviderRuntime(t, backend, provider, time.Minute).
		EnsureReady(context.Background(), dockerInstance())
	if err == nil {
		t.Fatal("an unreadable status during start reported success")
	}
	creates, deletes := provider.counts()
	if creates != 1 || deletes != 1 {
		t.Fatalf("creates=%d deletes=%d, want the half-started workload torn down", creates, deletes)
	}
}

// TestCleanupToleratesAnAlreadyGoneWorkload keeps the cleanup idempotent, so a
// racing reaper cannot turn a start failure into a second, confusing error.
func TestCleanupToleratesAnAlreadyGoneWorkload(t *testing.T) {
	backend := &runtimeBackendStub{statuses: []statusReply{
		{err: backends.ErrInstanceNotFound},
		{status: "pending"},
	}}
	provider := &vanishingProviderStub{}
	cause := errors.New("did not become ready")
	err := testProviderRuntime(t, backend, provider, 200*time.Millisecond).
		cleanupFailedStart(dockerInstance(), cause)
	if !errors.Is(err, cause) {
		t.Fatalf("cleanupFailedStart() error = %v, want the original cause preserved", err)
	}
}

type vanishingProviderStub struct{ runtimeProviderStub }

func (p *vanishingProviderStub) DeleteInstance(context.Context, string, string) error {
	return backends.ErrInstanceNotFound
}

// TestNonContainerInstancesAreRefusedBeforeAnyWorkload keeps URL-backed MCP
// servers out of the demand path: they have no workload to start.
func TestNonContainerInstancesAreRefusedBeforeAnyWorkload(t *testing.T) {
	backend := &runtimeBackendStub{statuses: []statusReply{{status: "running"}}}
	provider := &runtimeProviderStub{}
	instance := dockerInstance()
	instance.JSONSpec["type"] = "url"
	if _, err := testProviderRuntime(t, backend, provider, time.Second).
		EnsureReady(context.Background(), instance); err == nil {
		t.Fatal("a URL-backed MCP server was admitted to the container demand path")
	}
	if creates, deletes := provider.counts(); creates != 0 || deletes != 0 {
		t.Fatalf("creates=%d deletes=%d, want no workload touched", creates, deletes)
	}
	if backend.statusCalls() != 0 {
		t.Fatal("a URL-backed instance reached the runtime backend")
	}
}

// TestMalformedPortIsRefusedInsteadOfGuessed keeps a bad spec from being proxied
// to whatever happens to be listening on the default port.
func TestMalformedPortIsRefusedInsteadOfGuessed(t *testing.T) {
	for name, port := range map[string]any{
		"non-numeric": "eighty",
		"fractional":  8000.5,
		"zero":        float64(0),
		"negative":    float64(-1),
		"too large":   float64(70000),
	} {
		t.Run(name, func(t *testing.T) {
			backend := &runtimeBackendStub{statuses: []statusReply{{status: "running"}}}
			provider := &runtimeProviderStub{}
			instance := dockerInstance()
			instance.JSONSpec["port"] = port
			if _, err := testProviderRuntime(t, backend, provider, time.Second).
				EnsureReady(context.Background(), instance); err == nil {
				t.Fatalf("port %v was silently replaced with a default", port)
			}
		})
	}
}

func TestAbsentPortUsesTheDocumentedDefault(t *testing.T) {
	backend := &runtimeBackendStub{statuses: []statusReply{{status: "running"}}}
	instance := dockerInstance()
	delete(instance.JSONSpec, "port")
	endpoint, err := testProviderRuntime(t, backend, &runtimeProviderStub{}, time.Second).
		EnsureReady(context.Background(), instance)
	if err != nil {
		t.Fatalf("EnsureReady() error = %v", err)
	}
	if !strings.Contains(endpoint, ":8000") {
		t.Fatalf("endpoint = %q, want the documented 8000 default", endpoint)
	}
}
