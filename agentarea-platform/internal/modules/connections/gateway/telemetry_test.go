package gateway

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"testing"
	"time"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"

	kobs "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/obs"
)

func TestClassifyColdStart(t *testing.T) {
	cases := []struct {
		name    string
		step    string
		err     error
		outcome ColdStartOutcome
		reason  string
	}{
		{name: "ready", outcome: ColdStartReady},
		{name: "create failed", step: StepCreate, err: errors.New("quota"), outcome: ColdStartFailed, reason: "create_failed"},
		{name: "deadline while waiting to run", step: StepRunning, err: fmt.Errorf("wait: %w", ErrStartupDeadline), outcome: ColdStartTimeout, reason: "not_running"},
		{name: "context expired while waiting to run", step: StepRunning, err: fmt.Errorf("wait: %w", context.DeadlineExceeded), outcome: ColdStartTimeout, reason: "not_running"},
		{name: "inspection failed", step: StepRunning, err: errors.New("api down"), outcome: ColdStartFailed, reason: "inspect_failed"},
		{name: "stopped while running", step: StepRunning, err: fmt.Errorf("start: %w", stopped{}), outcome: ColdStartFailed, reason: "stopped"},
		{name: "stopped while listening", step: StepListening, err: errors.Join(stopped{}, errors.New("cleanup")), outcome: ColdStartFailed, reason: "stopped"},
		{name: "never listened", step: StepListening, err: errors.New("never accepted a connection"), outcome: ColdStartTimeout, reason: "not_listening"},
		{name: "observer refused", step: StepObserver, err: errors.New("ledger"), outcome: ColdStartFailed, reason: "observer_refused"},
		{name: "lease failed", step: StepAdmission, err: errors.New("ownership lost"), outcome: ColdStartFailed, reason: "admission_failed"},
		{name: "unattributed", err: errors.New("?"), outcome: ColdStartFailed, reason: "other"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if outcome, reason := classify(tc.step, tc.err); outcome != tc.outcome || reason != tc.reason {
				t.Fatalf("classify = %s/%s, want %s/%s", outcome, reason, tc.outcome, tc.reason)
			}
		})
	}
}

func TestSettleReportsOnlyAnActivation(t *testing.T) {
	var none *ColdStart
	if none.Settle(errors.New("x")) != nil {
		t.Fatal("a nil report settled")
	}
	idle := &ColdStart{}
	idle.Phase(StepRunning, time.Now(), nil)
	if idle.Settle(nil) != nil {
		t.Fatal("a request that activated nothing reported a cold start")
	}
	c := &ColdStart{}
	c.Begin()
	c.Phase(StepListening, time.Now(), errors.New("refused"))
	if got := c.Settle(errors.New("refused")); got == nil || got.Outcome != ColdStartTimeout || got.Reason != "not_listening" {
		t.Fatalf("settled %+v", got)
	}
}

func TestGatewayStatus(t *testing.T) {
	cases := []struct {
		status   int
		answer   Answer
		canceled bool
		want     string
	}{
		{status: 200, want: "2xx"},
		{status: 400, want: "4xx"},
		{status: 503, want: "5xx"},
		{status: 503, answer: AnswerStarting, want: "503_starting"},
		{status: 503, answer: AnswerStartFailed, want: "503_start_failed"},
		{status: 502, answer: AnswerStartFailed, want: "502_start_failed"},
		{status: 0, canceled: true, want: "canceled"},
		{status: 0, want: "none"},
		{status: 999, want: "other"},
	}
	for _, tc := range cases {
		if got := gatewayStatus(tc.status, tc.answer, tc.canceled); got != tc.want {
			t.Fatalf("gatewayStatus(%d, %q, %v) = %q, want %q", tc.status, tc.answer, tc.canceled, got, tc.want)
		}
	}
}

func TestMCPMethodName(t *testing.T) {
	value := func(s string) *string { return &s }
	cases := []struct {
		header *string
		want   string
	}{
		{header: nil, want: "none"},
		{header: value("tools/call"), want: "tools/call"},
		{header: value("server/discover"), want: "server/discover"},
		{header: value("tools/call?x=1"), want: "other"},
		{header: value(""), want: "other"},
	}
	for _, tc := range cases {
		if got := mcpMethodName(tc.header); got != tc.want {
			t.Fatalf("mcpMethodName = %q, want %q", got, tc.want)
		}
	}
}

func TestHeaderSafeAndRetryAfter(t *testing.T) {
	if got := headerSafe("ok\r\nX-Injected: 1\tcafé"); got != "ok??X-Injected: 1?caf??" {
		t.Fatalf("headerSafe = %q", got)
	}
	for d, want := range map[time.Duration]int{0: 1, time.Millisecond: 1, time.Second: 1, 1001 * time.Millisecond: 2, 30 * time.Second: 30} {
		if got := retryAfterSeconds(d); got != want {
			t.Errorf("retryAfterSeconds(%s) = %d, want %d", d, got, want)
		}
	}
}

