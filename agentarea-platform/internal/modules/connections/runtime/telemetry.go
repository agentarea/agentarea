package runtime

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/metric"

	kobs "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/obs"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/gateway"
)

const countTimeout = 5 * time.Second

func runtimeStates() []string { return []string{"starting", "ready", "failed", "reaping", "dormant"} }

func (r *Runtime) instruments() error {
	var errs [2]error
	r.reaps, errs[0] = r.d.Meter.Int64Counter(kobs.MCPIdleReaps, metric.WithUnit("{instance}"),
		metric.WithDescription("Idle MCP workloads the reaper removed."))
	_, errs[1] = r.d.Meter.Int64ObservableGauge(kobs.MCPInstances, metric.WithUnit("{instance}"),
		metric.WithDescription("MCP runtime instances, by lifecycle state."),
		metric.WithInt64Callback(r.observeInstances))
	if err := errors.Join(errs[:]...); err != nil {
		return fmt.Errorf("create MCP runtime instruments: %w", err)
	}
	return nil
}

func (r *Runtime) observeInstances(ctx context.Context, o metric.Int64Observer) error {
	ctx, cancel := context.WithTimeout(ctx, countTimeout)
	defer cancel()
	counts, err := r.countByState(ctx)
	if err != nil {
		otel.Handle(fmt.Errorf("count MCP runtime instances: %w", err))
		return nil
	}
	var other int64
	for _, n := range counts {
		other += n
	}
	for _, s := range runtimeStates() {
		other -= counts[s]
		o.Observe(counts[s], metric.WithAttributes(attribute.String(kobs.AttrState, s)))
	}
	o.Observe(other, metric.WithAttributes(attribute.String(kobs.AttrState, "other")))
	return nil
}

// creationTelemetry records the create phase of a cold start.
type creationTelemetry struct {
	t       *gateway.Telemetry
	mu      sync.Mutex
	started map[string]time.Time
}

func (c *creationTelemetry) Operation(ctx context.Context, op Operation) error {
	if op.Kind != OperationCreation {
		return nil
	}
	c.mu.Lock()
	began, seen := c.started[op.OperationID]
	if op.Phase == OperationStarted {
		c.started[op.OperationID] = op.ObservedAt
	} else {
		delete(c.started, op.OperationID)
	}
	c.mu.Unlock()
	if op.Phase == OperationStarted || !seen {
		return nil
	}
	outcome := gateway.ColdStartReady
	if op.Phase == OperationFailed {
		outcome = gateway.ColdStartFailed
	}
	c.t.RecordPhase(ctx, gateway.StepCreate, outcome, op.ObservedAt.Sub(began))
	return nil
}

func (c *creationTelemetry) Boundary(context.Context, BoundaryObservation) error { return nil }
