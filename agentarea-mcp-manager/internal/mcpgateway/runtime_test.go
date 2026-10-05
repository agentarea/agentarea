package mcpgateway

import (
	"context"
	"errors"
	"net"
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
	status      string
	internalURL string
	err         error
}

func (b *runtimeBackendStub) GetInstanceStatus(context.Context, string) (*backends.InstanceStatus, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	reply := b.statuses[min(b.statusCall, len(b.statuses)-1)]
	b.statusCall++
	if reply.err != nil {
		return nil, reply.err
	}
	return &backends.InstanceStatus{Status: reply.status, InternalURL: reply.internalURL}, nil
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
		nil,
	)
	if err != nil {
		t.Fatal(err)
	}
	return runtime
}

func TestStartFailureBackoffGrowsExponentiallyToCap(t *testing.T) {
	tests := []struct {
		failures int
		want     time.Duration
	}{
		{failures: 0, want: 0},
		{failures: 1, want: time.Second},
		{failures: 2, want: 2 * time.Second},
		{failures: 3, want: 4 * time.Second},
		{failures: 10, want: startFailureBackoffCap},
	}
	for _, test := range tests {
		if got := startFailureBackoff(test.failures); got != test.want {
			t.Errorf("startFailureBackoff(%d) = %s, want %s", test.failures, got, test.want)
		}
	}
}

func TestStartFailureBackoffPreventsRepeatedCreation(t *testing.T) {
	backend := &runtimeBackendStub{statuses: []statusReply{{err: backends.ErrInstanceNotFound}}}
	provider := &runtimeProviderStub{err: errors.New("failed")}
	runtime := testProviderRuntime(t, backend, provider, time.Second)
	instance := dockerInstance()

	if _, err := runtime.EnsureReady(context.Background(), instance); err == nil {
		t.Fatal("first EnsureReady() error = nil, want the simulated start failure")
	}
	_, err := runtime.EnsureReady(context.Background(), instance)
	var blocked *StartBackoffError
	if !errors.As(err, &blocked) {
		t.Fatalf("second EnsureReady() error = %v, want a start-backoff failure", err)
	}
	if creates, _ := provider.counts(); creates != 1 {
		t.Fatalf("provider creates = %d during backoff, want one", creates)
	}
	if calls := backend.statusCalls(); calls != 1 {
		t.Fatalf("runtime status calls = %d during backoff, want one", calls)
	}
}