func TestOldestInFlightIgnoresStandingStreams(t *testing.T) {
	for method, tracked := range map[string]bool{http.MethodGet: false, http.MethodPost: true, http.MethodDelete: true} {
		t.Run(method, func(t *testing.T) {
			tel, reader := newTestTelemetry(t, false)
			if err := tel.Started(context.Background(), RequestStarted{RequestID: "r", Method: method, StartedAt: time.Now().Add(-time.Hour)}); err != nil {
				t.Fatal(err)
			}
			metrics := collectMetrics(t, reader)
			gauge, _ := metrics[kobs.MCPGatewayOldest].(metricdata.Gauge[float64])
			if len(gauge.DataPoints) != 1 {
				t.Fatalf("oldest_in_flight points = %d", len(gauge.DataPoints))
			}
			if aged := gauge.DataPoints[0].Value > 0; aged != tracked {
				t.Fatalf("oldest_in_flight = %v, tracked = %v", gauge.DataPoints[0].Value, tracked)
			}
			if got := inFlight(metrics); got != 1 {
				t.Fatalf("in_flight = %d", got)
			}
		})
	}
}

func phasePoints(metrics map[string]metricdata.Aggregation) []string {
	h, _ := metrics[kobs.MCPColdStartDuration].(metricdata.Histogram[float64])
	var out []string
	for _, p := range h.DataPoints {
		phase, _ := p.Attributes.Value(attribute.Key(kobs.AttrPhase))
		outcome, _ := p.Attributes.Value(attribute.Key(kobs.AttrOutcome))
		plane, _ := p.Attributes.Value(attribute.Key(kobs.AttrPlane))
		out = append(out, fmt.Sprintf("%s/%s/%s", phase.AsString(), outcome.AsString(), plane.AsString()))
	}
	slices.Sort(out)
	return out
}

func TestTelemetryRecordsAColdStartByPhase(t *testing.T) {
	tel, reader := newTestTelemetry(t, true)
	cs := &ColdStart{Outcome: ColdStartTimeout, Reason: "not_listening", Running: time.Second, Listening: 3 * time.Second, Total: 5 * time.Second, FailedIn: StepListening}
	ctx := context.Background()
	started := RequestStarted{RequestID: "r", Method: http.MethodPost, StartedAt: time.Now()}
	_ = tel.Started(ctx, started)
	_ = tel.Completed(ctx, RequestCompleted{RequestStarted: started, EndedAt: time.Now(), StatusCode: 503, Answer: AnswerStartFailed, ColdStart: cs})
	tel.RecordPhase(ctx, StepCreate, ColdStartReady, time.Second)

	metrics := collectMetrics(t, reader)
	want := []string{"create/ready/remote", "listening/timeout/remote", "running/ready/remote", "total/timeout/remote"}
	if got := phasePoints(metrics); !slices.Equal(got, want) {
		t.Fatalf("phases %v, want %v", got, want)
	}
	if got := sumWhere(metrics, kobs.MCPColdStarts, kobs.AttrReason, "not_listening"); got != 1 {
		t.Fatalf("cold_starts{not_listening} = %d", got)
	}
	if got := requestCount(metrics, "503_start_failed"); got != 1 {
		t.Fatalf("requests{503_start_failed} = %d", got)
	}
	if got := sumWhere(metrics, kobs.MCPGatewayRequests, kobs.AttrCold, "true"); got != 1 {
		t.Fatalf("requests{cold} = %d", got)
	}
	if got := inFlight(metrics); got != 0 {
		t.Fatalf("in_flight = %d", got)
	}
}

func TestGatewayCountsRequestsAndUpstreamAnswers(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusNotFound) }))
	defer upstream.Close()
	tel, reader := newTestTelemetry(t, false)
	o := testOptions(&fakeRuntime{admit: admitTo(upstream.URL+"/mcp", &fakeLease{})})
	o.Telemetry = tel
	g := newTestGateway(t, o)
	req := mcpRequest(http.MethodPost, "{}")
	req.Header.Set("Mcp-Method", "tools/list")
	g.ServeHTTP(httptest.NewRecorder(), req)
	metrics := collectMetrics(t, reader)
	if got := sumWhere(metrics, kobs.MCPGatewayRequests, kobs.AttrMCPMethod, "tools/list"); got != 1 {
		t.Fatalf("requests{tools/list} = %d", got)
	}
	if got := sumWhere(metrics, kobs.MCPUpstreamResponses, kobs.AttrStatus, "4xx"); got != 1 {
		t.Fatalf("upstream{4xx} = %d", got)
	}
	if got := inFlight(metrics); got != 0 {
		t.Fatalf("in_flight = %d", got)
	}
}

func TestRefusalDetail(t *testing.T) {
	long := strings.Repeat("a", 300)
	cases := []struct {
		name string
		body string
		want []any
	}{
		{
			name: "json-rpc error",
			body: `{"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"unknown tool","data":{"token":"secret"}}}`,
			want: []any{"rpc_error_code", -32602, "rpc_error_message", "unknown tool"},
		},
		{
			name: "long json-rpc message",
			body: `{"jsonrpc":"2.0","id":1,"error":{"code":-32000,"message":"` + long + `"}}`,
			want: []any{"rpc_error_code", -32000, "rpc_error_message", long[:refusalLogLimit]},
		},
		{name: "json without an error", body: `{"jsonrpc":"2.0","id":1,"result":{}}`, want: []any{"body", `{"jsonrpc":"2.0","id":1,"result":{}}`}},
		{name: "plain text", body: long, want: []any{"body", long[:refusalLogLimit]}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := refusalDetail([]byte(tc.body)); !slices.Equal(got, tc.want) {
				t.Fatalf("refusalDetail = %v, want %v", got, tc.want)
			}
		})
	}
}
