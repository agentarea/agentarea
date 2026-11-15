package mcpserver

import (
	"context"
	"errors"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

type fakeRuns struct{ *recorder }

func (f fakeRuns) Start(_ context.Context, _ authn.Caller, in runsapi.RunStart) (runsapi.RunStarted, error) {
	f.saw("start %s %q approval=%v sched=%v", in.AgentID, in.Description, in.RequiresHumanApproval, in.ScheduledAt != nil)
	if in.AgentID == "denied" {
		return runsapi.RunStarted{}, errors.New("Permission denied")
	}
	return runsapi.RunStarted{RunID: "r1", Status: "running"}, nil
}
func (f fakeRuns) List(_ context.Context, _ authn.Caller, agentID string, limit int) ([]runsapi.RunSummary, error) {
	f.saw("list %q %d", agentID, limit)
	return []runsapi.RunSummary{{RunID: "r1", Title: "Do it", Status: "completed"}}, nil
}
func (f fakeRuns) Get(_ context.Context, _ authn.Caller, id string) (runsapi.RunDetail, error) {
	f.saw("get %s", id)
	if id == "gone" {
		return runsapi.RunDetail{}, errors.New("Run not found")
	}
	return runsapi.RunDetail{RunSummary: runsapi.RunSummary{RunID: id, Title: "Do it", Status: "running"}, Query: "Do it"}, nil
}
func (f fakeRuns) Cancel(_ context.Context, _ authn.Caller, id string) (bool, error) {
	f.saw("cancel %s", id)
	return id != "done", nil
}
func (f fakeRuns) Retry(_ context.Context, _ authn.Caller, id string) error {
	f.saw("retry %s", id)
	if id == "running" {
		return errors.New("Only a failed run whose execution has finished can be retried")
	}
	return nil
}
func (f fakeRuns) Pause(_ context.Context, _ authn.Caller, id string) (bool, error) {
	f.saw("pause %s", id)
	return true, nil
}
func (f fakeRuns) Resume(_ context.Context, _ authn.Caller, id string) (bool, error) {
	f.saw("resume %s", id)
	return true, nil
}
func (f fakeRuns) SendInput(_ context.Context, _ authn.Caller, id, req string, answers map[string]any) (bool, error) {
	f.saw("input %s %s %v", id, req, answers)
	return true, nil
}
func (f fakeRuns) SendCommand(_ context.Context, _ authn.Caller, id string, cmd runsapi.RunCommand) (bool, error) {
	f.saw("command %s %s", id, cmd.Command)
	if cmd.Command == "dance" {
		return false, errors.New("Unknown command: dance")
	}
	return true, nil
}
func (f fakeRuns) ResolveEscalation(_ context.Context, _ authn.Caller, id, esc string, approved bool, comment string) (bool, error) {
	f.saw("resolve %s %s %v %q", id, esc, approved, comment)
	return true, nil
}
func (f fakeRuns) ListPendingEscalations(_ context.Context, _ authn.Caller, id string) ([]runsapi.PendingEscalation, error) {
	f.saw("pending %s", id)
	return []runsapi.PendingEscalation{{EscalationID: "e1", ToolName: "shell", ToolCallID: "t1", ToolArgs: map[string]any{"cmd": "ls"}}}, nil
}
func (f fakeRuns) ContinueRun(_ context.Context, _ authn.Caller, id string, g runsapi.RunGrant) (runsapi.ContinueExecutionResult, error) {
	f.saw("continue %s %d %d %d %v", id, g.Iterations, g.Tokens, g.ToolCalls, g.BudgetUSD != nil)
	return runsapi.ContinueExecutionResult{Accepted: true, ContinuationCount: 1}, nil
}
func (f fakeRuns) Events(_ context.Context, _ authn.Caller, id string, limit, offset int, eventType *string) (runsapi.RunEventsPage, error) {
	f.saw("events %s %d %d %v", id, limit, offset, eventType != nil)
	return runsapi.RunEventsPage{Total: 1, Events: []any{map[string]any{"event_type": "workflow.started"}}}, nil
}

type fakeInbox struct{ *recorder }

func (f fakeInbox) List(_ context.Context, _ authn.Caller, status *string, agentID string, page, size int) (runsapi.InboxPage, error) {
	s := "<all>"
	if status != nil {
		s = *status
	}
	f.saw("inbox %s %q %d %d", s, agentID, page, size)
	return runsapi.InboxPage{Items: []runsapi.InboxItem{{ID: "r1", Status: "failed"}}, Total: 1, Page: page, PageSize: size}, nil
}

func TestRunsToolset(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{Runs: fakeRuns{rec}}, "runs")
	runToolCases(t, ts, rec, []toolCase{
		{"runs_start", `{"agent_id":"a1","description":"Do it"}`, `start a1 "Do it" approval=false sched=false`, `"run_id":"r1"`, false},
		{"runs_start", `{"agent_id":"denied","description":"Do it"}`, "", "Permission denied", true},
		{"runs_list", `{}`, `list "" 20`, `"title":"Do it"`, false},
		{"runs_list", `{"agent_id":"a1","limit":1000}`, `list "a1" 1000`, `"r1"`, false},
		{"runs_list", `{"limit":0}`, "", "limit must be between 1 and 1000, got 0", true},
		{"runs_get", `{"run_id":"r1"}`, "get r1", `"query":"Do it"`, false},
		{"runs_get", `{"run_id":"gone"}`, "get gone", "Run not found", true},
		{"runs_cancel", `{"run_id":"done"}`, "cancel done", `{"cancelled":false}`, false},
		{"runs_retry", `{"run_id":"r1"}`, "retry r1", `{"retried":true,"run_id":"r1"}`, false},
		{"runs_retry", `{"run_id":"running"}`, "retry running", "Only a failed run", true},
		{"runs_pause", `{"run_id":"r1"}`, "pause r1", `{"paused":true}`, false},
		{"runs_resume", `{"run_id":"r1"}`, "resume r1", `{"resumed":true}`, false},
		{"runs_send_input", `{"run_id":"r1","input_request_id":"q1","answers":{"a":"b"}}`, "input r1 q1 map[a:b]", `"input_request_id":"q1"`, false},
		{"runs_send_command", `{"run_id":"r1","command":"queue_message","message":"hi"}`, "command r1 queue_message", `{"command":"queue_message","delivered":true}`, false},
		{"runs_send_command", `{"run_id":"r1","command":"dance"}`, "command r1 dance", "Unknown command: dance", true},
		{"runs_resolve_escalation", `{"run_id":"r1","escalation_id":"e1","approved":true,"comment":"ok"}`, `resolve r1 e1 true "ok"`, `{"approved":true,"resolved":true}`, false},
		{"runs_list_pending_escalations", `{"run_id":"r1"}`, "pending r1", `"tool_name":"shell"`, false},
		{"runs_continue_run", `{"run_id":"r1","additional_iterations":5,"additional_budget_usd":"1.50"}`, "continue r1 5 0 0 true", `"accepted":true`, false},
		{"runs_get_events", `{"run_id":"r1"}`, "events r1 50 0 false", `"total":1`, false},
		{"runs_get_events", `{"run_id":"r1","limit":5,"offset":2,"event_type":"tool.call"}`, "events r1 5 2 true", `"workflow.started"`, false},
		{"runs_get_events", `{"run_id":"r1","limit":999999}`, "events r1 100 0 false", `"total":1`, false},
	})
}

func TestInboxToolset(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{Inbox: fakeInbox{rec}}, "inbox")
	runToolCases(t, ts, rec, []toolCase{
		{"inbox_list", `{}`, `inbox <all> "" 1 50`, `"page_size":50`, false},
		{"inbox_list", `{"status":"","agent_id":"a1","page":2,"page_size":10}`, `inbox <all> "a1" 2 10`, `"page":2`, false},
		{"inbox_list", `{"status":"failed"}`, `inbox failed "" 1 50`, `"r1"`, false},
		{"inbox_list", `{"status":"lost"}`, "", "Unknown inbox status 'lost'; expected one of ['waiting_for_approval', 'waiting_for_input', 'completed', 'failed']", true},
	})
}
