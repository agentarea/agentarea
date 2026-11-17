package gateway

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"go.opentelemetry.io/otel/attribute"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"

	kobs "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/obs"
)

const (
	testSecret   = "0123456789abcdef0123456789abcdef"
	testInstance = "8ca9f331-9cc9-4a51-9933-27d7bb73860b"
	testWS       = "ws-gateway"
)

type fakeLease struct {
	heartbeats   atomic.Int32
	finishes     atomic.Int32
	heartbeatErr error
}

func (l *fakeLease) Heartbeat(context.Context) error {
	l.heartbeats.Add(1)
	return l.heartbeatErr
}

func (l *fakeLease) Finish(context.Context) error {
	l.finishes.Add(1)
	return nil
}

// fakeRuntime is the gateway's Runtime with a func per method and the calls it saw.
type fakeRuntime struct {
	load       func(ctx context.Context, id string) (Target, error)
	admit      func(ctx context.Context, t Target, requestID string, report *ColdStart) (Admission, error)
	urlHeaders func(ctx context.Context, t Target) (map[string]string, error)
	retire     func(ctx context.Context, id string) error

	mu         sync.Mutex
	loads      int
	admits     []string
	urlLookups int
	retires    int
}

func (f *fakeRuntime) Load(ctx context.Context, id string) (Target, error) {
	f.mu.Lock()
	f.loads++
	f.mu.Unlock()
	if f.load != nil {
		return f.load(ctx, id)
	}
	return Target{InstanceID: id, WorkspaceID: testWS}, nil
}

func (f *fakeRuntime) Admit(ctx context.Context, t Target, requestID string, report *ColdStart) (Admission, error) {
	f.mu.Lock()
	f.admits = append(f.admits, requestID)
	f.mu.Unlock()
	return f.admit(ctx, t, requestID, report)
}

func (f *fakeRuntime) URLHeaders(ctx context.Context, t Target) (map[string]string, error) {
	f.mu.Lock()
	f.urlLookups++
	f.mu.Unlock()
	if f.urlHeaders != nil {
		return f.urlHeaders(ctx, t)
	}
	return map[string]string{}, nil
}

func (f *fakeRuntime) Retire(ctx context.Context, id string) error {
	f.mu.Lock()
	f.retires++
	f.mu.Unlock()
	return f.retire(ctx, id)
}

func (f *fakeRuntime) counts() (loads, admits, urlLookups, retires int) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.loads, len(f.admits), f.urlLookups, f.retires
}

// admitTo admits every request to upstream with lease.
func admitTo(upstream string, lease *fakeLease) func(context.Context, Target, string, *ColdStart) (Admission, error) {
	return func(context.Context, Target, string, *ColdStart) (Admission, error) {
		return Admission{Upstream: upstream, Lease: lease}, nil
	}
}

type startFailure struct {
	reason string
	delay  time.Duration
}

func (e *startFailure) Error() string             { return "start failed: " + e.reason }
func (e *startFailure) FailureReason() string     { return e.reason }
func (e *startFailure) RetryDelay() time.Duration { return e.delay }

type stopped struct{}

func (stopped) Error() string { return "stopped" }
func (stopped) Stopped() bool { return true }

type recordingObserver struct {
	mu          sync.Mutex
	started     []RequestStarted
	completed   []RequestCompleted
	startErr    error
	completeErr error
}

func (o *recordingObserver) Started(_ context.Context, r RequestStarted) error {
	o.mu.Lock()
	defer o.mu.Unlock()
	o.started = append(o.started, r)
	return o.startErr
}

func (o *recordingObserver) Completed(_ context.Context, r RequestCompleted) error {
	o.mu.Lock()
	defer o.mu.Unlock()
	o.completed = append(o.completed, r)
	return o.completeErr
}

func (o *recordingObserver) snapshot() ([]RequestStarted, []RequestCompleted) {
	o.mu.Lock()
	defer o.mu.Unlock()
	return append([]RequestStarted(nil), o.started...), append([]RequestCompleted(nil), o.completed...)
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func testOptions(rt Runtime) Options {
	return Options{
		Runtime: rt, Secret: testSecret, LeaseTTL: time.Minute,
		Workloads: http.DefaultTransport, URLs: http.DefaultTransport,
		Log: slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
}

func newTestGateway(t *testing.T, o Options) *Gateway {
	t.Helper()
	g, err := New(o)
	if err != nil {
		t.Fatal(err)
	}
	return g
}

func mcpRequest(method, body string) *http.Request {
	var r *http.Request
	if body == "" {
		r = httptest.NewRequest(method, "/mcp/"+testInstance+"/mcp", nil)
	} else {
		r = httptest.NewRequest(method, "/mcp/"+testInstance+"/mcp", strings.NewReader(body))
	}
	r.Header.Set(AuthHeader, "Bearer "+testSecret)
	return r
}

func newTestTelemetry(t *testing.T, remote bool) (*Telemetry, *sdkmetric.ManualReader) {
	t.Helper()
	reader := sdkmetric.NewManualReader()
	provider := sdkmetric.NewMeterProvider(sdkmetric.WithReader(reader))
	t.Cleanup(func() { _ = provider.Shutdown(context.Background()) })
	tel, err := NewTelemetry(provider.Meter("test"), remote)
	if err != nil {
		t.Fatal(err)
	}
	return tel, reader
}

func collectMetrics(t *testing.T, reader *sdkmetric.ManualReader) map[string]metricdata.Aggregation {
	t.Helper()
	var data metricdata.ResourceMetrics
	if err := reader.Collect(context.Background(), &data); err != nil {
		t.Fatalf("collect: %v", err)
	}
	metrics := map[string]metricdata.Aggregation{}
	for _, scope := range data.ScopeMetrics {
		for _, m := range scope.Metrics {
			metrics[m.Name] = m.Data
		}
	}
	return metrics
}

func sumWhere(metrics map[string]metricdata.Aggregation, name, key, value string) int64 {
	sum, _ := metrics[name].(metricdata.Sum[int64])
	var total int64
	for _, p := range sum.DataPoints {
		if key == "" {
			total += p.Value
			continue
		}
		if v, ok := p.Attributes.Value(attribute.Key(key)); ok && v.String() == value {
			total += p.Value
		}
	}
	return total
}

func requestCount(metrics map[string]metricdata.Aggregation, status string) int64 {
	return sumWhere(metrics, kobs.MCPGatewayRequests, kobs.AttrStatus, status)
}

func inFlight(metrics map[string]metricdata.Aggregation) int64 {
	return sumWhere(metrics, kobs.MCPGatewayInFlight, "", "")
}
