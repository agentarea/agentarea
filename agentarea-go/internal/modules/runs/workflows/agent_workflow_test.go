package workflows

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"

	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/workflow"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/domain"
)

const (
	parentTask = "11111111-1111-1111-1111-111111111111"
	childTask  = "22222222-2222-2222-2222-222222222222"
)

type llmScript func(req LLMCallRequest, attempt int32) (LLMCallResult, error)

type fakeRun struct {
	mu        sync.Mutex
	cfg       api.RunConfig
	rows      map[string][]LogRow
	live      map[string][]string
	statuses  map[string][]TaskStatus
	llm       map[string]llmScript
	llmCalls  map[string]int
	toolCalls []ToolCallRequest
	tool      func(ToolCallRequest) (ToolCallResult, error)
	created   []CreateDelegationTaskRequest
}

func newFakeRun() *fakeRun {
	return &fakeRun{
		cfg: testConfig(), rows: map[string][]LogRow{}, live: map[string][]string{}, statuses: map[string][]TaskStatus{},
		llm: map[string]llmScript{}, llmCalls: map[string]int{},
		tool: func(ToolCallRequest) (ToolCallResult, error) {
			return ToolCallResult{Success: true, Result: "found it", Source: "mcp"}, nil
		},
	}
}

func intp(v int) *int { return &v }

func testPolicy() api.Policy {
	return api.Policy{
		Budget:    &api.BudgetPolicy{RunBudget: ptr(money.MustParse("10"))},
		Tokens:    &api.TokenPolicy{MaxTokens: intp(1_000_000)},
		Execution: &api.ExecutionPolicy{MaxModelTurns: intp(6), MaxToolCallsPerTurn: intp(5), MaxToolCallsTotal: intp(20)},
	}
}

func testConfig() api.RunConfig {
	return api.RunConfig{
		Agent:    api.AgentSpec{ID: "agent-1", Name: "Researcher", Instruction: "Be useful.", ModelID: "model-1"},
		Model:    api.ResolvedModel{ModelID: "model-1", ModelName: "test-model", ContextWindow: 100_000},
		Tools:    []api.ToolDefinition{{Name: "search", Description: "Search", Parameters: map[string]any{"type": "object"}}},
		Bindings: map[string]api.ToolBinding{"search": {Source: "mcp", MCP: &api.MCPBinding{InstanceID: "mcp-1", RawName: "search"}}},
	}
}

func (f *fakeRun) resolve(_ context.Context, _ ResolveRunConfigRequest) (api.RunConfig, error) {
	return f.cfg, nil
}

func (f *fakeRun) record(_ context.Context, req RecordRequest) (RecordResult, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.rows[req.TaskID] = append(f.rows[req.TaskID], req.Rows...)
	for _, e := range req.Live {
		f.live[req.TaskID] = append(f.live[req.TaskID], e.Type)
	}
	if req.Status != nil {
		f.statuses[req.TaskID] = append(f.statuses[req.TaskID], *req.Status)
	}
	return RecordResult{Rows: len(req.Rows)}, nil
}

func (f *fakeRun) callLLM(ctx context.Context, req LLMCallRequest) (LLMCallResult, error) {
	f.mu.Lock()
	f.llmCalls[req.TaskID]++
	n := f.llmCalls[req.TaskID]
	script := f.llm[req.TaskID]
	f.mu.Unlock()
	if script == nil {
		return LLMCallResult{}, errors.New("no model script for task " + req.TaskID)
	}
	res, err := script(req, activity.GetInfo(ctx).Attempt)
	if err == nil && res.Usage.TotalTokens == 0 {
		res.Usage = LLMUsage{PromptTokens: 100 * int64(n), CompletionTokens: 10, TotalTokens: 100*int64(n) + 10}
		res.Cost = money.MustParse("0.01")
		res.Currency = "USD"
	}
	return res, err
}

func (f *fakeRun) executeTool(_ context.Context, req ToolCallRequest) (ToolCallResult, error) {
	f.mu.Lock()
	f.toolCalls = append(f.toolCalls, req)
	f.mu.Unlock()
	return f.tool(req)
}

