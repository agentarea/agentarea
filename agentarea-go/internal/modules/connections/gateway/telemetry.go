package gateway

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"sync"
	"time"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/metric"

	kobs "github.com/agentarea/agentarea/agentarea-go/internal/kernel/obs"
)

func knownMCPMethod(m string) bool {
	switch m {
	case "initialize", "ping", "server/discover", "tools/list", "tools/call",
		"resources/list", "resources/read", "resources/templates/list",
		"resources/subscribe", "resources/unsubscribe", "prompts/list", "prompts/get",
		"completion/complete", "logging/setLevel", "notifications/initialized",
		"notifications/cancelled", "notifications/progress", "notifications/roots/list_changed":
		return true
	}
	return false
}

// Telemetry records the gateway's requests and cold starts.
type Telemetry struct {
	plane attribute.KeyValue

	coldStartDuration metric.Float64Histogram
	coldStarts        metric.Int64Counter
	requestDuration   metric.Float64Histogram
	requests          metric.Int64Counter
	inFlight          metric.Int64UpDownCounter
	upstream          metric.Int64Counter

	mu      sync.Mutex
	started map[string]time.Time
}

// NewTelemetry builds the instruments on meter; remote labels the data-plane hop.
func NewTelemetry(meter metric.Meter, remote bool) (*Telemetry, error) {
	plane := "local"
	if remote {
		plane = "remote"
	}
	t := &Telemetry{plane: attribute.String(kobs.AttrPlane, plane), started: make(map[string]time.Time)}
	var errs [7]error
	t.coldStartDuration, errs[0] = meter.Float64Histogram(kobs.MCPColdStartDuration, metric.WithUnit("s"),
		metric.WithDescription("Duration of one phase of an MCP workload cold start."))
	t.coldStarts, errs[1] = meter.Int64Counter(kobs.MCPColdStarts, metric.WithUnit("{start}"),
		metric.WithDescription("MCP workload cold starts, by outcome and failure reason."))
	t.requestDuration, errs[2] = meter.Float64Histogram(kobs.MCPGatewayDuration, metric.WithUnit("s"),
		metric.WithDescription("Duration of a request through the MCP gateway, cold start included."))
	t.requests, errs[3] = meter.Int64Counter(kobs.MCPGatewayRequests, metric.WithUnit("{request}"),
		metric.WithDescription("Requests through the MCP gateway, by status class."))
	t.inFlight, errs[4] = meter.Int64UpDownCounter(kobs.MCPGatewayInFlight, metric.WithUnit("{request}"),
		metric.WithDescription("Requests the MCP gateway is serving now."))
	t.upstream, errs[5] = meter.Int64Counter(kobs.MCPUpstreamResponses, metric.WithUnit("{response}"),
		metric.WithDescription("Responses from MCP workloads, by status class."))
	_, errs[6] = meter.Float64ObservableGauge(kobs.MCPGatewayOldest, metric.WithUnit("s"),
		metric.WithDescription("Age of the oldest request the MCP gateway is serving."),
		metric.WithFloat64Callback(t.observeOldest))
	if err := errors.Join(errs[:]...); err != nil {
		return nil, fmt.Errorf("create MCP gateway instruments: %w", err)
	}
	return t, nil
}

// RecordPhase records one cold-start phase; the runtime records the create phase.
func (t *Telemetry) RecordPhase(ctx context.Context, phase string, outcome ColdStartOutcome, took time.Duration) {
	if t == nil {
		return
	}
	t.coldStartDuration.Record(ctx, took.Seconds(), metric.WithAttributes(
		attribute.String(kobs.AttrPhase, phase), attribute.String(kobs.AttrOutcome, string(outcome)), t.plane))
}

// Started counts a request in flight.
func (t *Telemetry) Started(ctx context.Context, r RequestStarted) error {
	if r.Method != http.MethodGet {
		t.mu.Lock()
		t.started[r.RequestID] = r.StartedAt
		t.mu.Unlock()
	}
	t.inFlight.Add(ctx, 1)
	return nil
}

