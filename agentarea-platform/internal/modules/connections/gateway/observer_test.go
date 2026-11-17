package gateway

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"
)

func TestRequestObserverSeesEachConcurrentRequestOnce(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK) }))
	defer upstream.Close()
	obs := &recordingObserver{}
	rt := &fakeRuntime{admit: admitTo(upstream.URL+"/mcp", &fakeLease{})}
	o := testOptions(rt)
	o.Observer = obs
	g := newTestGateway(t, o)
	const n = 12
	var wg sync.WaitGroup
	for range n {
		wg.Go(func() { g.ServeHTTP(httptest.NewRecorder(), mcpRequest(http.MethodPost, "{}")) })
	}
	wg.Wait()
	started, completed := obs.snapshot()
	if len(started) != n || len(completed) != n {
		t.Fatalf("started=%d completed=%d", len(started), len(completed))
	}
	ids := map[string]bool{}
	for _, c := range completed {
		ids[c.RequestID] = true
	}
	if len(ids) != n {
		t.Fatalf("%d distinct request ids for %d requests", len(ids), n)
	}
	rt.mu.Lock()
	defer rt.mu.Unlock()
	for _, id := range rt.admits {
		if !ids[id] {
			t.Fatalf("admitted request %s was never observed", id)
		}
	}
}

func TestRequestObserverReportsTheRequest(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusTeapot) }))
	defer upstream.Close()
	obs := &recordingObserver{}
	o := testOptions(&fakeRuntime{admit: admitTo(upstream.URL+"/mcp", &fakeLease{})})
	o.Observer = obs
	g := newTestGateway(t, o)
	req := mcpRequest(http.MethodPost, "{}")
	req.Header.Set("Mcp-Method", "tools/call")
	req.Header.Set("Mcp-Name", "search")
	g.ServeHTTP(httptest.NewRecorder(), req)

	_, completed := obs.snapshot()
	if len(completed) != 1 {
		t.Fatalf("completed %d", len(completed))
	}
	c := completed[0]
	if c.InstanceID != testInstance || c.WorkspaceID != testWS || c.Method != http.MethodPost || c.StatusCode != http.StatusTeapot {
		t.Fatalf("completed %+v", c)
	}
	if c.MCPMethod == nil || *c.MCPMethod != "tools/call" || c.MCPName == nil || *c.MCPName != "search" {
		t.Fatalf("routing headers %v %v", c.MCPMethod, c.MCPName)
	}
	if c.EndedAt.Before(c.StartedAt) || c.Canceled || c.Answer != "" || c.ColdStart != nil {
		t.Fatalf("completed %+v", c)
	}
}

func TestRequestObserverDistinguishesAbsentRoutingHeaders(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK) }))
	defer upstream.Close()
	obs := &recordingObserver{}
	o := testOptions(&fakeRuntime{admit: admitTo(upstream.URL+"/mcp", &fakeLease{})})
	o.Observer = obs
	g := newTestGateway(t, o)
	g.ServeHTTP(httptest.NewRecorder(), mcpRequest(http.MethodPost, "{}"))
	started, _ := obs.snapshot()
	if len(started) != 1 || started[0].MCPMethod != nil || started[0].MCPName != nil {
		t.Fatalf("started %+v", started)
	}
}

func TestRequestObserverReportsAColdStartThatSucceeded(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK) }))
	defer upstream.Close()
	obs := &recordingObserver{}
	rt := &fakeRuntime{admit: func(_ context.Context, _ Target, _ string, report *ColdStart) (Admission, error) {
		report.Begin()
		report.Phase(StepRunning, time.Now().Add(-time.Second), nil)
		report.Total = 2 * time.Second
		return Admission{Upstream: upstream.URL + "/mcp", Lease: &fakeLease{}}, nil
	}}
	o := testOptions(rt)
	o.Observer = obs
	g := newTestGateway(t, o)
	g.ServeHTTP(httptest.NewRecorder(), mcpRequest(http.MethodPost, "{}"))
	_, completed := obs.snapshot()
	cs := completed[0].ColdStart
	if cs == nil || cs.Outcome != ColdStartReady || cs.Reason != "" || cs.Running < time.Second || cs.Total != 2*time.Second {
		t.Fatalf("cold start %+v", cs)
	}
}