func (f *fakeRun) validate(_ context.Context, req ArtifactValidationRequest) (ArtifactValidationResult, error) {
	ev := make([]ArtifactEvidence, 0, len(req.DeclaredPaths))
	for _, p := range req.DeclaredPaths {
		ev = append(ev, ArtifactEvidence{Path: p, Validator: "exists"})
	}
	return ArtifactValidationResult{State: "passed", Generation: 1, Evidence: ev}, nil
}

func (f *fakeRun) spendCap(_ context.Context, _ MonthlySpendCapRequest) (MonthlySpendCapResult, error) {
	return MonthlySpendCapResult{}, nil
}

func (f *fakeRun) compact(_ context.Context, _ CompactMessagesRequest) (CompactMessagesResult, error) {
	return CompactMessagesResult{}, nil
}

func (f *fakeRun) createDelegation(_ context.Context, req CreateDelegationTaskRequest) (CreateDelegationTaskResult, error) {
	f.mu.Lock()
	f.created = append(f.created, req)
	f.mu.Unlock()
	return CreateDelegationTaskResult{Status: "created", TaskID: childTask, Policy: testPolicy()}, nil
}

func (f *fakeRun) delegatedSpend(_ context.Context, _ DelegatedSpendRequest) (DelegatedSpendResult, error) {
	return DelegatedSpendResult{Spent: money.MustParse("0.02")}, nil
}

func (f *fakeRun) updateSnapshot(_ context.Context, _ UpdateGovernanceSnapshotRequest) error {
	return nil
}

func (f *fakeRun) events(task string) []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	var out []string
	for _, r := range f.rows[task] {
		if r.Kind == "event" {
			out = append(out, r.Name)
		}
	}
	return out
}

func (f *fakeRun) eventData(task, typ string) []map[string]any {
	f.mu.Lock()
	defer f.mu.Unlock()
	var out []map[string]any
	for _, r := range f.rows[task] {
		if r.Kind == "event" && r.Name == typ {
			out = append(out, r.Meta)
		}
	}
	return out
}

func (f *fakeRun) messages(task, role string) []LogRow {
	f.mu.Lock()
	defer f.mu.Unlock()
	var out []LogRow
	for _, r := range f.rows[task] {
		if r.Kind != "event" && r.Role == role {
			out = append(out, r)
		}
	}
	return out
}

func (f *fakeRun) lastStatus(task string) TaskStatus {
	f.mu.Lock()
	defer f.mu.Unlock()
	s := f.statuses[task]
	if len(s) == 0 {
		return TaskStatus{}
	}
	return s[len(s)-1]
}

func newEnv(t *testing.T, f *fakeRun) *testsuite.TestWorkflowEnvironment {
	t.Helper()
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	env.RegisterWorkflowWithOptions(AgentExecutionWorkflow, workflow.RegisterOptions{Name: api.WorkflowAgentExecution})
	for name, fn := range map[string]any{
		api.ActivityResolveRunConfig: f.resolve, api.ActivityRecord: f.record, api.ActivityCallLLM: f.callLLM,
		api.ActivityExecuteTool: f.executeTool, api.ActivityValidateArtifacts: f.validate,
		api.ActivityCheckMonthlySpendCap: f.spendCap, api.ActivityCompactMessages: f.compact,
		api.ActivityCreateDelegationTask: f.createDelegation, api.ActivityDelegatedTaskSpend: f.delegatedSpend,
		api.ActivityUpdateGovernanceSnapshot: f.updateSnapshot,
	} {
		env.RegisterActivityWithOptions(fn, activity.RegisterOptions{Name: name})
	}
	return env
}

func request(params map[string]any) AgentRunRequest {
	if params == nil {
		params = map[string]any{"session": map[string]any{"continue": false}}
	}
	return AgentRunRequest{
		TaskID: parentTask, AgentID: "agent-1", UserID: "user-1", WorkspaceID: "ws-1", TaskQuery: "Find the answer",
		TaskParameters: params, Policy: testPolicy(), WorkflowMetadata: map[string]any{},
	}
}

func text(s string) LLMCallResult {
	return LLMCallResult{Role: "assistant", Content: s, FinishReason: "stop"}
}

func calls(cs ...ToolCall) LLMCallResult {
	return LLMCallResult{Role: "assistant", ToolCalls: cs, FinishReason: "tool_calls"}
}

