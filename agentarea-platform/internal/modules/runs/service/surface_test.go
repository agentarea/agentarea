package service

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
)

type fakeExecutor struct {
	durable.Executor
	status  durable.Result
	failure string
	signals []string
}

func (f *fakeExecutor) Status(context.Context, string) (durable.Result, error) { return f.status, nil }
func (f *fakeExecutor) Wait(context.Context, string, time.Duration) (durable.Result, error) {
	return durable.Result{Error: f.failure}, nil
}
func (f *fakeExecutor) Signal(_ context.Context, _ string, signal string, _ ...any) error {
	f.signals = append(f.signals, signal)
	return nil
}

func surfaceWith(x durable.Executor) *Surface {
	return NewSurface(SurfaceDeps{Executor: x, Log: quiet(), Now: fixedNow})
}

func TestWorkflowStatusClassifiesTheRunsOutcome(t *testing.T) {
	ctx := context.Background()
	for _, c := range []struct {
		name    string
		result  durable.Result
		failure string
		status  string
		reason  any
	}{
		{"completed with a response", durable.Result{Status: durable.StatusCompleted, Result: json.RawMessage(`{"success":true,"final_response":"done"}`)}, "", "completed", nil},
		{"completed without a response", durable.Result{Status: durable.StatusCompleted, Result: json.RawMessage(`{"success":true,"final_response":"  "}`)}, "", "failed", "missing_final_response"},
		{"waiting for input", durable.Result{Status: durable.StatusCompleted, Result: json.RawMessage(`{"status":"waiting_for_input"}`)}, "", "waiting_for_input", nil},
		{"quota exhausted", durable.Result{Status: durable.StatusFailed}, "Error: Quota exceeded for model", "blocked", nil},
		{"terminated", durable.Result{Status: durable.StatusTerminated}, "boom", "failed", nil},
		{"missing", durable.Result{Status: durable.StatusUnknown, Error: "Workflow not found"}, "", "unknown", nil},
	} {
		t.Run(c.name, func(t *testing.T) {
			s := surfaceWith(&fakeExecutor{status: c.result, failure: c.failure})
			got := s.workflowStatus(ctx, "task-1")
			if got.Status != c.status || got.FailureReason != c.reason {
				t.Fatalf("got %+v", got)
			}
		})
	}
}

func TestFilterDomainFieldsFlattensTheEnvelope(t *testing.T) {
	data := wirejson.Object{
		{Key: "event_type", Value: "x"},
		{Key: "data", Value: wirejson.Object{
			{Key: "original_event_type", Value: "ToolCallStarted"},
			{Key: "original_data", Value: wirejson.Object{{Key: "tool_name", Value: "shell"}}},
			{Key: "aggregate_id", Value: "a"},
			{Key: "step", Value: 1},
		}},
	}
	got, err := wirejson.Marshal(filterDomainFields(data), wirejson.Compact)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != `{"event_type":"x","step":1,"tool_name":"shell"}` {
		t.Fatalf("got %s", got)
	}
}

func TestRevealToolValueRedactsSecretKeysOnly(t *testing.T) {
	v := wirejson.Object{
		{Key: "api-key", Value: "abc"},
		{Key: "cmd", Value: "echo hi"},
		{Key: "nested", Value: []any{wirejson.Object{{Key: "passwd", Value: "x"}}}},
	}
	got, _ := wirejson.Marshal(revealToolValue(v, "", 0), wirejson.Compact)
	if string(got) != `{"api-key":"[redacted]","cmd":"echo hi","nested":[{"passwd":"[redacted]"}]}` {
		t.Fatalf("got %s", got)
	}
}