func dockerInstance() *models.MCPServerInstance {
	return &models.MCPServerInstance{
		InstanceID: "8ca9f331-9cc9-4a51-9933-27d7bb73860b",
		Name:       "8ca9f331-9cc9-4a51-9933-27d7bb73860b",
		JSONSpec: map[string]any{
			"type":  "docker",
			"image": "ghcr.io/agentarea/mcp:1.2.3",
		},
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

// TestColdStartWaitsForTheWorkloadToListen reproduces the first-request 502:
// Docker reports a container running while its server is still starting (an
// mcp-base container installs its package and initializes its stdio server
// before it binds), so proxying at "running" dialed a closed port.
func TestColdStartWaitsForTheWorkloadToListen(t *testing.T) {
	reserved, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	address := reserved.Addr().String()
	reserved.Close()
	backend := &runtimeBackendStub{statuses: []statusReply{
		{err: backends.ErrInstanceNotFound},
		{status: "running", internalURL: "http://" + address},
	}}
	const bindAfter = 400 * time.Millisecond
	go func() {
		time.Sleep(bindAfter)
		server, err := net.Listen("tcp", address)
		if err != nil {
			return
		}
		t.Cleanup(func() { server.Close() })
	}()

	started := time.Now()
	if _, err := testProviderRuntime(t, backend, &runtimeProviderStub{}, 5*time.Second).
		EnsureReady(context.Background(), dockerInstance()); err != nil {
		t.Fatalf("EnsureReady() error = %v", err)
	}
	if waited := time.Since(started); waited < bindAfter {
		t.Fatalf("EnsureReady returned after %v, before the workload listened", waited)
	}
}

func TestWorkloadThatNeverListensIsTornDown(t *testing.T) {
	reserved, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	address := reserved.Addr().String()
	reserved.Close()
	backend := &runtimeBackendStub{statuses: []statusReply{
		{err: backends.ErrInstanceNotFound},
		{status: "running", internalURL: "http://" + address},
	}}
	provider := &runtimeProviderStub{}
	_, err = testProviderRuntime(t, backend, provider, 500*time.Millisecond).
		EnsureReady(context.Background(), dockerInstance())
	if err == nil {
		t.Fatal("a workload that never listened reported a successful activation")
	}
	if creates, deletes := provider.counts(); creates != 1 || deletes != 1 {
		t.Fatalf("creates=%d deletes=%d, want the silent workload torn down", creates, deletes)
	}
}

// mcp-base exits when its stdio server dies, and the container it ran in stays
// behind as exited. Waiting on it held every request for the whole startup
// timeout before the workload was replaced; it is replaced straight away.
func TestStoppedWorkloadIsReplacedNotWaitedOn(t *testing.T) {
	backend := &runtimeBackendStub{statuses: []statusReply{
		{status: "stopped"},
		{status: "running"},
	}}
	provider := &runtimeProviderStub{}
	started := time.Now()
	if _, err := testProviderRuntime(t, backend, provider, 5*time.Second).
		EnsureReady(context.Background(), dockerInstance()); err != nil {
		t.Fatalf("EnsureReady() error = %v", err)
	}
	if creates, deletes := provider.counts(); creates != 1 || deletes != 1 {
		t.Fatalf("creates=%d deletes=%d, want the stopped workload replaced once", creates, deletes)
	}
	if waited := time.Since(started); waited > time.Second {
		t.Fatalf("EnsureReady took %v; a stopped workload was waited on", waited)
	}
}

// A package that fails to install or initialize makes mcp-base exit. That
// start has failed, whether the workload stops before or after it reported
// running, and the caller learns it then — not when the startup timeout ends.
func TestWorkloadThatStopsWhileStartingFailsFast(t *testing.T) {
	reserved, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	address := reserved.Addr().String()
	reserved.Close()
	for name, statuses := range map[string][]statusReply{
		"before running": {{err: backends.ErrInstanceNotFound}, {status: "stopped"}},
		"while installing": {
			{err: backends.ErrInstanceNotFound},
			{status: "running", internalURL: "http://" + address},
			{status: "stopped"},
		},
	} {
		t.Run(name, func(t *testing.T) {
			backend := &runtimeBackendStub{statuses: statuses}
			provider := &runtimeProviderStub{}
			started := time.Now()
			_, err := testProviderRuntime(t, backend, provider, 30*time.Second).
				EnsureReady(context.Background(), dockerInstance())
			if err == nil || !strings.Contains(err.Error(), "stopped") {
				t.Fatalf("EnsureReady() error = %v, want the stopped workload reported", err)
			}
			if waited := time.Since(started); waited > 5*time.Second {
				t.Fatalf("EnsureReady took %v; a stopped start was waited out", waited)
			}
			if creates, deletes := provider.counts(); creates != 1 || deletes != 1 {
				t.Fatalf("creates=%d deletes=%d, want the failed start cleaned up", creates, deletes)
			}
		})
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

// The gateway gives a cold start exactly StartupTimeout, and the runtime uses
// the same value for its readiness deadline, so in production the context
// almost always expires first. That branch used to return a bare
// "context deadline exceeded" and throw away the one fact worth having: what
// the workload was doing when time ran out. An operator reading the log then
// cannot tell a workload still pulling its image from one that came up and
// died, and has to go to the host to find out.
func TestAbandonedColdStartReportsTheStateTheWorkloadWasLeftIn(t *testing.T) {
	backend := &runtimeBackendStub{statuses: []statusReply{
		{err: backends.ErrInstanceNotFound},
		{status: "pending"},
	}}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Millisecond)
	defer cancel()

	_, err := testProviderRuntime(t, backend, &runtimeProviderStub{}, time.Minute).
		EnsureReady(ctx, dockerInstance())

	if err == nil {
		t.Fatal("an abandoned activation reported success")
	}
	if !strings.Contains(err.Error(), "pending") {
		t.Errorf("error = %q, want it to name the last state the workload reached", err.Error())
	}
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Errorf("error = %q, want it to still identify itself as the deadline expiring", err.Error())
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
