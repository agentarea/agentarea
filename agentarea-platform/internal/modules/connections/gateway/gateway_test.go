package gateway

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	kobs "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/obs"
)

func TestNewRefusesIncompleteOptions(t *testing.T) {
	rt := &fakeRuntime{}
	cases := map[string]func(*Options){
		"no runtime":   func(o *Options) { o.Runtime = nil },
		"no logger":    func(o *Options) { o.Log = nil },
		"no transport": func(o *Options) { o.URLs = nil },
		"no lease":     func(o *Options) { o.LeaseTTL = 0 },
		"short secret": func(o *Options) { o.Secret = "short" },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			o := testOptions(rt)
			mutate(&o)
			if _, err := New(o); err == nil {
				t.Fatal("New accepted incomplete options")
			}
		})
	}
}

func TestGatewayAuthenticatesStartsAndProxiesTheWholeRequest(t *testing.T) {
	var seen struct {
		path, body, auth, managerAuth, method string
	}
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		seen.path, seen.body, seen.method = r.URL.Path, string(b), r.Header.Get("Mcp-Method")
		seen.auth, seen.managerAuth = r.Header.Get("Authorization"), r.Header.Get(AuthHeader)
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"jsonrpc":"2.0","id":1,"result":{}}`)
	}))
	defer upstream.Close()
	lease := &fakeLease{}
	rt := &fakeRuntime{admit: admitTo(upstream.URL+"/mcp", lease)}
	g := newTestGateway(t, testOptions(rt))

	req := mcpRequest(http.MethodPost, `{"jsonrpc":"2.0","id":1,"method":"tools/list"}`)
	req.Header.Set("Mcp-Method", "tools/list")
	rec := httptest.NewRecorder()
	g.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK || !strings.Contains(rec.Body.String(), `"result"`) {
		t.Fatalf("status %d body %q", rec.Code, rec.Body.String())
	}
	if seen.path != "/mcp" || seen.body != `{"jsonrpc":"2.0","id":1,"method":"tools/list"}` || seen.method != "tools/list" {
		t.Fatalf("upstream saw %+v", seen)
	}
	if seen.managerAuth != "" {
		t.Fatal("the manager credential reached the workload")
	}
	if lease.finishes.Load() != 1 {
		t.Fatalf("lease finished %d times", lease.finishes.Load())
	}
	if _, admits, _, _ := rt.counts(); admits != 1 {
		t.Fatalf("admits = %d", admits)
	}
}

func TestGatewayRefusesAMissingOrWrongCredentialBeforeTheLifecycle(t *testing.T) {
	rt := &fakeRuntime{retire: func(context.Context, string) error { return nil }}
	g := newTestGateway(t, testOptions(rt))
	for _, header := range []string{"", "Bearer wrong", testSecret, "Basic " + testSecret} {
		for _, method := range []string{http.MethodPost, http.MethodDelete} {
			path := "/mcp/" + testInstance + "/mcp"
			if method == http.MethodDelete {
				path = "/mcp/" + testInstance
			}
			req := httptest.NewRequest(method, path, strings.NewReader("{}"))
			if header != "" {
				req.Header.Set(AuthHeader, header)
			}
			rec := httptest.NewRecorder()
			g.ServeHTTP(rec, req)
			if rec.Code != http.StatusUnauthorized {
				t.Errorf("%s with %q: status %d", method, header, rec.Code)
			}
		}
	}
	if loads, admits, _, retires := rt.counts(); loads+admits+retires != 0 {
		t.Fatalf("lifecycle reached: loads=%d admits=%d retires=%d", loads, admits, retires)
	}
}

func TestGatewayWithoutASecretIsTheInProcessHandler(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusAccepted) }))
	defer upstream.Close()
	o := testOptions(&fakeRuntime{admit: admitTo(upstream.URL+"/mcp", &fakeLease{})})
	o.Secret = ""
	g := newTestGateway(t, o)
	rec := httptest.NewRecorder()
	g.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/mcp/"+testInstance+"/mcp", strings.NewReader("{}")))
	if rec.Code != http.StatusAccepted {
		t.Fatalf("status %d", rec.Code)
	}
}

func TestGatewayRefusesAnInstanceIDThatIsNotAUUID(t *testing.T) {
	rt := &fakeRuntime{}
	g := newTestGateway(t, testOptions(rt))
	req := httptest.NewRequest(http.MethodPost, "/mcp/not-a-uuid/mcp", strings.NewReader("{}"))
	req.Header.Set(AuthHeader, "Bearer "+testSecret)
	rec := httptest.NewRecorder()
	g.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status %d", rec.Code)
	}
	if loads, _, _, _ := rt.counts(); loads != 0 {
		t.Fatal("an invalid id reached the runtime")
	}
}

func TestGatewayStripsReservedLifecycleHeadersFromTheWorkloadResponse(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set(StartingHeader, "1")
		w.Header().Set(StartFailureHeader, "forged")
		w.Header().Set("Mcp-Session-Id", "s1")
		w.WriteHeader(http.StatusOK)
	}))
	defer upstream.Close()
	g := newTestGateway(t, testOptions(&fakeRuntime{admit: admitTo(upstream.URL+"/mcp", &fakeLease{})}))
	rec := httptest.NewRecorder()
	g.ServeHTTP(rec, mcpRequest(http.MethodPost, "{}"))
	if rec.Header().Get(StartingHeader) != "" || rec.Header().Get(StartFailureHeader) != "" {
		t.Fatalf("reserved headers leaked: %v", rec.Header())
	}
	if rec.Header().Get("Mcp-Session-Id") != "s1" {
		t.Fatal("the workload's own headers were dropped")
	}
}

type zeros struct{}

func (zeros) Read(p []byte) (int, error) {
	clear(p)
	return len(p), nil
}

func TestGatewayRefusesAnOversizedBodyBeforeStarting(t *testing.T) {
	rt := &fakeRuntime{}
	tel, reader := newTestTelemetry(t, false)
	o := testOptions(rt)
	o.Telemetry = tel
	g := newTestGateway(t, o)
	req := httptest.NewRequest(http.MethodPost, "/mcp/"+testInstance+"/mcp", io.LimitReader(zeros{}, maxRequestBodyBytes+1))
	req.Header.Set(AuthHeader, "Bearer "+testSecret)
	rec := httptest.NewRecorder()
	g.ServeHTTP(rec, req)
	if rec.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("status %d", rec.Code)
	}
	if loads, admits, _, _ := rt.counts(); loads+admits != 0 {
		t.Fatal("an oversized body reached the runtime")
	}
	if got := requestCount(collectMetrics(t, reader), "4xx"); got != 1 {
		t.Fatalf("requests{4xx} = %d", got)
	}
}

func TestGatewayAnswersBadGatewayWhenTheInstanceCannotBeLoaded(t *testing.T) {
	for name, loadErr := range map[string]error{
		"not found": fmt.Errorf("load: %w", ErrInstanceNotFound),
		"db down":   errors.New("db down"),
	} {
		t.Run(name, func(t *testing.T) {
			rt := &fakeRuntime{load: func(context.Context, string) (Target, error) { return Target{}, loadErr }}
			tel, reader := newTestTelemetry(t, false)
			obs := &recordingObserver{}
			o := testOptions(rt)
			o.Telemetry, o.Observer = tel, obs
			g := newTestGateway(t, o)
			rec := httptest.NewRecorder()
			g.ServeHTTP(rec, mcpRequest(http.MethodPost, "{}"))
			if rec.Code != http.StatusBadGateway {
				t.Fatalf("status %d", rec.Code)
			}
			if started, _ := obs.snapshot(); len(started) != 0 {
				t.Fatal("an unloaded instance was observed as started")
			}
			if got := requestCount(collectMetrics(t, reader), "5xx"); got != 1 {
				t.Fatalf("requests{5xx} = %d", got)
			}
		})
	}
}

func TestGatewayAnswersAConcurrentStartAsRetryable(t *testing.T) {
	obs := &recordingObserver{}
	rt := &fakeRuntime{admit: func(context.Context, Target, string, *ColdStart) (Admission, error) {
		return Admission{}, fmt.Errorf("lock: %w", ErrStartInProgress)
	}}
	o := testOptions(rt)
	o.Observer = obs
	g := newTestGateway(t, o)
	rec := httptest.NewRecorder()
	g.ServeHTTP(rec, mcpRequest(http.MethodPost, "{}"))
	if rec.Code != http.StatusServiceUnavailable || rec.Header().Get("Retry-After") != "1" || rec.Header().Get(StartingHeader) != "1" {
		t.Fatalf("status %d headers %v", rec.Code, rec.Header())
	}
	if rec.Header().Get(StartFailureHeader) != "" {
		t.Fatal("a start in progress was reported as a failure")
	}
	_, completed := obs.snapshot()
	if len(completed) != 1 || completed[0].Answer != AnswerStarting || completed[0].StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("completed %+v", completed)
	}
}

func TestGatewayReturnsAClassifiedStartupFailureAsRetryable(t *testing.T) {
	obs := &recordingObserver{}
	rt := &fakeRuntime{admit: func(_ context.Context, _ Target, _ string, report *ColdStart) (Admission, error) {
		report.Begin()
		report.Fail(StepCreate)
		return Admission{}, &startFailure{reason: "image café\nmissing", delay: 1500 * time.Millisecond}
	}}
	o := testOptions(rt)
	o.Observer = obs
	g := newTestGateway(t, o)
	rec := httptest.NewRecorder()
	g.ServeHTTP(rec, mcpRequest(http.MethodPost, "{}"))
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status %d", rec.Code)
	}
	if got := rec.Header().Get(StartFailureHeader); got != "image caf???missing" {
		t.Fatalf("start failure header %q", got)
	}
	if got := rec.Header().Get("Retry-After"); got != "2" {
		t.Fatalf("Retry-After %q", got)
	}
	if !strings.Contains(rec.Body.String(), "image caf???missing") {
		t.Fatalf("body %q", rec.Body.String())
	}
	_, completed := obs.snapshot()
	if len(completed) != 1 || completed[0].Answer != AnswerStartFailed {
		t.Fatalf("completed %+v", completed)
	}
	cs := completed[0].ColdStart
	if cs == nil || cs.Outcome != ColdStartFailed || cs.Reason != "create_failed" {
		t.Fatalf("cold start %+v", cs)
	}
}

func TestGatewayAnswersAnUnclassifiedFailureAsBadGateway(t *testing.T) {
	for name, err := range map[string]error{
		"plain":        errors.New("backend down"),
		"empty reason": &startFailure{reason: "  ", delay: time.Minute},
	} {
		t.Run(name, func(t *testing.T) {
			rt := &fakeRuntime{admit: func(context.Context, Target, string, *ColdStart) (Admission, error) { return Admission{}, err }}
			g := newTestGateway(t, testOptions(rt))
			rec := httptest.NewRecorder()
			g.ServeHTTP(rec, mcpRequest(http.MethodPost, "{}"))
			if rec.Code != http.StatusBadGateway || rec.Header().Get("Retry-After") != "5" || rec.Header().Get(StartFailureHeader) != "" {
				t.Fatalf("status %d headers %v", rec.Code, rec.Header())
			}
			if strings.Contains(rec.Body.String(), "backend down") {
				t.Fatal("an unclassified cause reached the caller")
			}
		})
	}
}

func TestGatewayRefusesAnUpstreamItMustNotReach(t *testing.T) {
	for name, adm := range map[string]Admission{
		"local https":  {Upstream: "https://10.0.0.1/mcp"},
		"other scheme": {Upstream: "ftp://10.0.0.1/mcp"},
		"no host":      {Upstream: "http:///mcp"},
	} {
		t.Run(name, func(t *testing.T) {
			lease := &fakeLease{}
			adm.Lease = lease
			rt := &fakeRuntime{admit: func(context.Context, Target, string, *ColdStart) (Admission, error) { return adm, nil }}
			g := newTestGateway(t, testOptions(rt))
			rec := httptest.NewRecorder()
			g.ServeHTTP(rec, mcpRequest(http.MethodPost, "{}"))
			if rec.Code != http.StatusBadGateway {
				t.Fatalf("status %d", rec.Code)
			}
			if lease.finishes.Load() != 1 {
				t.Fatal("a refused upstream kept its lease")
			}
		})
	}
}

func TestGatewayAuthorizesTheRemoteHop(t *testing.T) {
	var auth string
	upstream := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		auth = r.Header.Get("Authorization")
		if r.URL.Path != "/dataplane/v1/instances/"+testInstance+"/proxy/mcp" {
			http.Error(w, r.URL.Path, http.StatusNotFound)
			return
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer upstream.Close()
	lease := &fakeLease{}
	rt := &fakeRuntime{admit: func(context.Context, Target, string, *ColdStart) (Admission, error) {
		return Admission{
			Upstream: upstream.URL + "/dataplane/v1/instances/" + testInstance + "/proxy/mcp", Remote: true, Lease: lease,
			Authorize: func(r *http.Request) bool { r.Header.Set("Authorization", "Bearer dp-token"); return true },
		}, nil
	}}
	o := testOptions(rt)
	o.Workloads = upstream.Client().Transport
	g := newTestGateway(t, o)
	rec := httptest.NewRecorder()
	g.ServeHTTP(rec, mcpRequest(http.MethodPost, "{}"))
	if rec.Code != http.StatusOK {
		t.Fatalf("status %d body %q", rec.Code, rec.Body.String())
	}
	if auth != "Bearer dp-token" {
		t.Fatalf("data plane saw Authorization %q", auth)
	}
	if lease.finishes.Load() != 1 {
		t.Fatal("lease not finished")
	}
}

func TestGatewayAnswersBadGatewayWhenTheWorkloadIsUnreachable(t *testing.T) {
	upstream := httptest.NewServer(http.NotFoundHandler())
	addr := upstream.URL
	upstream.Close()
	lease := &fakeLease{}
	tel, reader := newTestTelemetry(t, false)
	o := testOptions(&fakeRuntime{admit: admitTo(addr+"/mcp", lease)})
	o.Telemetry = tel
	g := newTestGateway(t, o)
	rec := httptest.NewRecorder()
	g.ServeHTTP(rec, mcpRequest(http.MethodPost, "{}"))
	if rec.Code != http.StatusBadGateway {
		t.Fatalf("status %d", rec.Code)
	}
	if lease.finishes.Load() != 1 {
		t.Fatal("lease not finished")
	}
	if got := sumWhere(collectMetrics(t, reader), kobs.MCPUpstreamResponses, kobs.AttrStatus, "error"); got != 1 {
		t.Fatalf("upstream{error} = %d", got)
	}
}

func TestGatewayRenewsTheLeaseWhileTheRequestRuns(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		time.Sleep(120 * time.Millisecond)
		w.WriteHeader(http.StatusOK)
	}))
	defer upstream.Close()
	lease := &fakeLease{}
	o := testOptions(&fakeRuntime{admit: admitTo(upstream.URL+"/mcp", lease)})
	o.LeaseTTL = 30 * time.Millisecond
	g := newTestGateway(t, o)
	rec := httptest.NewRecorder()
	g.ServeHTTP(rec, mcpRequest(http.MethodPost, "{}"))
	if rec.Code != http.StatusOK {
		t.Fatalf("status %d", rec.Code)
	}
	if lease.heartbeats.Load() < 2 {
		t.Fatalf("heartbeats = %d over a request of four lease thirds", lease.heartbeats.Load())
	}
	if lease.finishes.Load() != 1 {
		t.Fatalf("finishes = %d", lease.finishes.Load())
	}
}

func TestGatewayCutsTheRequestWhenTheLeaseIsLost(t *testing.T) {
	canceled := make(chan struct{})
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		select {
		case <-r.Context().Done():
			close(canceled)
		case <-time.After(5 * time.Second):
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer upstream.Close()
	lease := &fakeLease{heartbeatErr: errors.New("lease row gone")}
	o := testOptions(&fakeRuntime{admit: admitTo(upstream.URL+"/mcp", lease)})
	o.LeaseTTL = 30 * time.Millisecond
	g := newTestGateway(t, o)
	rec := httptest.NewRecorder()
	g.ServeHTTP(rec, mcpRequest(http.MethodPost, "{}"))
	select {
	case <-canceled:
	case <-time.After(5 * time.Second):
		t.Fatal("a lost lease left the workload request running")
	}
	if rec.Code != http.StatusBadGateway {
		t.Fatalf("status %d", rec.Code)
	}
	if lease.finishes.Load() != 1 {
		t.Fatal("lease not finished")
	}
}

func TestAbandonedRequestDoesNotCancelTheColdStart(t *testing.T) {
	var mu sync.Mutex
	var startErr error
	admitted := make(chan struct{})
	rt := &fakeRuntime{admit: func(ctx context.Context, _ Target, _ string, report *ColdStart) (Admission, error) {
		report.Begin()
		close(admitted)
		time.Sleep(200 * time.Millisecond)
		mu.Lock()
		startErr = ctx.Err()
		mu.Unlock()
		return Admission{Upstream: "http://127.0.0.1:1/mcp", Lease: &fakeLease{}}, nil
	}}
	g := newTestGateway(t, testOptions(rt))
	ctx, abandon := context.WithCancel(context.Background())
	req := mcpRequest(http.MethodPost, "{}").WithContext(ctx)
	served := make(chan struct{})
	go func() {
		g.ServeHTTP(httptest.NewRecorder(), req)
		close(served)
	}()
	<-admitted
	abandon()
	<-served
	mu.Lock()
	defer mu.Unlock()
	if startErr != nil {
		t.Fatalf("the caller's cancellation reached the cold start: %v", startErr)
	}
}

func TestGatewayRetiresAndClassifiesTheAnswer(t *testing.T) {
	cases := []struct {
		err    error
		status int
		retry  string
	}{
		{nil, http.StatusNoContent, ""},
		{fmt.Errorf("x: %w", ErrInstanceNotFound), http.StatusNotFound, ""},
		{fmt.Errorf("x: %w", ErrInstanceBusy), http.StatusConflict, "5"},
		{fmt.Errorf("x: %w", ErrStartInProgress), http.StatusConflict, "5"},
		{errors.New("docker down"), http.StatusBadGateway, "5"},
	}
	for _, tc := range cases {
		t.Run(fmt.Sprint(tc.status, tc.err), func(t *testing.T) {
			var got string
			rt := &fakeRuntime{retire: func(_ context.Context, id string) error { got = id; return tc.err }}
			g := newTestGateway(t, testOptions(rt))
			req := httptest.NewRequest(http.MethodDelete, "/mcp/"+strings.ToUpper(testInstance), nil)
			req.Header.Set(AuthHeader, "Bearer "+testSecret)
			rec := httptest.NewRecorder()
			g.ServeHTTP(rec, req)
			if rec.Code != tc.status || rec.Header().Get("Retry-After") != tc.retry {
				t.Fatalf("status %d Retry-After %q", rec.Code, rec.Header().Get("Retry-After"))
			}
			if got != testInstance {
				t.Fatalf("retired %q, want the canonical id", got)
			}
			if strings.Contains(rec.Body.String(), "docker down") {
				t.Fatal("the cause reached the caller")
			}
		})
	}
}

func TestRoutesMountOnACallersMux(t *testing.T) {
	rt := &fakeRuntime{retire: func(context.Context, string) error { return nil }}
	g := newTestGateway(t, testOptions(rt))
	mux := http.NewServeMux()
	g.Routes(mux)
	req := httptest.NewRequest(http.MethodDelete, "/mcp/"+testInstance, nil)
	req.Header.Set(AuthHeader, "Bearer "+testSecret)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)
	if rec.Code != http.StatusNoContent {
		t.Fatalf("status %d", rec.Code)
	}
}
