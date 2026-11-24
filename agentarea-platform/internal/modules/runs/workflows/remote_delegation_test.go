package workflows

import (
	"encoding/json"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"

	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/workflow"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

// remoteTask is how a fake remote agent answers one call: after a while, or it fails then.
type remoteTask struct {
	after time.Duration
	fails bool
}

// remoteWorld is a set of remote A2A agents whose tasks end at a simulated time.
type remoteWorld struct {
	mu    sync.Mutex
	now   func() time.Time
	tasks map[string]remoteTask
	sent  map[string]time.Time
	sends []ToolCallRequest
}

func addRemoteAgents(f *fakeRun, names ...string) {
	for _, n := range names {
		tool := "delegate_to_" + n
		f.cfg.Tools = append(f.cfg.Tools, api.ToolDefinition{Name: tool, Parameters: map[string]any{"type": "object"}})
		f.cfg.Bindings[tool] = api.ToolBinding{Source: "remote_agent", RemoteAgent: &api.RemoteAgentBinding{
			AgentName: n, A2AURL: "https://agents.example.com/" + n,
		}}
	}
}

func newRemoteWorld(f *fakeRun, tasks map[string]remoteTask) *remoteWorld {
	w := &remoteWorld{tasks: tasks, sent: map[string]time.Time{}}
	f.tool = func(req ToolCallRequest) (ToolCallResult, error) {
		w.mu.Lock()
		defer w.mu.Unlock()
		w.sends = append(w.sends, req)
		if _, again := w.sent[req.ToolCallID]; !again {
			w.sent[req.ToolCallID] = w.now()
		}
		return ToolCallResult{Success: true, Source: "builtin", ServiceCost: money.MustParse("0.25"),
			RemoteTask: &api.RemoteAgentTask{TaskID: "rt-" + req.ToolCallID, Endpoint: "https://agents.example.com/rpc"}}, nil
	}
	f.remoteGet = func(req RemoteTaskRequest) (ToolCallResult, error) {
		w.mu.Lock()
		defer w.mu.Unlock()
		t := w.tasks[req.ToolCallID]
		if w.now().Sub(w.sent[req.ToolCallID]) < t.after {
			return ToolCallResult{Success: true, Source: "builtin", RemoteTask: &req.Task}, nil
		}
		if t.fails {
			return ToolCallResult{Error: "'" + req.Binding.RemoteAgent.AgentName + "' ended the task as TASK_STATE_FAILED: boom", Source: "builtin"}, nil
		}
		return ToolCallResult{Success: true, Result: "answer from " + req.ToolName, Source: "builtin"}, nil
	}
	return w
}

func remoteCall(id, agent, message string) ToolCall {
	return ToolCall{ID: id, Name: "delegate_to_" + agent, Arguments: `{"message": "` + message + `"}`}
}

func envelope(t *testing.T, row LogRow) map[string]any {
	t.Helper()
	var e map[string]any
	if err := json.Unmarshal([]byte(row.Content), &e); err != nil {
		t.Fatalf("tool row %s is not an envelope: %q", row.ToolCallID, row.Content)
	}
	return e
}

func remoteEnv(t *testing.T, f *fakeRun, w *remoteWorld) *testsuite.TestWorkflowEnvironment {
	t.Helper()
	env := newEnv(t, f)
	env.SetTestTimeout(time.Minute)
	w.now = env.Now
	return env
}

func TestARemoteAgentAnsweringAfterThreeHoursIsWaitedFor(t *testing.T) {
	f := newFakeRun()
	addRemoteAgents(f, "a")
	w := newRemoteWorld(f, map[string]remoteTask{"call-a": {after: 3 * time.Hour}})
	f.llm[parentTask] = turns(calls(remoteCall("call-a", "a", "research")), calls(complete("call-done", "done")))
	env := remoteEnv(t, f, w)
	start := env.Now()
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))

	if res := result(t, env); !res.Success {
		t.Fatalf("result = %+v", res)
	}
	if took := env.Now().Sub(start); took < 3*time.Hour || took > 3*time.Hour+time.Minute {
		t.Fatalf("the turn took %s", took)
	}
	tools := f.messages(parentTask, "tool")
	e := envelope(t, tools[0])
	if e["status"] != "completed" || e["agent"] != "a" || e["task_id"] != "rt-call-a" || e["final_response"] != "answer from delegate_to_a" {
		t.Fatalf("envelope = %v", e)
	}
	if len(w.sends) != 1 || w.sends[0].Args["message"] != "research" {
		t.Fatalf("sends = %+v", w.sends)
	}
	if len(f.gets) <= remotePollsPerRun {
		t.Fatalf("%d reads, want the wait to outlast one run of %d", len(f.gets), remotePollsPerRun)
	}
	for _, g := range f.gets {
		if g.Task.TaskID != "rt-call-a" || g.ToolCallID != "call-a" || g.Binding.RemoteAgent == nil {
			t.Fatalf("read = %+v", g)
		}
	}
	contains(t, f.events(parentTask), domain.EventDelegationStarted, domain.EventDelegationCompleted, domain.EventTaskCompleted)
	if res := result(t, env); res.TotalCost.String() != "0.02" {
		t.Fatalf("total cost = %s", res.TotalCost)
	}
}

