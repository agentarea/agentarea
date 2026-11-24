package workflows

import (
	"context"
	"strings"
	"sync"
	"testing"

	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/temporal"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

type fakeRunner struct {
	mu    sync.Mutex
	turns []RunnerTurnRequest
	reply func(n int) (RunnerTurnResult, error)
}

func (f *fakeRunner) run(_ context.Context, req RunnerTurnRequest) (RunnerTurnResult, error) {
	f.mu.Lock()
	f.turns = append(f.turns, req)
	n := len(f.turns)
	f.mu.Unlock()
	return f.reply(n)
}

func (f *fakeRunner) deliver(context.Context, DeliverToRunnerRequest) error { return nil }

func runnerRun(t *testing.T, reply func(int) (RunnerTurnResult, error)) (*fakeRun, *fakeRunner, func() error, func(any) error) {
	t.Helper()
	f := newFakeRun()
	f.cfg.Model.ContextWindow = 0
	runner := &fakeRunner{reply: reply}
	env := newEnv(t, f)
	env.RegisterActivityWithOptions(runner.run, activity.RegisterOptions{Name: api.ActivityRunRunnerTurn})
	env.RegisterActivityWithOptions(runner.deliver, activity.RegisterOptions{Name: api.ActivityDeliverToRunner})
	req := request(nil)
	req.WorkflowMetadata = map[string]any{runnerClientKey: "client-1"}
	env.ExecuteWorkflow(AgentExecutionWorkflow, req)
	if !env.IsWorkflowCompleted() {
		t.Fatal("workflow did not complete")
	}
	return f, runner, env.GetWorkflowError, env.GetWorkflowResult
}

func TestRunnerTurnSendsTheGoalAndCompletesWithTheCLIAnswer(t *testing.T) {
	f, runner, werr, get := runnerRun(t, func(int) (RunnerTurnResult, error) {
		return RunnerTurnResult{Status: "completed", Response: "Done on the laptop."}, nil
	})
	if err := werr(); err != nil {
		t.Fatalf("workflow failed: %v", err)
	}
	var res AgentRunResult
	if err := get(&res); err != nil {
		t.Fatal(err)
	}
	if !res.Success || res.FinalResponse != "Done on the laptop." {
		t.Fatalf("result = %+v", res)
	}
	if len(runner.turns) != 1 || runner.turns[0].Message != "Find the answer" || runner.turns[0].TurnKey != "1.1" {
		t.Fatalf("turns = %+v", runner.turns)
	}
	if f.llmCalls[parentTask] != 0 {
		t.Fatal("a run on a runner calls no model of its own")
	}
	contains(t, f.events(parentTask), domain.EventTaskStarted, domain.EventTaskCompleted)
}

func TestRunnerLostTurnIsAssignedAgain(t *testing.T) {
	_, runner, werr, _ := runnerRun(t, func(n int) (RunnerTurnResult, error) {
		if n == 1 {
			return RunnerTurnResult{}, temporal.NewApplicationError("runner went away", runnerLostType)
		}
		return RunnerTurnResult{Status: "completed", Response: "ok"}, nil
	})
	if err := werr(); err != nil {
		t.Fatalf("workflow failed: %v", err)
	}
	if len(runner.turns) != 2 || runner.turns[1].TurnKey != "1.2" || runner.turns[1].Message != "Find the answer" {
		t.Fatalf("turns = %+v", runner.turns)
	}
}

func TestDelegatedAgentOnAClientRunsItsTurnOnTheRunner(t *testing.T) {
	f := newFakeRun()
	f.client = "client-1"
	f.cfg.Tools = append(f.cfg.Tools, api.ToolDefinition{Name: "delegate_to_coder", Parameters: map[string]any{"type": "object"}})
	f.cfg.Delegates = map[string]api.Delegate{"delegate_to_coder": {AgentID: "agent-2", AgentName: "coder"}}
	f.llm[parentTask] = turns(
		calls(ToolCall{ID: "call-1", Name: "delegate_to_coder", Arguments: `{"message": "draw a logo"}`}),
		calls(complete("call-2", "done")),
	)
	runner := &fakeRunner{reply: func(int) (RunnerTurnResult, error) {
		return RunnerTurnResult{Status: "completed", Response: "Drew it."}, nil
	}}
	env := newEnv(t, f)
	env.RegisterActivityWithOptions(runner.run, activity.RegisterOptions{Name: api.ActivityRunRunnerTurn})
	env.RegisterActivityWithOptions(runner.deliver, activity.RegisterOptions{Name: api.ActivityDeliverToRunner})
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))

	if res := result(t, env); !res.Success || res.TotalCost.String() != "0.04" {
		t.Fatalf("result = %+v (the run's own 0.02 and the 0.02 its runner child spent)", res)
	}
	if len(runner.turns) != 1 || runner.turns[0].TaskID != childTask || runner.turns[0].AgentID != "agent-2" || runner.turns[0].Message != "draw a logo" {
		t.Fatalf("runner turns = %+v", runner.turns)
	}
	if f.llmCalls[childTask] != 0 {
		t.Fatalf("the delegated run called the platform model %d times", f.llmCalls[childTask])
	}
	if d := f.eventData(parentTask, domain.EventDelegationCompleted); len(d) != 1 || d[0]["success"] != true || d[0]["child_cost"] != 0.02 {
		t.Fatalf("delegation.completed = %+v", d)
	}
	tools := f.messages(parentTask, "tool")
	if len(tools) == 0 || !strings.Contains(tools[0].Content, "Drew it.") {
		t.Fatalf("tool rows = %+v", tools)
	}
}

func TestRunnerTurnFailureFailsTheRun(t *testing.T) {
	f, _, werr, _ := runnerRun(t, func(int) (RunnerTurnResult, error) {
		return RunnerTurnResult{Status: "failed", Error: "codex crashed"}, nil
	})
	if err := werr(); appErrorType(err) != "RunnerTurnFailed" {
		t.Fatalf("workflow error = %v", err)
	}
	if st := f.lastStatus(parentTask); st.Status != StatusFailed {
		t.Fatalf("final status = %+v", st)
	}
}
