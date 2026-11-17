package app

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/metric"

	"github.com/agentarea/agentarea/agentarea-platform/ext"
	kdurable "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	kobs "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/obs"
	runsservice "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/service"
)

// entitlementGate asks the build's entitlement guard before a model call, as
// the governance pipeline runs it at PRE_LLM_CALL (temporal_bridge.py): the
// action is the call's model id, and Model says whose credentials pay.
type entitlementGate struct{ g ext.EntitlementGuard }

func (e entitlementGate) CheckLLMCall(ctx context.Context, c runsservice.LLMGateCall) (runsservice.GateResult, error) {
	ic := ext.InterceptorContext{
		AgentID: c.AgentID, WorkspaceID: c.WorkspaceID, UserID: c.UserID, Phase: ext.PhasePreLLMCall,
		ActionType: "llm_call", ActionName: c.ModelID, ExecutionState: c.ExecutionState,
	}
	if c.ModelID != "" {
		ic.Model = &ext.CallModel{ModelID: c.ModelID, ModelName: c.ModelName, ManagedBy: c.ManagedBy}
	}
	r, err := e.g.Execute(ctx, ic)
	if err != nil {
		return runsservice.GateResult{}, err
	}
	return runsservice.GateResult{Action: string(r.Action), InterceptorName: r.InterceptorName, Reason: r.Reason, Metadata: r.Metadata}, nil
}

// runTelemetry is agentarea.run.transitions and agentarea.run.duration
// (telemetry.py record_run_transition).
type runTelemetry struct {
	transitions metric.Int64Counter
	duration    metric.Float64Histogram
}

func newRunTelemetry() (runTelemetry, error) {
	m := otel.Meter(kobs.MeterScope)
	transitions, err := m.Int64Counter(kobs.RunTransitions, metric.WithUnit("{transition}"),
		metric.WithDescription("Task status updates, by the status set and why a run stopped."))
	if err != nil {
		return runTelemetry{}, err
	}
	duration, err := m.Float64Histogram(kobs.RunDuration, metric.WithUnit("s"),
		metric.WithDescription("Time from a run's start to a terminal status."))
	return runTelemetry{transitions: transitions, duration: duration}, err
}

func (t runTelemetry) RunTransition(status, failureReason string, elapsed *time.Duration) {
	ctx := context.Background()
	t.transitions.Add(ctx, 1, metric.WithAttributes(attribute.String(kobs.AttrStatus, status), attribute.String(kobs.AttrFailureReason, failureReason)))
	if elapsed != nil {
		t.duration.Record(ctx, elapsed.Seconds(), metric.WithAttributes(attribute.String(kobs.AttrStatus, status)))
	}
}

// registered refuses a worker missing an activity its workflows schedule
// (validate_activity_mapping).
func registered(w kdurable.Worker, want []string) error {
	kinds := w.Kinds()
	var missing []string
	for _, name := range want {
		if _, ok := kinds[name]; !ok {
			missing = append(missing, name)
		}
	}
	if len(missing) > 0 {
		slices.Sort(missing)
		return fmt.Errorf("activities not registered: %s", strings.Join(missing, ", "))
	}
	return nil
}