func TestRemoteAgentCallsOfOneTurnAreWaitedForTogether(t *testing.T) {
	f := newFakeRun()
	addRemoteAgents(f, "a", "b", "c")
	w := newRemoteWorld(f, map[string]remoteTask{
		"call-a": {after: 3 * time.Hour}, "call-b": {after: 10 * time.Minute}, "call-c": {after: 20 * time.Minute, fails: true},
	})
	f.llm[parentTask] = turns(
		calls(remoteCall("call-a", "a", "one"), remoteCall("call-b", "b", "two"), remoteCall("call-c", "c", "three")),
		calls(complete("call-done", "done")),
	)
	env := remoteEnv(t, f, w)
	start := env.Now()
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))

	if res := result(t, env); !res.Success {
		t.Fatalf("result = %+v", res)
	}
	if took := env.Now().Sub(start); took > 3*time.Hour+time.Minute {
		t.Fatalf("the turn took %s: the calls were waited for one after another", took)
	}
	tools := f.messages(parentTask, "tool")
	want := []struct{ id, status, field, value string }{
		{"call-a", "completed", "final_response", "answer from delegate_to_a"},
		{"call-b", "completed", "final_response", "answer from delegate_to_b"},
		{"call-c", "failed", "error", "'c' ended the task as TASK_STATE_FAILED: boom"},
	}
	for i, wnt := range want {
		e := envelope(t, tools[i])
		if tools[i].ToolCallID != wnt.id || e["status"] != wnt.status || e[wnt.field] != wnt.value || e["task_id"] != "rt-"+wnt.id {
			t.Fatalf("tool row %d = %s %v, want %+v", i, tools[i].ToolCallID, e, wnt)
		}
	}
	var arrived []string
	for _, d := range f.eventData(parentTask, domain.EventDelegationCompleted) {
		arrived = append(arrived, d["tool_call_id"].(string))
	}
	if strings.Join(arrived, ",") != "call-b,call-c,call-a" {
		t.Fatalf("results arrived as %v", arrived)
	}
	if res := result(t, env); res.TotalToolCalls != 3 {
		t.Fatalf("result = %+v", res)
	}
}

func TestStoppingTheRunStopsTheRemoteTask(t *testing.T) {
	f := newFakeRun()
	addRemoteAgents(f, "a")
	w := newRemoteWorld(f, map[string]remoteTask{"call-a": {after: 3 * time.Hour}})
	f.llm[parentTask] = turns(calls(remoteCall("call-a", "a", "research")))
	env := remoteEnv(t, f, w)
	env.RegisterDelayedCallback(env.CancelWorkflow, time.Hour)
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))

	if !env.IsWorkflowCompleted() || !temporal.IsCanceledError(env.GetWorkflowError()) {
		t.Fatalf("want cancelled, got %v", env.GetWorkflowError())
	}
	if len(f.cancels) != 1 || f.cancels[0].Task.TaskID != "rt-call-a" || f.cancels[0].ToolCallID != "call-a" {
		t.Fatalf("cancels = %+v", f.cancels)
	}
	reads := len(f.gets)
	if st := f.lastStatus(parentTask); st.Status != StatusCancelled {
		t.Fatalf("final status = %+v", st)
	}
	tools := f.messages(parentTask, "tool")
	if e := envelope(t, tools[0]); e["status"] != "cancelled" || e["error"] != delegationStopped {
		t.Fatalf("envelope = %v", e)
	}
	contains(t, f.events(parentTask), domain.EventDelegationStarted, domain.EventDelegationFailed, domain.EventTaskCancelled)
	if reads == 0 || reads > 200 {
		t.Fatalf("%d reads in the hour before the stop", reads)
	}
}

