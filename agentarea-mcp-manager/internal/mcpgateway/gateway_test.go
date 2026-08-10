package mcpgateway

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/models"
)

const testGatewaySecret = "0123456789abcdef0123456789abcdef"

type gatewayRepositoryStub struct {
	mu            sync.Mutex
	instance      *models.MCPServerInstance
	starting      int
	failed        int
	started       int
	finished      int
	idle          []string
	reapCallbacks int
	retireErr     error
	retired       int
}

func (r *gatewayRepositoryStub) WithInstanceLock(ctx context.Context, _ string, fn func(context.Context) error) error {
	return fn(ctx)
}
func (r *gatewayRepositoryStub) LoadInstance(context.Context, string) (*models.MCPServerInstance, error) {
	return r.instance, nil
}
func (r *gatewayRepositoryStub) MarkStarting(context.Context, string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.starting++
	return nil
}
func (r *gatewayRepositoryStub) MarkFailed(context.Context, string, error) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.failed++
	return nil
}
func (r *gatewayRepositoryStub) MarkReadyAndBeginRequest(context.Context, string, string, time.Duration) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.started++
	return nil
}
func (r *gatewayRepositoryStub) HeartbeatRequest(context.Context, string, time.Duration) error {
	return nil
}
func (r *gatewayRepositoryStub) FinishRequest(context.Context, string, string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.finished++
	return nil
}
func (r *gatewayRepositoryStub) IdleCandidates(context.Context, time.Duration) ([]string, error) {
	return r.idle, nil
}
func (r *gatewayRepositoryStub) ReapIfIdle(ctx context.Context, _ string, _ time.Duration, remove func(context.Context, *models.MCPServerInstance) error) (bool, error) {
	r.reapCallbacks++
	return true, remove(ctx, r.instance)
}
func (r *gatewayRepositoryStub) RetireForDeletion(ctx context.Context, _ string, remove func(context.Context, *models.MCPServerInstance) error) error {
	if r.retireErr != nil {
		return r.retireErr
	}
	r.retired++
	return remove(ctx, r.instance)
}

type runtimeStub struct {
	endpoint string
	err      error
	ensured  int
	deleted  int
}

func (r *runtimeStub) EnsureReady(context.Context, *models.MCPServerInstance) (string, error) {
	r.ensured++
	return r.endpoint, r.err
}
func (r *runtimeStub) Delete(context.Context, *models.MCPServerInstance) error {
	r.deleted++
	return nil
}

func testGateway(t *testing.T, repository *gatewayRepositoryStub, runtime InstanceRuntime) *Gateway {
	t.Helper()
	gateway, err := New(repository, runtime, Policy{
		RequestLeaseTTL: 3 * time.Second,
		StartupTimeout:  time.Second,
		IdleTimeout:     time.Minute,
		SweepInterval:   time.Second,
		AuthSecret:      testGatewaySecret,
	}, slog.New(slog.NewTextHandler(io.Discard, nil)), nil)
	if err != nil {
		t.Fatal(err)
	}
	return gateway
}

func TestGatewayAuthenticatesStartsAndObservesWholeRequest(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/mcp" {
			t.Errorf("upstream path = %q", request.URL.Path)
		}
		if request.Header.Get("X-AgentArea-Manager-Authorization") != "" {
			t.Error("manager credential reached the untrusted upstream")
		}
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte("proxied"))
	}))
	defer upstream.Close()

	instanceID := "8ca9f331-9cc9-4a51-9933-27d7bb73860b"
	repository := &gatewayRepositoryStub{instance: &models.MCPServerInstance{
		InstanceID: instanceID,
		JSONSpec:   map[string]any{"type": "docker"},
	}}
	runtime := &runtimeStub{endpoint: upstream.URL + "/mcp"}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/mcp/"+instanceID+"/mcp", strings.NewReader("{}"))
	request.Header.Set("X-AgentArea-Manager-Authorization", "Bearer "+testGatewaySecret)

	testGateway(t, repository, runtime).ServeHTTP(recorder, request)

	if recorder.Code != http.StatusCreated || recorder.Body.String() != "proxied" {
		t.Fatalf("response = %d %q", recorder.Code, recorder.Body.String())
	}
	if runtime.ensured != 1 || repository.starting != 1 || repository.started != 1 || repository.finished != 1 {
		t.Fatalf("lifecycle calls: ensured=%d starting=%d started=%d finished=%d", runtime.ensured, repository.starting, repository.started, repository.finished)
	}
}

