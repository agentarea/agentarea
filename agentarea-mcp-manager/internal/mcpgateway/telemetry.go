package mcpgateway

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"sync"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/metric"

	"github.com/agentarea/mcp-manager/internal/telemetry"
)

// InstanceStates counts runtime instances by lifecycle state.
type InstanceStates func(context.Context) (map[string]int64, error)

// runtimeStates are the lifecycle states the instances gauge reports; a
// state outside them is counted as "other".
var runtimeStates = []string{"starting", "ready", "failed", "reaping", "dormant"}

// mcpMethods are the client-to-server methods the gateway names in metrics.
// The Mcp-Method header is caller-supplied, so anything else is "other".
var mcpMethods = map[string]bool{
	"initialize": true, "ping": true, "server/discover": true,
	"tools/list": true, "tools/call": true,
	"resources/list": true, "resources/read": true, "resources/templates/list": true,
	"resources/subscribe": true, "resources/unsubscribe": true,
	"prompts/list": true, "prompts/get": true,
	"completion/complete": true, "logging/setLevel": true,
	"notifications/initialized": true, "notifications/cancelled": true,
	"notifications/progress": true, "notifications/roots/list_changed": true,
}

// Telemetry records the demand gateway's metrics (ADR-0048 §9). It is the
// core's own RequestObserver and RuntimeObserver: AttachTelemetry composes it
// after the observers an extension installed instead of replacing them.
type Telemetry struct {
	plane attribute.KeyValue

	coldStartDuration metric.Float64Histogram
	coldStarts        metric.Int64Counter
	requestDuration   metric.Float64Histogram
	requests          metric.Int64Counter
	inFlight          metric.Int64UpDownCounter
	idleReaps         metric.Int64Counter
	upstream          metric.Int64Counter

	mu       sync.Mutex
	started  map[string]time.Time
	creating map[string]time.Time
}

// NewTelemetry creates the gateway's instruments on the global meter
// provider. remote reports whether workloads run on a separate data plane.
func NewTelemetry(remote bool, states InstanceStates) (*Telemetry, error) {
	return newTelemetry(telemetry.Meter(), remote, states)
}

func newTelemetry(meter metric.Meter, remote bool, states InstanceStates) (*Telemetry, error) {
	plane := "local"
	if remote {
		plane = "remote"
	}
	t := &Telemetry{
		plane:    telemetry.AttrPlane.String(plane),
		started:  make(map[string]time.Time),
		creating: make(map[string]time.Time),
	}
	var errs [9]error
	t.coldStartDuration, errs[0] = meter.Float64Histogram(telemetry.MCPColdStartDuration, metric.WithUnit("s"),
		metric.WithDescription("Duration of one phase of an MCP workload cold start."))
	t.coldStarts, errs[1] = meter.Int64Counter(telemetry.MCPColdStarts, metric.WithUnit("{start}"),
		metric.WithDescription("MCP workload cold starts, by outcome and failure reason."))
	t.requestDuration, errs[2] = meter.Float64Histogram(telemetry.MCPGatewayDuration, metric.WithUnit("s"),
		metric.WithDescription("Duration of a request through the MCP gateway, cold start included."))
	t.requests, errs[3] = meter.Int64Counter(telemetry.MCPGatewayRequests, metric.WithUnit("{request}"),
		metric.WithDescription("Requests through the MCP gateway, by status class."))
	t.inFlight, errs[4] = meter.Int64UpDownCounter(telemetry.MCPGatewayInFlight, metric.WithUnit("{request}"),
		metric.WithDescription("Requests the MCP gateway is serving now."))
	t.idleReaps, errs[5] = meter.Int64Counter(telemetry.MCPIdleReaps, metric.WithUnit("{instance}"),
		metric.WithDescription("Idle MCP workloads the reaper removed."))
	t.upstream, errs[6] = meter.Int64Counter(telemetry.MCPUpstreamResponses, metric.WithUnit("{response}"),
		metric.WithDescription("Responses from MCP workloads, by status class."))
	_, errs[7] = meter.Float64ObservableGauge(telemetry.MCPGatewayOldest, metric.WithUnit("s"),
		metric.WithDescription("Age of the oldest request the MCP gateway is serving."),
		metric.WithFloat64Callback(t.observeOldest))
	_, errs[8] = meter.Int64ObservableGauge(telemetry.MCPInstances, metric.WithUnit("{instance}"),
		metric.WithDescription("MCP runtime instances, by lifecycle state."),
		metric.WithInt64Callback(observeInstances(states)))
	if err := errors.Join(errs[:]...); err != nil {
		return nil, fmt.Errorf("create MCP gateway instruments: %w", err)
	}
	return t, nil
}