func turns(replies ...LLMCallResult) llmScript {
	var mu sync.Mutex
	i := 0
	return func(LLMCallRequest, int32) (LLMCallResult, error) {
		mu.Lock()
		defer mu.Unlock()
		if i >= len(replies) {
			return text("out of script"), nil
		}
		r := replies[i]
		i++
		return r, nil
	}
}

func complete(id, result string) ToolCall {
	return ToolCall{ID: id, Name: domain.ToolCompletion, Arguments: `{"result": "` + result + `"}`}
}

func result(t *testing.T, env *testsuite.TestWorkflowEnvironment) AgentRunResult {
	t.Helper()
	if !env.IsWorkflowCompleted() {
		t.Fatal("workflow did not complete")
	}
	if err := env.GetWorkflowError(); err != nil {
		t.Fatalf("workflow failed: %v", err)
	}
	var res AgentRunResult
	if err := env.GetWorkflowResult(&res); err != nil {
		t.Fatal(err)
	}
	return res
}

func contains(t *testing.T, got []string, want ...string) {
	t.Helper()
	at := 0
	for _, g := range got {
		if at < len(want) && g == want[at] {
			at++
		}
	}
	if at < len(want) {
		t.Fatalf("events %v do not contain %v in order (missing %q)", got, want, want[at])
	}
}

func TestHappyRunCompletesFromATextReply(t *testing.T) {
	f := newFakeRun()
	f.llm[parentTask] = turns(text("The answer is 42."))
	env := newEnv(t, f)
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))

	res := result(t, env)
	if !res.Success || res.Status != StatusCompleted || res.FinalResponse != "The answer is 42." {
		t.Fatalf("result = %+v", res)
	}
	contains(t, f.events(parentTask), domain.EventTaskStarted, domain.EventRuntimeDiscovered, domain.EventTurnStarted,
		domain.EventLLMCompleted, domain.EventArtifactValidationStarted, domain.EventArtifactValidationDone,
		domain.EventTurnCompleted, domain.EventTaskCompleted, domain.EventExecutionFinished)
	if live := f.live[parentTask]; len(live) == 0 || live[0] != domain.EventLLMStarted {
		t.Fatalf("live events = %v, want llm.call.started first", live)
	}
	if st := f.lastStatus(parentTask); st.Status != StatusCompleted || st.Response != "The answer is 42." || st.Resume == nil {
		t.Fatalf("final status = %+v", st)
	}
	sys := f.messages(parentTask, "system")
	if len(sys) != 1 || !strings.Contains(sys[0].Content, "Researcher") {
		t.Fatalf("system rows = %+v", sys)
	}
	if res.TotalCost.String() != "0.01" {
		t.Fatalf("total cost = %s", res.TotalCost)
	}
}

func TestToolCallRunsThroughTheToolActivity(t *testing.T) {
	f := newFakeRun()
	f.llm[parentTask] = turns(
		calls(ToolCall{ID: "call-1", Name: "search", Arguments: `{"q": "x"}`}),
		calls(complete("call-2", "done")),
	)
	env := newEnv(t, f)
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))

	res := result(t, env)
	if !res.Success || res.FinalResponse != "done" || res.TotalToolCalls != 1 {
		t.Fatalf("result = %+v", res)
	}
	if len(f.toolCalls) != 1 || f.toolCalls[0].Args["q"] != "x" || f.toolCalls[0].Binding.MCP == nil {
		t.Fatalf("tool calls = %+v", f.toolCalls)
	}
	contains(t, f.events(parentTask), domain.EventToolCall, domain.EventToolResult, domain.EventTaskCompleted)
	tools := f.messages(parentTask, "tool")
	if len(tools) < 1 || tools[0].Content != "found it" || tools[0].ToolCallID != "call-1" {
		t.Fatalf("tool rows = %+v", tools)
	}
}