func TestGatewayRejectsMissingCredentialBeforeLifecycle(t *testing.T) {
	repository := &gatewayRepositoryStub{}
	runtime := &runtimeStub{}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/mcp/8ca9f331-9cc9-4a51-9933-27d7bb73860b/mcp", nil)

	testGateway(t, repository, runtime).ServeHTTP(recorder, request)

	if recorder.Code != http.StatusUnauthorized || runtime.ensured != 0 || repository.starting != 0 {
		t.Fatalf("unauthorized request reached lifecycle: status=%d ensured=%d", recorder.Code, runtime.ensured)
	}
}

func TestGatewayRecordsFailedColdStart(t *testing.T) {
	instanceID := "8ca9f331-9cc9-4a51-9933-27d7bb73860b"
	repository := &gatewayRepositoryStub{instance: &models.MCPServerInstance{InstanceID: instanceID}}
	runtime := &runtimeStub{err: errors.New("image rejected")}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/mcp/"+instanceID+"/mcp", nil)
	request.Header.Set("X-AgentArea-Manager-Authorization", "Bearer "+testGatewaySecret)

	testGateway(t, repository, runtime).ServeHTTP(recorder, request)

	if recorder.Code != http.StatusBadGateway || repository.failed != 1 || repository.started != 0 {
		t.Fatalf("failed start response=%d failed=%d started=%d", recorder.Code, repository.failed, repository.started)
	}
}

func TestGatewayReaperDelegatesOnlyEligibleInstances(t *testing.T) {
	repository := &gatewayRepositoryStub{
		instance: &models.MCPServerInstance{InstanceID: "8ca9f331-9cc9-4a51-9933-27d7bb73860b"},
		idle:     []string{"8ca9f331-9cc9-4a51-9933-27d7bb73860b"},
	}
	runtime := &runtimeStub{}

	reaped, err := testGateway(t, repository, runtime).Reap(context.Background())
	if err != nil || reaped != 1 || repository.reapCallbacks != 1 || runtime.deleted != 1 {
		t.Fatalf("reap result=%d err=%v callbacks=%d deleted=%d", reaped, err, repository.reapCallbacks, runtime.deleted)
	}
}

func TestGatewayRetiresSynchronouslyAndAuthenticates(t *testing.T) {
	instanceID := "8ca9f331-9cc9-4a51-9933-27d7bb73860b"
	repository := &gatewayRepositoryStub{instance: &models.MCPServerInstance{InstanceID: instanceID}}
	runtime := &runtimeStub{}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodDelete, "/mcp/"+instanceID, nil)
	request.Header.Set("X-AgentArea-Manager-Authorization", "Bearer "+testGatewaySecret)

	testGateway(t, repository, runtime).RetireHTTP(recorder, request)

	if recorder.Code != http.StatusNoContent || repository.retired != 1 || runtime.deleted != 1 {
		t.Fatalf("retire response=%d retired=%d deleted=%d", recorder.Code, repository.retired, runtime.deleted)
	}
}

func TestGatewayRefusesRetirementWithActiveLease(t *testing.T) {
	instanceID := "8ca9f331-9cc9-4a51-9933-27d7bb73860b"
	repository := &gatewayRepositoryStub{retireErr: ErrInstanceBusy}
	runtime := &runtimeStub{}
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodDelete, "/mcp/"+instanceID, nil)
	request.Header.Set("X-AgentArea-Manager-Authorization", "Bearer "+testGatewaySecret)

	testGateway(t, repository, runtime).RetireHTTP(recorder, request)

	if recorder.Code != http.StatusConflict || runtime.deleted != 0 {
		t.Fatalf("busy retire response=%d deleted=%d", recorder.Code, runtime.deleted)
	}
}