// Started counts the request in flight. A GET is a standing MCP stream that
// lives as long as its session, so only other methods age toward a hang.
func (t *Telemetry) Started(ctx context.Context, request RequestStarted) error {
	if request.Method != http.MethodGet {
		t.mu.Lock()
		t.started[request.RequestID] = request.StartedAt
		t.mu.Unlock()
	}
	t.inFlight.Add(ctx, 1)
	return nil
}

func (t *Telemetry) Completed(ctx context.Context, request RequestCompleted) error {
	t.end(ctx, request.RequestID)
	attrs := requestAttributes(request.MCPMethod,
		gatewayStatus(request.StatusCode, request.Answer, request.Canceled), request.ColdStart != nil)
	t.requests.Add(ctx, 1, attrs)
	t.requestDuration.Record(ctx, request.EndedAt.Sub(request.StartedAt).Seconds(), attrs)
	if request.ColdStart != nil {
		t.recordColdStart(ctx, request.ColdStart)
	}
	return nil
}

// aborted ends a request whose proxy panicked, which reports no completion to
// the request observers.
func (t *Telemetry) aborted(ctx context.Context, request RequestStarted, cold bool) {
	if t == nil {
		return
	}
	t.end(ctx, request.RequestID)
	t.requests.Add(ctx, 1, requestAttributes(request.MCPMethod, "aborted", cold))
}

// rejected counts a request the gateway answered before it was observed.
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

func requestAttributes(mcpMethod *string, status string, cold bool) metric.MeasurementOption {
	return metric.WithAttributes(
		telemetry.AttrMCPMethod.String(mcpMethodName(mcpMethod)),
		telemetry.AttrStatus.String(status),
		telemetry.AttrCold.Bool(cold),
	)
}

func (t *Telemetry) recordColdStart(ctx context.Context, start *ColdStart) {
	for _, phase := range []struct {
		step activationStep
		took time.Duration
	}{{stepRunning, start.Running}, {stepListening, start.Listening}} {
		if phase.took <= 0 {
			continue
		}
		outcome := ColdStartReady
		if start.failedIn == phase.step {
			outcome = start.Outcome
		}
		t.recordPhase(ctx, string(phase.step), outcome, phase.took)
	}
	t.recordPhase(ctx, "total", start.Outcome, start.Total)
	reason := start.Reason
	if reason == "" {
		reason = "none"
	}
	t.coldStarts.Add(ctx, 1, metric.WithAttributes(
		telemetry.AttrOutcome.String(string(start.Outcome)), telemetry.AttrReason.String(reason), t.plane))
}

func (t *Telemetry) recordPhase(ctx context.Context, phase string, outcome ColdStartOutcome, took time.Duration) {
	t.coldStartDuration.Record(ctx, took.Seconds(), metric.WithAttributes(
		telemetry.AttrPhase.String(phase), telemetry.AttrOutcome.String(string(outcome)), t.plane))
}

// Operation times the create phase of a cold start: from the provider's
// creation start to its completion or failure.
func (t *Telemetry) Operation(ctx context.Context, operation RuntimeOperation) error {
	if operation.Operation != OperationCreation {
		return nil
	}
	t.mu.Lock()
	began, seen := t.creating[operation.OperationID]
	if operation.Phase == OperationStarted {
		t.creating[operation.OperationID] = operation.ObservedAt
	} else {
		delete(t.creating, operation.OperationID)
	}
	t.mu.Unlock()
	if operation.Phase == OperationStarted || !seen {
		return nil
	}
	outcome := ColdStartReady
	if operation.Phase == OperationFailed {
		outcome = ColdStartFailed
	}
	t.recordPhase(ctx, string(stepCreate), outcome, operation.ObservedAt.Sub(began))
	return nil
}

func (t *Telemetry) Boundary(context.Context, BoundaryObservation) error { return nil }

