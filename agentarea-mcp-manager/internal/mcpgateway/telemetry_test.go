package mcpgateway

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"go.opentelemetry.io/otel"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"

	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/agentarea/mcp-manager/internal/telemetry"
)

func TestClassifyColdStart(t *testing.T) {
	stopped := &StartupFailureError{reason: "stopped", cause: &workloadStoppedDuringStartupError{status: "exited"}}
	cases := []struct {
		name    string
		step    activationStep
		err     error
		outcome ColdStartOutcome
		reason  string
	}{
		{name: "ready", outcome: ColdStartReady},
		{name: "create failed", step: stepCreate, err: errors.New("quota"), outcome: ColdStartFailed, reason: "create_failed"},
		{name: "deadline while waiting to run", step: stepRunning, err: &StartupFailureError{cause: errStartupDeadline}, outcome: ColdStartTimeout, reason: "not_running"},
		{name: "context expired while waiting to run", step: stepRunning, err: fmt.Errorf("wait: %w", context.DeadlineExceeded), outcome: ColdStartTimeout, reason: "not_running"},
		{name: "inspection failed", step: stepRunning, err: errors.New("api down"), outcome: ColdStartFailed, reason: "inspect_failed"},
		{name: "stopped while running", step: stepRunning, err: stopped, outcome: ColdStartFailed, reason: "stopped"},
		{name: "stopped while listening", step: stepListening, err: errors.Join(stopped, errors.New("cleanup")), outcome: ColdStartFailed, reason: "stopped"},
		{name: "never listened", step: stepListening, err: errors.New("never accepted a connection"), outcome: ColdStartTimeout, reason: "not_listening"},
		{name: "observer refused", step: stepObserver, err: errors.New("ledger"), outcome: ColdStartFailed, reason: "observer_refused"},
		{name: "lease failed", step: stepAdmission, err: errors.New("ownership lost"), outcome: ColdStartFailed, reason: "admission_failed"},
		{name: "unattributed", err: errors.New("?"), outcome: ColdStartFailed, reason: "other"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			outcome, reason := classifyColdStart(tc.step, tc.err)
			if outcome != tc.outcome || reason != tc.reason {
				t.Fatalf("classifyColdStart = %s/%s, want %s/%s", outcome, reason, tc.outcome, tc.reason)
			}
		})
	}
}

func TestGatewayStatus(t *testing.T) {
	cases := []struct {
		status   int
		answer   GatewayAnswer
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

func newTestTelemetry(t *testing.T, states InstanceStates) (*Telemetry, *sdkmetric.ManualReader) {
	t.Helper()
	reader := sdkmetric.NewManualReader()
	provider := sdkmetric.NewMeterProvider(sdkmetric.WithReader(reader))
	t.Cleanup(func() { _ = provider.Shutdown(context.Background()) })
	if states == nil {
		states = func(context.Context) (map[string]int64, error) { return nil, nil }
	}
	tel, err := newTelemetry(provider.Meter("test"), false, states)
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

func requestCount(metrics map[string]metricdata.Aggregation, status string) int64 {
	sum, _ := metrics[telemetry.MCPGatewayRequests].(metricdata.Sum[int64])
	var total int64
	for _, point := range sum.DataPoints {
		if value, _ := point.Attributes.Value(telemetry.AttrStatus); value.AsString() == status {
			total += point.Value
		}
	}
	return total
}

func inFlight(metrics map[string]metricdata.Aggregation) int64 {
	sum, _ := metrics[telemetry.MCPGatewayInFlight].(metricdata.Sum[int64])
	var total int64
	for _, point := range sum.DataPoints {
		total += point.Value
	}
	return total
}

// ReverseProxy aborts a response whose body copy fails by panicking with
// http.ErrAbortHandler; the request must still leave the in-flight gauges.
func TestGatewayEndsTelemetryOfAnAbortedProxy(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Length", "100")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("partial"))
		w.(http.Flusher).Flush()
		conn, _, err := w.(http.Hijacker).Hijack()
		if err != nil {
			t.Errorf("hijack: %v", err)
			return
		}
		_ = conn.Close()
	}))
	defer upstream.Close()

	instanceID := "8ca9f331-9cc9-4a51-9933-27d7bb73860b"
	repository := &gatewayRepositoryStub{instance: &models.MCPServerInstance{InstanceID: instanceID}}
	gateway := testGateway(t, repository, &runtimeStub{endpoint: upstream.URL + "/mcp"})
	tel, reader := newTestTelemetry(t, nil)
	gateway.AttachTelemetry(tel)

	request := httptest.NewRequest(http.MethodPost, "/mcp/"+instanceID+"/mcp", strings.NewReader("{}"))
	request.Header.Set("X-AgentArea-Manager-Authorization", "Bearer "+testGatewaySecret)
	request = request.WithContext(context.WithValue(request.Context(), http.ServerContextKey, &http.Server{}))
	recovered := func() (value any) {
		defer func() { value = recover() }()
		gateway.ServeHTTP(httptest.NewRecorder(), request)
		return nil
	}()

	if recovered != http.ErrAbortHandler {
		t.Fatalf("recovered %v, want http.ErrAbortHandler re-panicked", recovered)
	}
	if len(tel.started) != 0 {
		t.Fatalf("aborted request still tracked: %v", tel.started)
	}
	metrics := collectMetrics(t, reader)
	if got := inFlight(metrics); got != 0 {
		t.Fatalf("in_flight = %d after an aborted request, want 0", got)
	}
	if got := requestCount(metrics, "aborted"); got != 1 {
		t.Fatalf("aborted requests = %d, want 1", got)
	}
}