func TestTaskResponseCarriesTheApiCallersEndUser(t *testing.T) {
	exec := "task-x"
	task := Task{
		ID: "t", AgentID: "a", Description: "d", Status: "completed", CreatedBy: "u",
		Parameters: wirejson.Object{}, Result: wirejson.Object{{Key: "total_cost", Value: "0.5"}, {Key: "tokens_used", Value: json.Number("7")}},
		ExecutionID: &exec, Metadata: wirejson.Object{{Key: "end_user_id", Value: "eu-1"}},
		CreatedAt: time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC),
	}
	c := authn.Caller{Principal: authn.Principal{UserID: "u", Credential: &authn.Credential{Kind: authn.KindAPIKey}}}
	got := TaskResponseJSON(task, c)
	if v, _ := got.Get("end_user_id"); v != "eu-1" {
		t.Fatalf("end_user_id %v", v)
	}
	if v, _ := got.Get("total_cost"); v != 0.5 && v != wirejson.Float(0.5) {
		t.Fatalf("total_cost %v (%T)", v, v)
	}
	if v, _ := got.Get("created_at"); v != "2026-01-02T03:04:05Z" {
		t.Fatalf("created_at %v", v)
	}
}

func TestEndsFeedWaitsForASettlingRun(t *testing.T) {
	settling := Envelope{EventType: "task.completed", Data: wirejson.Object{{Key: "execution_status", Value: "settling"}}}
	if endsFeed(settling, true) || !endsFeed(settling, false) || !endsFeed(Envelope{EventType: "task.failed", Data: wirejson.Object{}}, true) {
		t.Fatal("a settling run keeps the feed open; a failed one ends it")
	}
}

type failingWrites struct{ db.Database }

func (failingWrites) Write(context.Context, scope.Workspace, func(context.Context, db.Session) error) error {
	return errors.New("connection reset")
}

type cancelOK struct{ fakeExecutor }

func (*cancelOK) Cancel(context.Context, string) error { return nil }

func TestCancellingAScheduledTaskReportsAFailedWrite(t *testing.T) {
	ws, err := scope.NewWorkspace("00000000-0000-4000-8000-000000000009", "acme")
	if err != nil {
		t.Fatal(err)
	}
	s := NewSurface(SurfaceDeps{DB: failingWrites{}, Executor: &cancelOK{}, Log: quiet(), Now: fixedNow})
	ok, err := s.cancelScheduled(context.Background(), ws, Task{ID: "00000000-0000-4000-8000-00000000000a"})
	if ok || err == nil {
		t.Fatalf("a cancelled workflow whose task row was not written is an error, not 'not found': %v %v", ok, err)
	}
}

func TestDecisionsAnswerNullForAMalformedAgentID(t *testing.T) {
	taskID := uuid.New()
	agentID := uuid.NewString()
	meta, err := auditMetadata([]byte(`{"agent_id":"not-a-uuid","tool":"send","comment":"","escalation_id":0}`))
	if err != nil {
		t.Fatal(err)
	}
	at := time.Date(2026, 3, 1, 12, 0, 0, 0, time.UTC)
	row := governanceapi.AuditEntry{ActorType: "agent", ActorID: "a", Action: approvalDenied, CreatedAt: at}
	got := decisionJSON(row, taskID, meta, map[uuid.UUID]string{taskID: "Do it"}, nil)
	want := wirejson.Object{
		{Key: "escalation_id", Value: ""}, {Key: "task_id", Value: taskID.String()},
		{Key: "agent_id", Value: nil}, {Key: "agent_name", Value: nil},
		{Key: "task_description", Value: "Do it"}, {Key: "tool_name", Value: "send"},
		{Key: "approved", Value: false}, {Key: "decided_by", Value: nil},
		{Key: "comment", Value: nil}, {Key: "decided_at", Value: "2026-03-01T12:00:00Z"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v", got)
	}
	meta, _ = auditMetadata([]byte(`{"agent_id":"` + agentID + `","escalation_id":"e1","comment":"ok"}`))
	row.ActorType, row.Action = "user", approvalApproved
	got = decisionJSON(row, taskID, meta, nil, map[string]string{agentID: "Bot"})
	if v, _ := got.Get("agent_name"); v != "Bot" {
		t.Fatalf("agent_name %v", v)
	}
	for k, w := range map[string]any{"escalation_id": "e1", "decided_by": "a", "comment": "ok", "approved": true, "task_description": nil} {
		if v, _ := got.Get(k); v != w {
			t.Fatalf("%s = %v", k, v)
		}
	}
}
