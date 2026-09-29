package mcpgateway

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/models"
)

type requestObserverStub struct {
	mu           sync.Mutex
	started      []RequestStarted
	completed    []RequestCompleted
	startErr     error
	completedErr error
}

func (o *requestObserverStub) Started(_ context.Context, request RequestStarted) error {
	o.mu.Lock()
	defer o.mu.Unlock()
	o.started = append(o.started, request)
	return o.startErr
}

func (o *requestObserverStub) Completed(_ context.Context, request RequestCompleted) error {
	o.mu.Lock()
	defer o.mu.Unlock()
	o.completed = append(o.completed, request)
	return o.completedErr
}

func (o *requestObserverStub) snapshot() ([]RequestStarted, []RequestCompleted) {
	o.mu.Lock()
	defer o.mu.Unlock()
	return append([]RequestStarted(nil), o.started...), append([]RequestCompleted(nil), o.completed...)
}

type observedRuntimeStub struct{ endpoint string }

func (r observedRuntimeStub) EnsureReady(context.Context, *models.MCPServerInstance) (string, error) {
	return r.endpoint, nil
}
func (r observedRuntimeStub) Delete(context.Context, *models.MCPServerInstance) error { return nil }

func observedRequest(instanceID string, body io.Reader) *http.Request {
	request := httptest.NewRequest(http.MethodPost, "/mcp/"+instanceID+"/mcp", body)
	request.Header.Set("X-AgentArea-Manager-Authorization", "Bearer "+testGatewaySecret)
	return request
}

func TestRequestObserverSeesEachConcurrentRequestOnce(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusAccepted)
	}))
	defer upstream.Close()
	instance := &models.MCPServerInstance{InstanceID: "8ca9f331-9cc9-4a51-9933-27d7bb73860b", WorkspaceID: "ws-observed"}
	g := testGateway(t, &gatewayRepositoryStub{instance: instance}, observedRuntimeStub{endpoint: upstream.URL})
	observer := &requestObserverStub{}
	g.SetRequestObserver(observer)
	var group sync.WaitGroup
	for range 8 {
		group.Add(1)
		go func() {
			defer group.Done()
			w := httptest.NewRecorder()
			g.ServeHTTP(w, observedRequest(instance.InstanceID, strings.NewReader("{}")))
			if w.Code != http.StatusAccepted {
				t.Errorf("status = %d", w.Code)
			}
		}()
	}
	group.Wait()
	started, completed := observer.snapshot()
	if len(started) != 8 || len(completed) != 8 {
		t.Fatalf("started=%d completed=%d", len(started), len(completed))
	}
	ids := map[string]bool{}
	for _, request := range started {
		if request.InstanceID != instance.InstanceID || request.WorkspaceID != instance.WorkspaceID || request.Method != http.MethodPost {
			t.Fatalf("attribution = %+v", request)
		}
		ids[request.RequestID] = true
	}
	for _, request := range completed {
		if !ids[request.RequestID] || request.StatusCode != http.StatusAccepted || request.Canceled || request.EndedAt.Before(request.StartedAt) {
			t.Fatalf("completion = %+v", request)
		}
		delete(ids, request.RequestID)
	}
	if len(ids) != 0 {
		t.Fatalf("requests without completion: %v", ids)
	}
}

func TestRequestObserverStartFailureRefusesTheRequest(t *testing.T) {
	instance := &models.MCPServerInstance{InstanceID: "8ca9f331-9cc9-4a51-9933-27d7bb73860b", WorkspaceID: "ws-observed"}
	repository := &gatewayRepositoryStub{instance: instance}
	runtime := &runtimeStub{endpoint: "http://127.0.0.1:1/mcp"}
	g := testGateway(t, repository, runtime)
	observer := &requestObserverStub{startErr: errors.New("ledger unavailable")}
	g.SetRequestObserver(observer)
	w := httptest.NewRecorder()
	g.ServeHTTP(w, observedRequest(instance.InstanceID, nil))
	if w.Code != http.StatusServiceUnavailable || !strings.Contains(w.Body.String(), "MCP request processing unavailable") {
		t.Fatalf("response = %d %q", w.Code, w.Body.String())
	}
	if runtime.ensured != 0 || repository.starting != 0 {
		t.Fatalf("refused request reached lifecycle: ensured=%d starting=%d", runtime.ensured, repository.starting)
	}
	if _, completed := observer.snapshot(); len(completed) != 0 {
		t.Fatalf("refused request reported completion: %+v", completed)
	}
}

func TestRequestObserverCompletionFailureKeepsTheResponse(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusCreated)
		_, _ = io.WriteString(w, "proxied")
	}))
	defer upstream.Close()
	instance := &models.MCPServerInstance{InstanceID: "8ca9f331-9cc9-4a51-9933-27d7bb73860b", WorkspaceID: "ws-observed"}
	g := testGateway(t, &gatewayRepositoryStub{instance: instance}, observedRuntimeStub{endpoint: upstream.URL})
	g.SetRequestObserver(&requestObserverStub{completedErr: errors.New("ledger unavailable")})
	w := httptest.NewRecorder()
	g.ServeHTTP(w, observedRequest(instance.InstanceID, nil))
	if w.Code != http.StatusCreated || w.Body.String() != "proxied" {
		t.Fatalf("response = %d %q", w.Code, w.Body.String())
	}
}