func (t *Telemetry) reaped(ctx context.Context) {
	if t != nil {
		t.idleReaps.Add(ctx, 1)
	}
}

// upstreamAnswered counts a workload response; status 0 is a request the
// workload never answered.
func (t *Telemetry) upstreamAnswered(ctx context.Context, status int) {
	if t == nil {
		return
	}
	class := "error"
	if status > 0 {
		class = statusClass(status)
	}
	t.upstream.Add(ctx, 1, metric.WithAttributes(telemetry.AttrStatus.String(class)))
}

func (t *Telemetry) observeOldest(_ context.Context, observer metric.Float64Observer) error {
	now := time.Now()
	var oldest time.Duration
	t.mu.Lock()
	for _, startedAt := range t.started {
		oldest = max(oldest, now.Sub(startedAt))
	}
	t.mu.Unlock()
	observer.Observe(oldest.Seconds())
	return nil
}

func observeInstances(states InstanceStates) metric.Int64Callback {
	return func(ctx context.Context, observer metric.Int64Observer) error {
		ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
		defer cancel()
		counts, err := states(ctx)
		if err != nil {
			// A callback error drops the whole collection, heartbeat included.
			otel.Handle(fmt.Errorf("count MCP runtime instances: %w", err))
			return nil
		}
		var other int64
		for _, count := range counts {
			other += count
		}
		for _, state := range runtimeStates {
			other -= counts[state]
			observer.Observe(counts[state], metric.WithAttributes(telemetry.AttrState.String(state)))
		}
		observer.Observe(other, metric.WithAttributes(telemetry.AttrState.String("other")))
		return nil
	}
}

// mcpMethodName bounds the caller-supplied Mcp-Method header to known
// methods. 2025-era clients send no header at all.
func mcpMethodName(header *string) string {
	switch {
	case header == nil:
		return "none"
	case mcpMethods[*header]:
		return *header
	default:
		return "other"
	}
}

// gatewayStatus is the status class of a gateway response. The gateway's own
// "starting" and start-failure answers are told apart from a workload's 5xx.
func gatewayStatus(status int, answer GatewayAnswer, canceled bool) string {
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

// requestObservers reports to each observer in order. A Started error stops
// the chain: the gateway refuses the request and reports no completion, so a
// later observer must not see a start that never ends.
type requestObservers []RequestObserver

func (o requestObservers) Started(ctx context.Context, request RequestStarted) error {
	for _, observer := range o {
		if err := observer.Started(ctx, request); err != nil {
			return err
		}
	}
	return nil
}

func (o requestObservers) Completed(ctx context.Context, request RequestCompleted) error {
	errs := make([]error, 0, len(o))
	for _, observer := range o {
		errs = append(errs, observer.Completed(ctx, request))
	}
	return errors.Join(errs...)
}

// runtimeObservers reports to each observer in order. Every observer sees
// every fact, except that a refused operation start stops the chain: the
// runtime then abandons the operation and reports no end for it.
type runtimeObservers []RuntimeObserver

func (o runtimeObservers) Operation(ctx context.Context, operation RuntimeOperation) error {
	errs := make([]error, 0, len(o))
	for _, observer := range o {
		err := observer.Operation(ctx, operation)
		if err != nil && operation.Phase == OperationStarted {
			return err
		}
		errs = append(errs, err)
	}
	return errors.Join(errs...)
}

func (o runtimeObservers) Boundary(ctx context.Context, observation BoundaryObservation) error {
	errs := make([]error, 0, len(o))
	for _, observer := range o {
		errs = append(errs, observer.Boundary(ctx, observation))
	}
	return errors.Join(errs...)
}

// AttachTelemetry records the gateway's metrics after the request observer an
// extension attached, if any.
func (g *Gateway) AttachTelemetry(t *Telemetry) {
	g.telemetry = t
	if g.requests == nil {
		g.requests = t
		return
	}
	g.requests = requestObservers{g.requests, t}
}

// AttachTelemetry records cold-start creation after the runtime observer an
// extension attached, if any.
func (r *ProviderRuntime) AttachTelemetry(t *Telemetry) {
	if r.observer == nil {
		r.observer = t
		return
	}
	r.observer = runtimeObservers{r.observer, t}
}
