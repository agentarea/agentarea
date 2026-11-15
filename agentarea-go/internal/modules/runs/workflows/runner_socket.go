package workflows

import (
	"context"

	"go.temporal.io/sdk/activity"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

// RunnerTurnCall is one run_runner_turn_activity as the socket holding the
// client's runner serves it.
type RunnerTurnCall struct {
	Request    RunnerTurnRequest
	WorkflowID string
	// Heartbeat records the activity's heartbeat; a stop reaches ctx through it.
	Heartbeat func()
	// Signal tells the run what the runner reported (runner_turn_update).
	Signal func(ctx context.Context, u RunnerTurnUpdate) error
}

// RunnerTurns runs turns on the runner of one socket.
type RunnerTurns interface {
	RunTurn(ctx context.Context, call RunnerTurnCall) (RunnerTurnResult, error)
}

// RegisterRunnerTurns registers run_runner_turn_activity over turns on the
// worker polling api.RunnerTaskQueue(client); exec signals the runs.
func RegisterRunnerTurns(w durable.Worker, turns RunnerTurns, exec durable.Executor) {
	for _, spec := range ActivitySpecs() {
		if spec.Queue != QueueRunner {
			continue
		}
		w.RegisterActivity(durable.Activity{Name: spec.Name, Kind: spec.Kind, Fn: func(ctx context.Context, req RunnerTurnRequest) (RunnerTurnResult, error) {
			workflowID := activity.GetInfo(ctx).WorkflowExecution.ID
			if workflowID == "" {
				return RunnerTurnResult{}, &durable.ApplicationError{Type: "NoWorkflow", Message: "a runner's turn is run by its task's workflow", NonRetryable: true}
			}
			return turns.RunTurn(ctx, RunnerTurnCall{
				Request:    req,
				WorkflowID: workflowID,
				Heartbeat:  func() { activity.RecordHeartbeat(ctx) },
				Signal: func(sctx context.Context, u RunnerTurnUpdate) error {
					return exec.Signal(sctx, workflowID, api.SignalRunnerTurnUpdate, u)
				},
			})
		}})
	}
}

// RunnerLostType is the error type of a turn whose runner went away; the run assigns it again.
const RunnerLostType = runnerLostType