func TestRequestObserverDistinguishesAbsentRoutingHeaders(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusAccepted)
	}))
	defer upstream.Close()
	instance := &models.MCPServerInstance{InstanceID: "8ca9f331-9cc9-4a51-9933-27d7bb73860b", WorkspaceID: "ws-observed"}
	g := testGateway(t, &gatewayRepositoryStub{instance: instance}, observedRuntimeStub{endpoint: upstream.URL})
	observer := &requestObserverStub{}
	g.SetRequestObserver(observer)
	routed := observedRequest(instance.InstanceID, nil)
	routed.Header.Set("Mcp-Method", "tools/call")
	routed.Header.Set("Mcp-Name", "")
	g.ServeHTTP(httptest.NewRecorder(), routed)
	g.ServeHTTP(httptest.NewRecorder(), observedRequest(instance.InstanceID, nil))
	started, _ := observer.snapshot()
	if len(started) != 2 {
		t.Fatalf("started = %d", len(started))
	}
	if started[0].MCPMethod == nil || *started[0].MCPMethod != "tools/call" || started[0].MCPName == nil || *started[0].MCPName != "" {
		t.Fatalf("routed request headers = %+v", started[0])
	}
	if started[1].MCPMethod != nil || started[1].MCPName != nil {
		t.Fatalf("2025-era request gained routing headers: %+v", started[1])
	}
}

func TestRequestObserverKeepsStreamingRequestOpen(t *testing.T) {
	release := make(chan struct{})
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, "data: first\n\n")
		w.(http.Flusher).Flush()
		select {
		case <-release:
		case <-r.Context().Done():
		}
	}))
	defer upstream.Close()
	defer close(release)
	instance := &models.MCPServerInstance{InstanceID: "8ca9f331-9cc9-4a51-9933-27d7bb73860b", WorkspaceID: "ws-observed"}
	g := testGateway(t, &gatewayRepositoryStub{instance: instance}, observedRuntimeStub{endpoint: upstream.URL})
	observer := &requestObserverStub{}
	g.SetRequestObserver(observer)
	server := httptest.NewServer(g)
	defer server.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	r, _ := http.NewRequestWithContext(ctx, http.MethodGet, server.URL+"/mcp/"+instance.InstanceID+"/mcp", nil)
	r.Header.Set("X-AgentArea-Manager-Authorization", "Bearer "+testGatewaySecret)
	response, err := http.DefaultClient.Do(r)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	chunk := make([]byte, len("data: first\n\n"))
	if _, err := io.ReadFull(response.Body, chunk); err != nil {
		t.Fatal(err)
	}
	started, completed := observer.snapshot()
	if len(started) != 1 || len(completed) != 0 {
		t.Fatalf("open stream: started=%d completed=%d", len(started), len(completed))
	}
}

type abortingObservedWriter struct{ *httptest.ResponseRecorder }

func (w abortingObservedWriter) Write([]byte) (int, error) { panic(http.ErrAbortHandler) }

func TestRequestObserverGetsNoCompletionAfterProxyAbort(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(w, "response")
	}))
	defer upstream.Close()
	instance := &models.MCPServerInstance{InstanceID: "8ca9f331-9cc9-4a51-9933-27d7bb73860b", WorkspaceID: "ws-observed"}
	repository := &gatewayRepositoryStub{instance: instance}
	g := testGateway(t, repository, observedRuntimeStub{endpoint: upstream.URL})
	observer := &requestObserverStub{}
	g.SetRequestObserver(observer)
	var aborted any
	func() {
		defer func() { aborted = recover() }()
		g.ServeHTTP(abortingObservedWriter{httptest.NewRecorder()}, observedRequest(instance.InstanceID, nil))
	}()
	if aborted != http.ErrAbortHandler {
		t.Fatalf("proxy abort = %v", aborted)
	}
	started, completed := observer.snapshot()
	if len(started) != 1 || len(completed) != 0 {
		t.Fatalf("aborted request: started=%d completed=%d", len(started), len(completed))
	}
	if repository.finished != 1 {
		t.Fatal("aborted stream leaked its live request lease")
	}
}

type runtimeObserverStub struct {
	mu          sync.Mutex
	operations  []RuntimeOperation
	boundaries  []BoundaryObservation
	contextErrs []error
	boundaryErr error
	onBoundary  func(BoundaryObservation)
}

func (o *runtimeObserverStub) Operation(_ context.Context, operation RuntimeOperation) error {
	o.mu.Lock()
	defer o.mu.Unlock()
	o.operations = append(o.operations, operation)
	return nil
}

