package service

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/metric"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	kobs "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/obs"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

// Tool kinds, paths and outcomes the tool-call instruments count (telemetry.py ToolKind,
// ToolPath, ToolOutcome).
const (
	toolKindMCP        = "mcp"
	toolKindBuiltin    = "builtin"
	toolKindOpenAPI    = "openapi"
	toolKindPlatform   = "platform"
	toolKindDelegation = "delegation"
	toolKindSkill      = "skill"

	toolPathWorker = "worker"

	toolOutcomeOK             = "ok"
	toolOutcomeToolError      = "tool_error"
	toolOutcomeTransportError = "transport_error"
	toolOutcomeTimeout        = "timeout"
	toolOutcomeDenied         = "denied"
	toolOutcomeHeld           = "held"
	toolOutcomeCancelled      = "cancelled"
)

// ToolTelemetry records agentarea.tool.calls, agentarea.tool.call.duration,
// agentarea.tool.in_flight and agentarea.tool.oldest_in_flight.
type ToolTelemetry struct {
	calls    metric.Int64Counter
	duration metric.Float64Histogram
	inFlight metric.Int64UpDownCounter
	now      func() time.Time

	mu      sync.Mutex
	started map[*toolCall]struct{}
	seen    map[toolKey]struct{}
}

type toolKey struct{ kind, path string }

// NewToolTelemetry builds the tool-call instruments on meter.
func NewToolTelemetry(meter metric.Meter) (*ToolTelemetry, error) {
	t := &ToolTelemetry{now: time.Now, started: map[*toolCall]struct{}{}, seen: map[toolKey]struct{}{}}
	var errs [4]error
	t.calls, errs[0] = meter.Int64Counter(kobs.ToolCalls, metric.WithUnit("{call}"),
		metric.WithDescription("Tool calls, by kind, path and outcome."))
	t.duration, errs[1] = meter.Float64Histogram(kobs.ToolCallDuration, metric.WithUnit("s"),
		metric.WithDescription("Tool call duration."))
	t.inFlight, errs[2] = meter.Int64UpDownCounter(kobs.ToolInFlight, metric.WithUnit("{call}"),
		metric.WithDescription("Tool calls in progress."))
	_, errs[3] = meter.Float64ObservableGauge(kobs.ToolOldestInFlight, metric.WithUnit("s"),
		metric.WithDescription("Age of the oldest tool call in progress in this process."),
		metric.WithFloat64Callback(t.observeOldest))
	if err := errors.Join(errs[:]...); err != nil {
		return nil, fmt.Errorf("create tool call instruments: %w", err)
	}
	return t, nil
}

// toolCall is one call being metered; its outcome is the first one set.
type toolCall struct {
	t       *ToolTelemetry
	key     toolKey
	at      time.Time
	outcome string
}

func (t *ToolTelemetry) begin(ctx context.Context, kind, path string) *toolCall {
	if t == nil {
		return nil
	}
	c := &toolCall{t: t, key: toolKey{kind, path}, at: t.now()}
	t.mu.Lock()
	t.started[c] = struct{}{}
	t.seen[c.key] = struct{}{}
	t.mu.Unlock()
	t.inFlight.Add(ctx, 1, metric.WithAttributes(c.key.attributes()...))
	return c
}

func (c *toolCall) set(outcome string) {
	if c != nil && c.outcome == "" {
		c.outcome = outcome
	}
}

// failed: the call raised and was answered as a failure instead.
func (c *toolCall) failed(err error) { c.set(toolFailureOutcome(err)) }

func (c *toolCall) answered(success bool) {
	if success {
		c.set(toolOutcomeOK)
	} else {
		c.set(toolOutcomeToolError)
	}
}

// end records the call; err is what the call raised, if it set no outcome.
func (c *toolCall) end(ctx context.Context, err error) {
	if c == nil {
		return
	}
	if err != nil {
		c.failed(err)
	}
	c.set(toolOutcomeOK)
	t := c.t
	t.mu.Lock()
	delete(t.started, c)
	t.mu.Unlock()
	t.inFlight.Add(ctx, -1, metric.WithAttributes(c.key.attributes()...))
	outcome := metric.WithAttributes(append(c.key.attributes(), attribute.String(kobs.AttrOutcome, c.outcome))...)
	t.calls.Add(ctx, 1, outcome)
	t.duration.Record(ctx, t.now().Sub(c.at).Seconds(), outcome)
}

func (k toolKey) attributes() []attribute.KeyValue {
	return []attribute.KeyValue{attribute.String(kobs.AttrToolKind, k.kind), attribute.String(kobs.AttrPath, k.path)}
}

// observeOldest reports the oldest call per kind and path; 0 for one seen with none in progress.
func (t *ToolTelemetry) observeOldest(_ context.Context, o metric.Float64Observer) error {
	now := t.now()
	t.mu.Lock()
	ages := make(map[toolKey]time.Duration, len(t.seen))
	for k := range t.seen {
		ages[k] = 0
	}
	for c := range t.started {
		ages[c.key] = max(ages[c.key], now.Sub(c.at))
	}
	t.mu.Unlock()
	for k, age := range ages {
		o.Observe(age.Seconds(), metric.WithAttributes(k.attributes()...))
	}
	return nil
}

// toolFailureOutcome is the outcome of a call that raised instead of answering.
func toolFailureOutcome(err error) string {
	timeout, isTimeout := errors.AsType[interface {
		error
		Timeout() bool
	}](err)
	switch {
	case errors.Is(err, context.Canceled):
		return toolOutcomeCancelled
	case errors.Is(err, context.DeadlineExceeded), isTimeout && timeout.Timeout():
		return toolOutcomeTimeout
	}
	return toolOutcomeTransportError
}

// toolKind is the kind of tool a binding runs, as dispatch picks its caller.
func toolKind(b api.ToolBinding) string {
	switch b.Source {
	case "mcp":
		return toolKindMCP
	case "openapi":
		return toolKindOpenAPI
	case "remote_agent":
		return toolKindDelegation
	case "code":
		if b.Code == nil {
			return toolKindBuiltin
		}
		switch b.Code.Namespace {
		case shellToolset, filesToolset, webToolset, contextToolset, mediaToolset:
			return toolKindBuiltin
		}
		return toolKindPlatform
	}
	return toolKindBuiltin
}

// skillOutcome: a refused skill is denied, an unreachable service a transport failure,
// any other failure the tool's error.
func skillOutcome(err error) string {
	app, isApp := errors.AsType[*durable.ApplicationError](err)
	switch {
	case err == nil:
		return toolOutcomeOK
	case isApp && app.Type == "SkillActivationRefused":
		return toolOutcomeDenied
	case isApp && app.Type == "ServiceUnreachable":
		return toolFailureOutcome(app.Cause)
	case !isApp && (errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded)):
		return toolFailureOutcome(err)
	}
	return toolOutcomeToolError
}