// Completed records a finished request and its cold start.
func (t *Telemetry) Completed(ctx context.Context, r RequestCompleted) error {
	t.end(ctx, r.RequestID)
	attrs := requestAttributes(r.MCPMethod, gatewayStatus(r.StatusCode, r.Answer, r.Canceled), r.ColdStart != nil)
	t.requests.Add(ctx, 1, attrs)
	t.requestDuration.Record(ctx, r.EndedAt.Sub(r.StartedAt).Seconds(), attrs)
	if r.ColdStart != nil {
		t.recordColdStart(ctx, r.ColdStart)
	}
	return nil
}

func (t *Telemetry) aborted(ctx context.Context, r RequestStarted, cold bool) {
	if t == nil {
		return
	}
	t.end(ctx, r.RequestID)
	t.requests.Add(ctx, 1, requestAttributes(r.MCPMethod, "aborted", cold))
}

func (t *Telemetry) rejected(ctx context.Context, mcpMethod *string, status int) {
	if t != nil {
		t.requests.Add(ctx, 1, requestAttributes(mcpMethod, statusClass(status), false))
	}
}

func (t *Telemetry) end(ctx context.Context, requestID string) {
	t.mu.Lock()
	delete(t.started, requestID)
	t.mu.Unlock()
	t.inFlight.Add(ctx, -1)
}

func (t *Telemetry) upstreamAnswered(ctx context.Context, status int) {
	if t == nil {
		return
	}
	class := "error"
	if status > 0 {
		class = statusClass(status)
	}
	t.upstream.Add(ctx, 1, metric.WithAttributes(attribute.String(kobs.AttrStatus, class)))
}

func (t *Telemetry) recordColdStart(ctx context.Context, start *ColdStart) {
	for _, p := range []struct {
		step string
		took time.Duration
	}{{StepRunning, start.Running}, {StepListening, start.Listening}} {
		if p.took <= 0 {
			continue
		}
		outcome := ColdStartReady
		if start.FailedIn == p.step {
			outcome = start.Outcome
		}
		t.RecordPhase(ctx, p.step, outcome, p.took)
	}
	t.RecordPhase(ctx, "total", start.Outcome, start.Total)
	reason := start.Reason
	if reason == "" {
		reason = "none"
	}
	t.coldStarts.Add(ctx, 1, metric.WithAttributes(
		attribute.String(kobs.AttrOutcome, string(start.Outcome)), attribute.String(kobs.AttrReason, reason), t.plane))
}

func (t *Telemetry) observeOldest(_ context.Context, o metric.Float64Observer) error {
	now := time.Now()
	var oldest time.Duration
	t.mu.Lock()
	for _, at := range t.started {
		oldest = max(oldest, now.Sub(at))
	}
	t.mu.Unlock()
	o.Observe(oldest.Seconds())
	return nil
}

func requestAttributes(mcpMethod *string, status string, cold bool) metric.MeasurementOption {
	return metric.WithAttributes(
		attribute.String(kobs.AttrMCPMethod, mcpMethodName(mcpMethod)),
		attribute.String(kobs.AttrStatus, status),
		attribute.Bool(kobs.AttrCold, cold),
	)
}

func mcpMethodName(h *string) string {
	switch {
	case h == nil:
		return "none"
	case knownMCPMethod(*h):
		return *h
	default:
		return "other"
	}
}

func gatewayStatus(status int, answer Answer, canceled bool) string {
	switch {
	case answer == AnswerStarting:
		return "503_starting"
	case answer == AnswerStartFailed && (status == 502 || status == 503):
		return fmt.Sprintf("%d_start_failed", status)
	case status == 0 && canceled:
		return "canceled"
	case status == 0:
		return "none"
	default:
		return statusClass(status)
	}
}

func statusClass(status int) string {
	if status < 100 || status > 599 {
		return "other"
	}
	return fmt.Sprintf("%dxx", status/100)
}

type requestObservers []RequestObserver

func (o requestObservers) Started(ctx context.Context, r RequestStarted) error {
	for _, obs := range o {
		if err := obs.Started(ctx, r); err != nil {
			return err
		}
	}
	return nil
}

func (o requestObservers) Completed(ctx context.Context, r RequestCompleted) error {
	errs := make([]error, 0, len(o))
	for _, obs := range o {
		errs = append(errs, obs.Completed(ctx, r))
	}
	return errors.Join(errs...)
}