func TestRequestObserverStartFailureRefusesTheRequest(t *testing.T) {
	obs := &recordingObserver{startErr: errors.New("audit store down")}
	rt := &fakeRuntime{admit: admitTo("http://127.0.0.1:1/mcp", &fakeLease{})}
	o := testOptions(rt)
	o.Observer = obs
	g := newTestGateway(t, o)
	rec := httptest.NewRecorder()
	g.ServeHTTP(rec, mcpRequest(http.MethodPost, "{}"))
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status %d", rec.Code)
	}
	if _, admits, _, _ := rt.counts(); admits != 0 {
		t.Fatal("a refused request started the workload")
	}
	if _, completed := obs.snapshot(); len(completed) != 0 {
		t.Fatal("a refused request was reported completed")
	}
}

func TestRequestObserverCompletionFailureKeepsTheResponse(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { _, _ = io.WriteString(w, "ok") }))
	defer upstream.Close()
	obs := &recordingObserver{completeErr: errors.New("audit store down")}
	o := testOptions(&fakeRuntime{admit: admitTo(upstream.URL+"/mcp", &fakeLease{})})
	o.Observer = obs
	g := newTestGateway(t, o)
	rec := httptest.NewRecorder()
	g.ServeHTTP(rec, mcpRequest(http.MethodPost, "{}"))
	if rec.Code != http.StatusOK || rec.Body.String() != "ok" {
		t.Fatalf("status %d body %q", rec.Code, rec.Body.String())
	}
}

func TestRequestObserverKeepsAStreamingRequestOpen(t *testing.T) {
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
	obs := &recordingObserver{}
	o := testOptions(&fakeRuntime{admit: admitTo(upstream.URL+"/mcp", &fakeLease{})})
	o.Observer = obs
	server := httptest.NewServer(newTestGateway(t, o))
	defer server.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, server.URL+"/mcp/"+testInstance+"/mcp", nil)
	req.Header.Set(AuthHeader, "Bearer "+testSecret)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	chunk := make([]byte, len("data: first\n\n"))
	if _, err := io.ReadFull(resp.Body, chunk); err != nil {
		t.Fatal(err)
	}
	started, completed := obs.snapshot()
	if len(started) != 1 || len(completed) != 0 {
		t.Fatalf("open stream: started=%d completed=%d", len(started), len(completed))
	}
}

type abortingWriter struct{ *httptest.ResponseRecorder }

func (abortingWriter) Write([]byte) (int, error) { panic(http.ErrAbortHandler) }

func TestAProxyAbortEndsTelemetryButIsNotACompletion(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { _, _ = io.WriteString(w, "response") }))
	defer upstream.Close()
	obs := &recordingObserver{}
	lease := &fakeLease{}
	tel, reader := newTestTelemetry(t, false)
	o := testOptions(&fakeRuntime{admit: admitTo(upstream.URL+"/mcp", lease)})
	o.Observer, o.Telemetry = obs, tel
	g := newTestGateway(t, o)
	var aborted any
	func() {
		defer func() { aborted = recover() }()
		g.ServeHTTP(abortingWriter{httptest.NewRecorder()}, mcpRequest(http.MethodPost, "{}"))
	}()
	if err, _ := aborted.(error); !errors.Is(err, http.ErrAbortHandler) {
		t.Fatalf("recovered %v, want http.ErrAbortHandler re-panicked", aborted)
	}
	started, completed := obs.snapshot()
	if len(started) != 1 || len(completed) != 0 {
		t.Fatalf("aborted request: started=%d completed=%d", len(started), len(completed))
	}
	if lease.finishes.Load() != 1 {
		t.Fatal("an aborted stream leaked its request lease")
	}
	metrics := collectMetrics(t, reader)
	if got := inFlight(metrics); got != 0 {
		t.Fatalf("in_flight = %d after an aborted request", got)
	}
	if got := requestCount(metrics, "aborted"); got != 1 {
		t.Fatalf("requests{aborted} = %d", got)
	}
}
