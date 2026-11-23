package app

import (
	"context"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	connectionsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	runsservice "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/service"
)

type fakeRemoteAgents struct {
	saw       connectionsapi.RemoteAgentCall
	sawTask   connectionsapi.RemoteTaskCall
	cancelled []connectionsapi.RemoteTaskCall
	answer    connectionsapi.RemoteAgentResult
}

func (f *fakeRemoteAgents) SendRemoteAgent(_ context.Context, c connectionsapi.RemoteAgentCall) (connectionsapi.RemoteAgentResult, error) {
	f.saw = c
	return f.answer, nil
}

func (f *fakeRemoteAgents) GetRemoteAgentTask(_ context.Context, c connectionsapi.RemoteTaskCall) (connectionsapi.RemoteAgentResult, error) {
	f.sawTask = c
	return f.answer, nil
}

func (f *fakeRemoteAgents) CancelRemoteAgentTask(_ context.Context, c connectionsapi.RemoteTaskCall) error {
	f.cancelled = append(f.cancelled, c)
	return nil
}

func remoteInvocation() runsservice.ToolInvocation {
	return runsservice.ToolInvocation{ToolName: "delegate_to_Docs", ToolCallID: "call-1", TaskID: "t1", ExecutionID: "e1", CallRef: "ref",
		Args:      map[string]any{"message": "write the docs"},
		Principal: runsservice.Principal{WorkspaceID: "w1", UserID: "u1", AgentID: "a1"},
		Binding: runsapi.ToolBinding{Source: "remote_agent",
			RemoteAgent: &runsapi.RemoteAgentBinding{AgentName: "Docs", A2AURL: "https://remote.test", AuthSecretName: "remote-key"}}}
}

func TestRemoteAgentCallerDelegatesAsTheRunsAgent(t *testing.T) {
	f := &fakeRemoteAgents{answer: connectionsapi.RemoteAgentResult{Success: true, Result: "the docs",
		Payments: []connectionsapi.Payment{{Protocol: "x402", Amount: money.MustParse("0.5"), Settled: true}}}}
	out, err := remoteAgentCaller{t: f}.Call(context.Background(), remoteInvocation())
	if err != nil || !out.Success || out.Result != "the docs" || out.Source != "builtin" || len(out.Payments) != 1 || out.ServiceCost.String() != "0.5" {
		t.Fatalf("out = %+v %v", out, err)
	}
	want := connectionsapi.RemoteAgentCall{WorkspaceID: "w1", UserID: "u1", AgentID: "a1", AgentName: "Docs", ToolName: "delegate_to_Docs",
		ToolCallID: "call-1", A2AURL: "https://remote.test", AuthSecretName: "remote-key", Message: "write the docs",
		MessageID: remoteMessageID("e1", "call-1"), Paid: connectionsapi.PaidCall{ExecutionID: "e1", CallRef: "ref"}}
	if f.saw != want || len(want.MessageID) != 32 {
		t.Fatalf("call = %+v", f.saw)
	}
	if _, _ = (remoteAgentCaller{t: f}).Call(context.Background(), remoteInvocation()); f.saw.MessageID != want.MessageID {
		t.Fatalf("a second attempt sent message id %q, the first %q", f.saw.MessageID, want.MessageID)
	}
	if remoteMessageID("e1", "call-2") == want.MessageID {
		t.Fatal("two calls share a message id")
	}
}

func TestRemoteAgentCallerHandsTheRunningTaskToTheRun(t *testing.T) {
	task := connectionsapi.RemoteTask{ID: "rt1", Endpoint: "https://remote.test/rpc", Legacy: true}
	f := &fakeRemoteAgents{answer: connectionsapi.RemoteAgentResult{Pending: &task}}
	c := remoteAgentCaller{t: f}
	out, err := c.Call(context.Background(), remoteInvocation())
	want := runsapi.RemoteAgentTask{TaskID: "rt1", Endpoint: "https://remote.test/rpc", Legacy: true}
	if err != nil || !out.Success || out.RemoteTask == nil || *out.RemoteTask != want {
		t.Fatalf("out = %+v %v", out, err)
	}
	out, err = c.GetTask(context.Background(), remoteInvocation(), want)
	if err != nil || out.RemoteTask == nil || f.sawTask.Task != task || f.sawTask.AuthSecretName != "remote-key" || f.sawTask.UserID != "u1" {
		t.Fatalf("get = %+v %v, saw %+v", out, err, f.sawTask)
	}
	f.answer = connectionsapi.RemoteAgentResult{Success: true, Result: "the docs"}
	if out, _ = c.GetTask(context.Background(), remoteInvocation(), want); !out.Success || out.Result != "the docs" || out.RemoteTask != nil {
		t.Fatalf("done = %+v", out)
	}
	if err := c.CancelTask(context.Background(), remoteInvocation(), want); err != nil || len(f.cancelled) != 1 || f.cancelled[0].Task != task {
		t.Fatalf("cancel = %v, %+v", err, f.cancelled)
	}
}

func TestRemoteAgentCallerAnswersWhatTheToolRaised(t *testing.T) {
	f := &fakeRemoteAgents{answer: connectionsapi.RemoteAgentResult{Error: "A2A request failed with HTTP 500", Raised: true}}
	out, err := remoteAgentCaller{t: f}.Call(context.Background(), remoteInvocation())
	msg := "Tool 'delegate_to_Docs' execution failed: A2A request failed with HTTP 500"
	if err != nil || out.Success || out.Error != msg || out.Result != "MCP tool error: ToolExecutionError: "+msg || out.Source != "builtin" {
		t.Fatalf("out = %+v %v", out, err)
	}
	f.answer = connectionsapi.RemoteAgentResult{Error: "'Docs' ended the task as TASK_STATE_FAILED: boom"}
	out, _ = remoteAgentCaller{t: f}.Call(context.Background(), remoteInvocation())
	if out.Success || out.Error != f.answer.Error || out.Result != "" {
		t.Fatalf("failed = %+v", out)
	}
}
