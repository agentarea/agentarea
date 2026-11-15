package workflows

import (
	"context"
	"encoding/json"
	"errors"
	modelsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/models/api"
	"io"
	"log/slog"
	"strings"
	"sync"
	"testing"

	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/testsuite"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/service"
)

type recordingWorker struct {
	durable.Worker
	acts []durable.Activity
}

func (w *recordingWorker) RegisterActivity(a durable.Activity) { w.acts = append(w.acts, a) }

func TestRegisterActivitiesRegistersStepsOneToTwelveByTheirSpecs(t *testing.T) {
	w := &recordingWorker{}
	RegisterActivities(w, NewActivities(service.New(service.Deps{}), nil))
	kinds := Kinds()
	want := 0
	for _, s := range ActivitySpecs() {
		if s.Step <= 12 {
			want++
		}
	}
	if len(w.acts) != want {
		t.Fatalf("registered %d activities, want %d", len(w.acts), want)
	}
	for _, a := range w.acts {
		if kinds[a.Name] != a.Kind || a.Fn == nil {
			t.Fatalf("%s registered as %s", a.Name, a.Kind)
		}
	}
}

type models struct{ reply modelsapi.Reply }

func (m models) Call(context.Context, modelsapi.Principal, modelsapi.Call) (modelsapi.Reply, error) {
	return m.reply, nil
}

type tool struct{}

func (tool) Call(context.Context, service.ToolInvocation) (service.ToolOutput, error) {
	return service.ToolOutput{Success: true, Result: "ok", Source: "builtin"}, nil
}

func activityEnv(t *testing.T, a *Activities) *testsuite.TestActivityEnvironment {
	t.Helper()
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestActivityEnvironment()
	for name, fn := range a.byName() {
		env.RegisterActivityWithOptions(fn, activity.RegisterOptions{Name: name})
	}
	return env
}

func newActivities(d service.Deps, exec durable.Executor) *Activities {
	d.Log = slog.New(slog.NewTextHandler(io.Discard, nil))
	if d.Pricing == nil {
		d.Pricing = money.USDAtProviderCost{}
	}
	return NewActivities(service.New(d), exec)
}

func principalFixture() Principal {
	return Principal{WorkspaceID: "8b1f6d36-6a0e-4c43-9c43-1c2d8f0a2b11", UserID: "u1", AgentID: "3f0c1a52-1d7e-4f0a-9a55-6c2e1b7d9e01"}
}

func TestCallLLMActivityReturnsTheReplyAndItsUsage(t *testing.T) {
	limit := 100
	a := newActivities(service.Deps{Models: models{reply: modelsapi.Reply{
		Content: "hi", Usage: modelsapi.Usage{Prompt: 1, Completion: 2, Total: 3}, ProviderCostUSD: money.MustParse("0.5"),
	}}}, nil)
	env := activityEnv(t, a)
	v, err := env.ExecuteActivity(api.ActivityCallLLM, LLMCallRequest{
		Principal: principalFixture(), TaskID: "t1", Model: api.ResolvedModel{ModelID: "m"},
		Messages: []Message{{Role: "user", Content: "hello"}}, Policy: api.Policy{Tokens: &api.TokenPolicy{MaxTokensPerCall: &limit}},
	})
	if err != nil {
		t.Fatal(err)
	}
	var out LLMCallResult
	if err := v.Get(&out); err != nil {
		t.Fatal(err)
	}
	if out.Role != "assistant" || out.Content != "hi" || out.Usage.TotalTokens != 3 || out.Currency != "USD" ||
		out.Cost.String() != "0.5" || out.Usage.Billing == nil || out.Usage.Billing.Settle != "" {
		t.Fatalf("result %+v", out)
	}
}

func TestCallLLMActivityFailsWithThePythonErrorType(t *testing.T) {
	env := activityEnv(t, newActivities(service.Deps{Models: models{}}, nil))
	_, err := env.ExecuteActivity(api.ActivityCallLLM, LLMCallRequest{Principal: principalFixture(), Model: api.ResolvedModel{ModelID: "m"}})
	if err == nil || !strings.Contains(err.Error(), "max_tokens_per_call") {
		t.Fatalf("error %v", err)
	}
}