func TestApprovalWaitsForAPersonThenRunsTheTool(t *testing.T) {
	for _, approved := range []bool{true, false} {
		f := newFakeRun()
		f.llm[parentTask] = turns(
			calls(ToolCall{ID: "call-1", Name: "search", Arguments: `{"q": "x"}`}),
			calls(complete("call-2", "done")),
		)
		env := newEnv(t, f)
		req := request(nil)
		req.Policy.Approval = &api.ApprovalPolicy{EscalationRules: []string{"search"}}
		env.RegisterDelayedCallback(func() {
			v, err := env.QueryWorkflow(api.QueryPendingEscalation)
			if err != nil {
				t.Errorf("query: %v", err)
				return
			}
			var pending []api.PendingEscalationView
			if err := v.Get(&pending); err != nil || len(pending) != 1 {
				t.Errorf("pending = %+v, %v", pending, err)
				return
			}
			env.SignalWorkflow(api.SignalResolveEscalation, api.ResolveEscalationSignal{
				EscalationID: pending[0].EscalationID, Approved: approved, ResolvedBy: "user-1", Comment: "ok",
			})
		}, time.Hour)
		env.ExecuteWorkflow(AgentExecutionWorkflow, req)

		res := result(t, env)
		if !res.Success {
			t.Fatalf("approved=%v result = %+v", approved, res)
		}
		contains(t, f.events(parentTask), domain.EventApprovalRequested, domain.EventApprovalDecided, domain.EventToolResult)
		if approved && (len(f.toolCalls) != 1 || !f.toolCalls[0].PolicyApprovalGranted) {
			t.Fatalf("approved tool calls = %+v", f.toolCalls)
		}
		if !approved {
			if len(f.toolCalls) != 0 {
				t.Fatalf("denied call ran: %+v", f.toolCalls)
			}
			tools := f.messages(parentTask, "tool")
			if len(tools) == 0 || tools[0].Content != "Tool call denied by human operator: ok" {
				t.Fatalf("tool rows = %+v", tools)
			}
		}
		statuses := f.statuses[parentTask]
		if statuses[0].Status != "waiting_for_approval" || statuses[1].Status != "running" {
			t.Fatalf("statuses = %+v", statuses)
		}
	}
}

func TestCancelDuringAWaitStoresTheCancelledOutcome(t *testing.T) {
	f := newFakeRun()
	f.llm[parentTask] = turns(calls(ToolCall{ID: "call-1", Name: domain.ToolWait, Arguments: `{"seconds": 7200, "reason": "render"}`}))
	env := newEnv(t, f)
	env.RegisterDelayedCallback(env.CancelWorkflow, 10*time.Minute)
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))

	if !env.IsWorkflowCompleted() || !temporal.IsCanceledError(env.GetWorkflowError()) {
		t.Fatalf("want cancelled, got %v", env.GetWorkflowError())
	}
	contains(t, f.events(parentTask), domain.EventToolCall, domain.EventToolResult, domain.EventTaskCancelled, domain.EventExecutionFinished)
	if st := f.lastStatus(parentTask); st.Status != StatusCancelled || st.FailureReason != "cancelled" {
		t.Fatalf("final status = %+v", st)
	}
	tools := f.messages(parentTask, "tool")
	if len(tools) != 1 || tools[0].Content != stoppedBeforeRunning {
		t.Fatalf("tool rows = %+v", tools)
	}
}

func TestPauseEndsAWaitAndResumeContinuesTheRun(t *testing.T) {
	f := newFakeRun()
	f.llm[parentTask] = turns(
		calls(ToolCall{ID: "call-1", Name: domain.ToolWait, Arguments: `{"seconds": 7200, "reason": "render"}`}),
		calls(complete("call-2", "done")),
	)
	env := newEnv(t, f)
	env.RegisterDelayedCallback(func() { env.SignalWorkflow(api.SignalPause, api.PauseSignal{Reason: "lunch"}) }, time.Minute)
	env.RegisterDelayedCallback(func() {
		v, err := env.QueryWorkflow(api.QueryCurrentState)
		if err != nil {
			t.Errorf("query: %v", err)
			return
		}
		var state map[string]any
		if err := v.Get(&state); err != nil || state["paused"] != true {
			t.Errorf("state = %v, %v", state, err)
		}
		env.SignalWorkflow(api.SignalResume, api.PauseSignal{})
	}, 3*time.Hour)
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))

	res := result(t, env)
	if !res.Success || f.llmCalls[parentTask] != 2 {
		t.Fatalf("result = %+v, llm calls %d", res, f.llmCalls[parentTask])
	}
	contains(t, f.events(parentTask), domain.EventExecutionPaused, domain.EventToolResult, domain.EventExecutionResumed, domain.EventTaskCompleted)
	tools := f.messages(parentTask, "tool")
	if len(tools) == 0 || !strings.Contains(tools[0].Content, "the task was paused") {
		t.Fatalf("tool rows = %+v", tools)
	}
}