func TestOldestInFlightIgnoresStandingStreams(t *testing.T) {
	cases := []struct {
		method  string
		tracked bool
	}{
		{method: http.MethodGet, tracked: false},
		{method: http.MethodPost, tracked: true},
		{method: http.MethodDelete, tracked: true},
	}
	for _, tc := range cases {
		t.Run(tc.method, func(t *testing.T) {
			tel, reader := newTestTelemetry(t, nil)
			request := RequestStarted{RequestID: "r", Method: tc.method, StartedAt: time.Now().Add(-time.Hour)}
			if err := tel.Started(context.Background(), request); err != nil {
				t.Fatal(err)
			}
			metrics := collectMetrics(t, reader)
			gauge, _ := metrics[telemetry.MCPGatewayOldest].(metricdata.Gauge[float64])
			if len(gauge.DataPoints) != 1 {
				t.Fatalf("oldest_in_flight points = %d", len(gauge.DataPoints))
			}
			if aged := gauge.DataPoints[0].Value > 0; aged != tc.tracked {
				t.Fatalf("oldest_in_flight = %v, tracked = %v", gauge.DataPoints[0].Value, tc.tracked)
			}
			if got := inFlight(metrics); got != 1 {
				t.Fatalf("in_flight = %d, want 1", got)
			}
		})
	}
}

// A failed instance count must skip its own gauge only: a callback error makes
// the SDK drop the whole collection.
func TestInstancesGaugeSkipsAFailedCount(t *testing.T) {
	var handled []error
	previous := otel.GetErrorHandler()
	otel.SetErrorHandler(otel.ErrorHandlerFunc(func(err error) { handled = append(handled, err) }))
	t.Cleanup(func() { otel.SetErrorHandler(previous) })
	tel, reader := newTestTelemetry(t, func(context.Context) (map[string]int64, error) {
		return nil, errors.New("database is down")
	})
	tel.rejected(context.Background(), nil, http.StatusBadGateway)

	metrics := collectMetrics(t, reader)

	if gauge, _ := metrics[telemetry.MCPInstances].(metricdata.Gauge[int64]); len(gauge.DataPoints) != 0 {
		t.Fatalf("instances observed despite a failed count: %v", gauge.DataPoints)
	}
	if got := requestCount(metrics, "5xx"); got != 1 {
		t.Fatalf("requests{5xx} = %d; the failed count dropped the other metrics", got)
	}
	if len(handled) != 1 || !strings.Contains(handled[0].Error(), "database is down") {
		t.Fatalf("handled errors = %v, want the count failure", handled)
	}
}

func TestGatewayCountsEarlyAnswers(t *testing.T) {
	instanceID := "8ca9f331-9cc9-4a51-9933-27d7bb73860b"
	cases := []struct {
		name    string
		loadErr error
		body    string
		status  int
		class   string
	}{
		{name: "body too large", body: strings.Repeat("x", maxRequestBodyBytes+1), status: http.StatusRequestEntityTooLarge, class: "4xx"},
		{name: "target unavailable", loadErr: errors.New("db down"), body: "{}", status: http.StatusBadGateway, class: "5xx"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			repository := &gatewayRepositoryStub{instance: &models.MCPServerInstance{InstanceID: instanceID}, loadErr: tc.loadErr}
			gateway := testGateway(t, repository, &runtimeStub{})
			tel, reader := newTestTelemetry(t, nil)
			gateway.AttachTelemetry(tel)
			recorder := httptest.NewRecorder()
			request := httptest.NewRequest(http.MethodPost, "/mcp/"+instanceID+"/mcp", strings.NewReader(tc.body))
			request.Header.Set("X-AgentArea-Manager-Authorization", "Bearer "+testGatewaySecret)

			gateway.ServeHTTP(recorder, request)

			if recorder.Code != tc.status {
				t.Fatalf("status = %d, want %d", recorder.Code, tc.status)
			}
			if got := requestCount(collectMetrics(t, reader), tc.class); got != 1 {
				t.Fatalf("requests{%s} = %d, want 1", tc.class, got)
			}
		})
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
			want: []any{slog.Int("rpc_error_code", -32602), slog.String("rpc_error_message", "unknown tool")},
		},
		{
			name: "long json-rpc message",
			body: `{"jsonrpc":"2.0","id":1,"error":{"code":-32000,"message":"` + long + `"}}`,
			want: []any{slog.Int("rpc_error_code", -32000), slog.String("rpc_error_message", long[:refusedLogLimit])},
		},
		{name: "json without an error", body: `{"jsonrpc":"2.0","id":1,"result":{}}`, want: []any{slog.String("body", `{"jsonrpc":"2.0","id":1,"result":{}}`)}},
		{name: "plain text", body: long, want: []any{slog.String("body", long[:refusedLogLimit])}},
		{name: "cut rune", body: strings.Repeat("a", refusedLogLimit-1) + "é", want: []any{slog.String("body", strings.Repeat("a", refusedLogLimit-1))}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := refusalDetail([]byte(tc.body))
			if fmt.Sprint(got) != fmt.Sprint(tc.want) {
				t.Fatalf("refusalDetail = %v, want %v", got, tc.want)
			}
		})
	}
}