func TestExecuteToolActivityAnswersADenial(t *testing.T) {
	env := activityEnv(t, newActivities(service.Deps{Tools: map[string]service.ToolCaller{"code": tool{}}}, nil))
	v, err := env.ExecuteActivity(api.ActivityExecuteTool, ToolCallRequest{
		Principal: principalFixture(), TaskID: "t1", ToolCallID: "c1", ToolName: "bash",
		Binding: api.ToolBinding{Source: "code"}, Policy: api.Policy{Tools: &api.ToolsPolicy{Allowed: []string{}}},
	})
	if err != nil {
		t.Fatal(err)
	}
	var out ToolCallResult
	if err := v.Get(&out); err != nil {
		t.Fatal(err)
	}
	if out.Success || out.Error != "tool 'bash' is not permitted by the policy allowlist" {
		t.Fatalf("result %+v", out)
	}
	v, err = env.ExecuteActivity(api.ActivityExecuteTool, ToolCallRequest{
		Principal: principalFixture(), TaskID: "t1", ToolCallID: "c1", ToolName: "bash", Binding: api.ToolBinding{Source: "code"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := v.Get(&out); err != nil || !out.Success || out.Result != "ok" || out.Source != "builtin" || !out.CostMetered {
		t.Fatalf("result %+v %v", out, err)
	}
}

func TestContextActivitiesReportFailureInTheResult(t *testing.T) {
	env := activityEnv(t, newActivities(service.Deps{}, nil))
	v, err := env.ExecuteActivity(api.ActivityStoreContextOutput, StoreOutputRequest{Principal: Principal{}, TaskID: "t1", OutputID: "o", Content: "x"})
	if err != nil {
		t.Fatal(err)
	}
	var out ContextResult
	if err := v.Get(&out); err != nil || out.Success || !strings.Contains(out.Error, "principal is incomplete") {
		t.Fatalf("result %+v %v", out, err)
	}
}

type runner struct{ frames [][]byte }

func (r runner) RunTurn(_ context.Context, _ service.RunnerTurn, onUpdate func([]byte) error) (service.RunnerOutcome, error) {
	for _, f := range r.frames {
		if err := onUpdate(f); err != nil {
			return service.RunnerOutcome{}, err
		}
	}
	return service.RunnerOutcome{Status: "completed", Response: "done"}, nil
}

type signals struct {
	durable.Executor
	mu   sync.Mutex
	sent []any
}

func (s *signals) Signal(_ context.Context, workflowID, signal string, args ...any) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if signal != api.SignalRunnerTurnUpdate || workflowID == "" {
		return errors.New("unexpected signal " + signal)
	}
	s.sent = append(s.sent, args...)
	return nil
}

func TestRunRunnerTurnSignalsEachUpdateToItsRun(t *testing.T) {
	frame, _ := json.Marshal(RunnerTurnUpdate{TurnKey: "k1", Events: []RunnerTurnEvent{{Seq: 1, Kind: "message", Text: "working"}}})
	exec := &signals{}
	env := activityEnv(t, newActivities(service.Deps{Runner: runner{frames: [][]byte{frame}}}, exec))
	v, err := env.ExecuteActivity(api.ActivityRunRunnerTurn, RunnerTurnRequest{TaskID: "t1", TurnKey: "k1", Message: "go"})
	if err != nil {
		t.Fatal(err)
	}
	var out RunnerTurnResult
	if err := v.Get(&out); err != nil || out.Status != "completed" {
		t.Fatalf("result %+v %v", out, err)
	}
	if len(exec.sent) != 1 || exec.sent[0].(RunnerTurnUpdate).Events[0].Text != "working" {
		t.Fatalf("signals %+v", exec.sent)
	}
}