func TestModelCallRetriesThenAFatalErrorFailsTheTask(t *testing.T) {
	f := newFakeRun()
	attempts := 0
	f.llm[parentTask] = func(_ LLMCallRequest, attempt int32) (LLMCallResult, error) {
		attempts++
		if attempt == 1 {
			return LLMCallResult{}, errors.New("connection reset")
		}
		return text("recovered"), nil
	}
	env := newEnv(t, f)
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))
	if res := result(t, env); !res.Success || attempts != 2 {
		t.Fatalf("result = %+v after %d attempts", res, attempts)
	}

	f = newFakeRun()
	f.llm[parentTask] = func(LLMCallRequest, int32) (LLMCallResult, error) {
		return LLMCallResult{}, temporal.NewNonRetryableApplicationError("401 unauthorized: bad api_key", "AuthenticationError", nil)
	}
	env = newEnv(t, f)
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))
	if env.GetWorkflowError() == nil {
		t.Fatal("want the run to fail")
	}
	failed := f.eventData(parentTask, domain.EventLLMFailed)
	if len(failed) != 1 || failed[0]["error"] != "Authentication failed with the LLM provider. Please check your API key." {
		t.Fatalf("llm.call.failed = %+v", failed)
	}
	contains(t, f.events(parentTask), domain.EventLLMFailed, domain.EventTurnAborted, domain.EventTaskFailed)
	if st := f.lastStatus(parentTask); st.Status != StatusFailed || st.Resume == nil {
		t.Fatalf("final status = %+v", st)
	}
}

func TestDelegationRunsTheOtherAgentAsAChild(t *testing.T) {
	f := newFakeRun()
	f.cfg.Tools = append(f.cfg.Tools, api.ToolDefinition{Name: "delegate_to_helper", Parameters: map[string]any{"type": "object"}})
	f.cfg.Delegates = map[string]api.Delegate{"delegate_to_helper": {AgentID: "agent-2", AgentName: "helper"}}
	f.llm[parentTask] = turns(
		calls(ToolCall{ID: "call-1", Name: "delegate_to_helper", Arguments: `{"message": "summarize"}`}),
		calls(complete("call-2", "done")),
	)
	f.llm[childTask] = turns(text("child summary"))
	env := newEnv(t, f)
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))

	res := result(t, env)
	if !res.Success || res.TotalCost.String() != "0.03" {
		t.Fatalf("result = %+v", res)
	}
	if len(f.created) != 1 || f.created[0].RunBudget.String() != "9.99" {
		t.Fatalf("created = %+v", f.created)
	}
	if !strings.HasPrefix(f.created[0].ExecutionID, "delegation-") {
		t.Fatalf("child workflow id = %q", f.created[0].ExecutionID)
	}
	contains(t, f.events(parentTask), domain.EventDelegationStarted, domain.EventDelegationCompleted, domain.EventTaskCompleted)
	tools := f.messages(parentTask, "tool")
	var envelope map[string]any
	if len(tools) == 0 || json.Unmarshal([]byte(tools[0].Content), &envelope) != nil || envelope["final_response"] != "child summary" {
		t.Fatalf("tool rows = %+v", tools)
	}
	if st := f.lastStatus(childTask); st.Status != StatusCompleted || st.Resume != nil {
		t.Fatalf("child status = %+v", st)
	}
}

func TestContinueAsNewCarriesTheRunIntoTheNextExecution(t *testing.T) {
	f := newFakeRun()
	f.llm[parentTask] = turns(text("first"), text("second"))
	env := newEnv(t, f)
	env.SetContinueAsNewSuggested(true)
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))

	can, ok := errors.AsType[*workflow.ContinueAsNewError](env.GetWorkflowError())
	if !ok {
		t.Fatalf("want continue-as-new, got %v", env.GetWorkflowError())
	}
	contains(t, f.events(parentTask), domain.EventTaskStarted, domain.EventExecutionContinuedAsNew)
	var next AgentRunRequest
	if err := converter.GetDefaultDataConverter().FromPayloads(can.Input, &next); err != nil {
		t.Fatal(err)
	}
	if next.Continued == nil || next.Continued.Config.Model.ContextWindow != 100_000 || len(next.Continued.Tools) == 0 {
		t.Fatalf("continued state = %+v", next.Continued)
	}

	env = newEnv(t, f)
	env.ExecuteWorkflow(AgentExecutionWorkflow, next)
	res := result(t, env)
	if !res.Success || res.FinalResponse != "first" {
		t.Fatalf("result = %+v", res)
	}
	if got := f.eventData(parentTask, domain.EventTaskStarted); len(got) != 1 {
		t.Fatalf("task.started recorded %d times", len(got))
	}
}