func TestARetriedSendIsTheSameCall(t *testing.T) {
	f := newFakeRun()
	addRemoteAgents(f, "a")
	w := newRemoteWorld(f, map[string]remoteTask{"call-a": {after: time.Minute}})
	send := f.tool
	attempts := 0
	f.tool = func(req ToolCallRequest) (ToolCallResult, error) {
		attempts++
		res, err := send(req)
		if attempts == 1 {
			return ToolCallResult{}, errors.New("connection reset after the agent took the message")
		}
		return res, err
	}
	f.llm[parentTask] = turns(calls(remoteCall("call-a", "a", "research")), calls(complete("call-done", "done")))
	env := remoteEnv(t, f, w)
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))

	if res := result(t, env); !res.Success {
		t.Fatalf("result = %+v", res)
	}
	if len(w.sends) != 2 {
		t.Fatalf("sends = %d", len(w.sends))
	}
	a, b := w.sends[0], w.sends[1]
	if a.ExecutionID == "" || a.ExecutionID != b.ExecutionID || a.ToolCallID != b.ToolCallID || a.Args["message"] != b.Args["message"] {
		t.Fatalf("the retry is another call: %+v / %+v", a, b)
	}
	if e := envelope(t, f.messages(parentTask, "tool")[0]); e["status"] != "completed" {
		t.Fatalf("envelope = %v", e)
	}
}

func remoteRequest(f *fakeRun, deadline time.Time) RemoteDelegationRequest {
	b := f.cfg.Bindings["delegate_to_a"]
	return RemoteDelegationRequest{Deadline: deadline, Call: ToolCallRequest{
		Principal: Principal{WorkspaceID: "ws-1", UserID: "user-1", AgentID: "agent-1"}, TaskID: parentTask, ExecutionID: "exec-1",
		ToolCallID: "call-a", ToolName: "delegate_to_a", Args: map[string]any{"message": "research"}, Binding: b, Policy: testPolicy(),
	}}
}

func childEnv(t *testing.T, f *fakeRun, w *remoteWorld) *testsuite.TestWorkflowEnvironment {
	t.Helper()
	return remoteEnv(t, f, w)
}

func TestALongWaitContinuesAsNewWithItsState(t *testing.T) {
	f := newFakeRun()
	addRemoteAgents(f, "a")
	w := newRemoteWorld(f, map[string]remoteTask{"call-a": {after: 3 * time.Hour}})
	env := childEnv(t, f, w)
	env.ExecuteWorkflow(RemoteDelegationWorkflow, remoteRequest(f, env.Now().Add(6*time.Hour)))

	can, ok := errors.AsType[*workflow.ContinueAsNewError](env.GetWorkflowError())
	if !ok {
		t.Fatalf("want continue-as-new, got %v", env.GetWorkflowError())
	}
	var next RemoteDelegationRequest
	if err := converter.GetDefaultDataConverter().FromPayloads(can.Input, &next); err != nil {
		t.Fatal(err)
	}
	st := next.State
	if st == nil || st.Polls != remotePollsPerRun || st.Task.TaskID != "rt-call-a" || st.Delay != remotePollMax ||
		st.Sent.ServiceCost.String() != "0.25" || st.Started.IsZero() {
		t.Fatalf("state = %+v", st)
	}

	ended := env.Now()
	env = childEnv(t, f, w)
	env.SetStartTime(ended)
	env.ExecuteWorkflow(RemoteDelegationWorkflow, next)
	if !env.IsWorkflowCompleted() || env.GetWorkflowError() != nil {
		t.Fatalf("second run: %v", env.GetWorkflowError())
	}
	var res RemoteDelegationResult
	if err := env.GetWorkflowResult(&res); err != nil {
		t.Fatal(err)
	}
	if !res.Answer.Success || res.Answer.Result != "answer from delegate_to_a" || res.TaskID != "rt-call-a" ||
		res.Answer.ServiceCost.String() != "0.25" || res.Answer.Duration < 3*time.Hour {
		t.Fatalf("result = %+v", res)
	}
	if len(w.sends) != 1 {
		t.Fatalf("the next run sent again: %d sends", len(w.sends))
	}
}