func TestLoadPolicyFromEnvRequiresExplicitOperationalValues(t *testing.T) {
	t.Setenv("MCP_REQUEST_LEASE_TTL", "90s")
	t.Setenv("MCP_GATEWAY_STARTUP_TIMEOUT", "5m")
	t.Setenv("MCP_IDLE_TIMEOUT", "0")
	t.Setenv("MCP_IDLE_SWEEP_INTERVAL", "1m")
	t.Setenv("MCP_GATEWAY_AUTH_SECRET", testGatewaySecret)

	policy, err := LoadPolicyFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	if policy.IdleTimeout != 0 || policy.RequestLeaseTTL != 90*time.Second {
		t.Fatalf("unexpected policy: %+v", policy)
	}

	t.Setenv("MCP_REQUEST_LEASE_TTL", "invalid")
	if _, err := LoadPolicyFromEnv(); err == nil {
		t.Fatal("malformed duration was accepted")
	}
}

// slowStartRuntime blocks in EnsureReady long enough for the caller to give up,
// mirroring a real cold start whose readiness probe cannot succeed inside a
// short client timeout.
type slowStartRuntime struct {
	mu        sync.Mutex
	delay     time.Duration
	ensured   int
	deleted   int
	sawCancel bool
	endpoint  string
}

func (r *slowStartRuntime) EnsureReady(ctx context.Context, _ *models.MCPServerInstance) (string, error) {
	r.mu.Lock()
	r.ensured++
	delay := r.delay
	r.mu.Unlock()
	select {
	case <-ctx.Done():
		r.mu.Lock()
		r.sawCancel = true
		r.mu.Unlock()
		return "", ctx.Err()
	case <-time.After(delay):
	}
	return r.endpoint, nil
}

func (r *slowStartRuntime) Delete(context.Context, *models.MCPServerInstance) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.deleted++
	return nil
}

// TestAbandonedRequestDoesNotDestroyTheColdStart is the cold-start liveness
// contract. The caller's timeout is always shorter than a real readiness probe
// (verification allows 5s; the probe cannot report ready before ~8s). While the
// start inherited the request context, every such caller tore down the workload
// it had just created, so the next attempt started from nothing and
// container-backed MCP could never come up at all.
func TestAbandonedRequestDoesNotDestroyTheColdStart(t *testing.T) {
	instanceID := "8ca9f331-9cc9-4a51-9933-27d7bb73860b"
	repository := &gatewayRepositoryStub{instance: &models.MCPServerInstance{
		InstanceID: instanceID,
		JSONSpec:   map[string]any{"type": "docker"},
	}}
	runtime := &slowStartRuntime{delay: 400 * time.Millisecond, endpoint: "http://unused.test/mcp"}

	// The caller gives up well before the start could finish.
	callerCtx, abandon := context.WithCancel(context.Background())
	request := httptest.NewRequest(http.MethodPost, "/mcp/"+instanceID+"/mcp", strings.NewReader("{}")).
		WithContext(callerCtx)
	request.Header.Set("X-AgentArea-Manager-Authorization", "Bearer "+testGatewaySecret)

	served := make(chan struct{})
	go func() {
		testGateway(t, repository, runtime).ServeHTTP(httptest.NewRecorder(), request)
		close(served)
	}()
	time.Sleep(80 * time.Millisecond)
	abandon()
	<-served

	runtime.mu.Lock()
	defer runtime.mu.Unlock()
	if runtime.sawCancel {
		t.Error("the caller's cancellation reached the cold start; it must be bounded by StartupTimeout alone")
	}
	if runtime.deleted != 0 {
		t.Fatalf("an abandoned request tore down the workload %d time(s); the retry would start from nothing", runtime.deleted)
	}
	if runtime.ensured != 1 {
		t.Fatalf("EnsureReady calls = %d, want the start to have run once to completion", runtime.ensured)
	}
}