func TestUnansweredInputRequestBlocksTheRunAfterItsTimeout(t *testing.T) {
	f := newFakeRun()
	f.llm[parentTask] = turns(calls(ToolCall{ID: "call-1", Name: domain.ToolRequestUserInput, Arguments: `{"question": "Which city?"}`}))
	env := newEnv(t, f)
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))

	res := result(t, env)
	if res.Success || res.Status != StatusBlocked || res.FailureReason != "input_timeout" {
		t.Fatalf("result = %+v", res)
	}
	contains(t, f.events(parentTask), domain.EventInputRequest, domain.EventTaskFailed)
	if st := f.lastStatus(parentTask); st.Status != StatusBlocked || st.Resume != nil {
		t.Fatalf("final status = %+v", st)
	}
}

func TestSubmittedInputAnswersTheRequest(t *testing.T) {
	f := newFakeRun()
	f.llm[parentTask] = turns(
		calls(ToolCall{ID: "call-1", Name: domain.ToolRequestUserInput, Arguments: `{"question": "Which city?"}`}),
		calls(complete("call-2", "Paris it is")),
	)
	env := newEnv(t, f)
	env.RegisterDelayedCallback(func() {
		data := f.eventData(parentTask, domain.EventInputRequest)
		if len(data) != 1 {
			t.Errorf("input.request = %+v", data)
			return
		}
		env.SignalWorkflow(api.SignalWorkflowCommand, api.WorkflowCommandSignal{Command: api.CommandSubmitUserInput, Payload: map[string]any{
			"input_request_id": data[0]["input_request_id"], "answers": map[string]any{"answer": "Paris"},
		}})
	}, time.Minute)
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))

	if res := result(t, env); !res.Success || res.FinalResponse != "Paris it is" {
		t.Fatalf("result = %+v", res)
	}
	contains(t, f.events(parentTask), domain.EventInputRequest, domain.EventInputSubmitted, domain.EventInputResponse, domain.EventTaskCompleted)
	tools := f.messages(parentTask, "tool")
	if len(tools) == 0 || !strings.Contains(tools[0].Content, `"answers": {"answer": "Paris"}`) {
		t.Fatalf("tool rows = %+v", tools)
	}
}

func TestIterationLimitWaitsForAContinuationGrant(t *testing.T) {
	f := newFakeRun()
	f.llm[parentTask] = turns(
		calls(ToolCall{ID: "c1", Name: "search", Arguments: `{}`}),
		calls(ToolCall{ID: "c2", Name: "search", Arguments: `{}`}),
		calls(complete("c3", "finally")),
	)
	env := newEnv(t, f)
	req := request(nil)
	req.Policy.Execution.MaxModelTurns = intp(2)
	next := testPolicy()
	next.Execution.MaxModelTurns = intp(3)
	var granted api.ContinueExecutionResult
	env.RegisterDelayedCallback(func() {
		env.UpdateWorkflow(api.UpdateContinueExecution, "grant-1", &testsuite.TestUpdateCallback{
			OnAccept: func() {},
			OnReject: func(err error) { t.Errorf("rejected: %v", err) },
			OnComplete: func(v any, err error) {
				if err != nil {
					t.Errorf("update failed: %v", err)
					return
				}
				granted, _ = v.(api.ContinueExecutionResult)
			},
		}, api.ContinueExecution{AdditionalIterations: 1, Policy: &next,
			Governance: &api.GovernanceSnapshot{Revision: 2, EffectivePolicy: next}})
	}, time.Hour)
	env.ExecuteWorkflow(AgentExecutionWorkflow, req)

	res := result(t, env)
	if !res.Success || res.FinalResponse != "finally" || !granted.Accepted || granted.MaxIterations != 3 {
		t.Fatalf("result = %+v, grant = %+v", res, granted)
	}
	contains(t, f.events(parentTask), domain.EventTaskAwaitingContinuation, domain.EventTaskContinued, domain.EventTaskCompleted)
}