func TestATaskUpdateSignalReadsTheTaskAtOnce(t *testing.T) {
	f := newFakeRun()
	addRemoteAgents(f, "a")
	w := newRemoteWorld(f, map[string]remoteTask{"call-a": {after: 6 * time.Hour}})
	env := childEnv(t, f, w)
	at := time.Hour + 7*time.Second
	env.RegisterDelayedCallback(func() {
		w.mu.Lock()
		w.tasks["call-a"] = remoteTask{}
		w.mu.Unlock()
		env.SignalWorkflow(api.SignalRemoteTaskUpdate, api.RemoteTaskUpdate{TaskID: "someone-else"})
		env.SignalWorkflow(api.SignalRemoteTaskUpdate, api.RemoteTaskUpdate{TaskID: "rt-call-a"})
	}, at)
	env.ExecuteWorkflow(RemoteDelegationWorkflow, remoteRequest(f, env.Now().Add(6*time.Hour)))

	var res RemoteDelegationResult
	if err := env.GetWorkflowResult(&res); err != nil {
		t.Fatal(err)
	}
	if !res.Answer.Success || res.Answer.Duration != at {
		t.Fatalf("answered after %s, want %s: %+v", res.Answer.Duration, at, res)
	}
}

func TestARemoteTaskPastTheDeadlineIsStopped(t *testing.T) {
	f := newFakeRun()
	addRemoteAgents(f, "a")
	w := newRemoteWorld(f, map[string]remoteTask{"call-a": {after: 3 * time.Hour}})
	env := childEnv(t, f, w)
	env.ExecuteWorkflow(RemoteDelegationWorkflow, remoteRequest(f, env.Now().Add(time.Hour)))

	var res RemoteDelegationResult
	if err := env.GetWorkflowResult(&res); err != nil {
		t.Fatal(err)
	}
	if res.Answer.Success || res.Answer.Error != "'a' is still working on task rt-call-a; no result within the delegation time limit" {
		t.Fatalf("result = %+v", res)
	}
	if len(f.cancels) != 1 || f.cancels[0].Task.TaskID != "rt-call-a" {
		t.Fatalf("cancels = %+v", f.cancels)
	}
}

func TestOrdinaryToolsOfOneTurnRunInOrder(t *testing.T) {
	f := newFakeRun()
	var mu sync.Mutex
	running, overlapped := 0, false
	var ran []string
	f.tool = func(req ToolCallRequest) (ToolCallResult, error) {
		mu.Lock()
		running++
		overlapped = overlapped || running > 1
		ran = append(ran, req.ToolCallID)
		mu.Unlock()
		time.Sleep(20 * time.Millisecond)
		mu.Lock()
		running--
		mu.Unlock()
		return ToolCallResult{Success: true, Result: "found " + req.ToolCallID, Source: "mcp"}, nil
	}
	f.llm[parentTask] = turns(
		calls(
			ToolCall{ID: "call-1", Name: "search", Arguments: `{"q": "1"}`},
			ToolCall{ID: "call-2", Name: "search", Arguments: `{"q": "2"}`},
			ToolCall{ID: "call-3", Name: "search", Arguments: `{"q": "3"}`},
		),
		calls(complete("call-4", "done")),
	)
	env := newEnv(t, f)
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))

	if res := result(t, env); !res.Success {
		t.Fatalf("result = %+v", res)
	}
	if overlapped || strings.Join(ran, ",") != "call-1,call-2,call-3" {
		t.Fatalf("ran %v, overlapped %v", ran, overlapped)
	}
	tools := f.messages(parentTask, "tool")
	for i, id := range []string{"call-1", "call-2", "call-3"} {
		if tools[i].ToolCallID != id || tools[i].Content != "found "+id {
			t.Fatalf("tool rows = %+v", tools)
		}
	}
}