func (o *runtimeObserverStub) Boundary(ctx context.Context, observation BoundaryObservation) error {
	o.mu.Lock()
	o.boundaries = append(o.boundaries, observation)
	o.contextErrs = append(o.contextErrs, ctx.Err())
	o.mu.Unlock()
	if o.onBoundary != nil {
		o.onBoundary(observation)
	}
	return o.boundaryErr
}

func TestRuntimeObserverSeesCreationOncePerWorkload(t *testing.T) {
	backend := &runtimeBackendStub{statuses: []statusReply{{err: backends.ErrInstanceNotFound}, {status: "running"}}}
	runtime := testProviderRuntime(t, backend, &runtimeProviderStub{}, time.Second)
	observer := &runtimeObserverStub{}
	runtime.SetRuntimeObserver(observer)
	instance := dockerInstance()
	instance.WorkspaceID = "ws-observed"
	for range 4 {
		if _, err := runtime.EnsureReady(context.Background(), instance); err != nil {
			t.Fatal(err)
		}
	}
	if len(observer.operations) != 2 || observer.operations[0].Phase != OperationStarted || observer.operations[1].Phase != OperationCompleted {
		t.Fatalf("warm requests multiplied creation: %+v", observer.operations)
	}
	if observer.operations[0].OperationID == "" || observer.operations[0].OperationID != observer.operations[1].OperationID {
		t.Fatalf("creation phases are not correlated: %+v", observer.operations)
	}
	if len(observer.boundaries) != 1 || observer.boundaries[0].Boundary != BoundaryActivation || observer.boundaries[0].OperationID != observer.operations[0].OperationID {
		t.Fatalf("activation boundary = %+v", observer.boundaries)
	}
	if err := runtime.Delete(context.Background(), instance); err != nil {
		t.Fatal(err)
	}
	last := observer.operations[len(observer.operations)-1]
	if last.Operation != OperationDeletion || last.Phase != OperationCompleted || last.Resource.WorkspaceID != instance.WorkspaceID {
		t.Fatalf("deletion = %+v", last)
	}
}

func TestRuntimeObserverBoundaryPrecedesDestruction(t *testing.T) {
	instance := dockerInstance()
	observer := &runtimeObserverStub{}
	provider := &boundaryOrderProvider{observer: observer}
	runtime := testProviderRuntime(t, &runtimeBackendStub{}, provider, time.Second)
	runtime.SetRuntimeObserver(observer)
	if err := runtime.Delete(context.Background(), instance); err != nil {
		t.Fatal(err)
	}
	if !provider.boundarySeen {
		t.Fatal("provider destruction preceded the deletion boundary")
	}
}

type boundaryOrderProvider struct {
	runtimeProviderStub
	observer     *runtimeObserverStub
	boundarySeen bool
}

func (p *boundaryOrderProvider) DeleteInstance(ctx context.Context, id, name string) error {
	p.observer.mu.Lock()
	p.boundarySeen = len(p.observer.boundaries) == 1 && p.observer.boundaries[0].Boundary == BoundaryDeletion
	p.observer.mu.Unlock()
	return p.runtimeProviderStub.DeleteInstance(ctx, id, name)
}

func TestRuntimeObserverFailedBoundaryKeepsTheWorkload(t *testing.T) {
	provider := &runtimeProviderStub{}
	runtime := testProviderRuntime(t, &runtimeBackendStub{}, provider, time.Second)
	boundaryErr := errors.New("observation unavailable")
	runtime.SetRuntimeObserver(&runtimeObserverStub{boundaryErr: boundaryErr})
	if err := runtime.Delete(context.Background(), dockerInstance()); !errors.Is(err, boundaryErr) {
		t.Fatalf("delete error = %v", err)
	}
	if _, deletes := provider.counts(); deletes != 0 {
		t.Fatal("provider destruction preceded an observed boundary")
	}
}

func TestRuntimeObserverFailedActivationCleanupIsNotCancelled(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	observer := &runtimeObserverStub{}
	provider := &runtimeProviderStub{}
	runtime := testProviderRuntime(t, &runtimeBackendStub{statuses: []statusReply{{status: "pending"}}}, provider, time.Second)
	runtime.SetRuntimeObserver(observer)
	if _, err := runtime.EnsureReady(ctx, dockerInstance()); !errors.Is(err, context.Canceled) {
		t.Fatalf("activation error = %v", err)
	}
	if len(observer.boundaries) != 1 || observer.boundaries[0].Boundary != BoundaryFailedStartCleanup {
		t.Fatalf("cleanup boundaries = %+v", observer.boundaries)
	}
	if observer.contextErrs[0] != nil {
		t.Fatalf("cleanup observation inherited the cancelled activation: %v", observer.contextErrs[0])
	}
	if _, deletes := provider.counts(); deletes != 1 {
		t.Fatalf("cleanup deletions = %d", deletes)
	}
}
