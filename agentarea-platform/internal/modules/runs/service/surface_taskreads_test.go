package service

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
)

type workflowStatuses struct {
	durable.Executor
	by map[string]durable.Status
}

func (w workflowStatuses) Status(_ context.Context, id string) (durable.Result, error) {
	st, ok := w.by[id]
	if !ok {
		return durable.Result{Status: durable.StatusUnknown, Error: "Workflow not found"}, nil
	}
	return durable.Result{WorkflowID: id, Status: st}, nil
}

type taskSeed struct {
	status, origin, originID, execution, result string
	age                                         time.Duration
	policy                                      bool
}

func seedTask(t *testing.T, d db.Database, ws scope.Workspace, agentID string, ts taskSeed) string {
	t.Helper()
	id := uuid.NewString()
	meta := map[string]any{}
	if ts.policy {
		meta["governance_snapshot"] = map[string]any{"effective_policy": map[string]any{}}
	}
	err := d.Write(context.Background(), ws, func(ctx context.Context, s db.Session) error {
		if err := (store.Runs{}).CreateTask(ctx, s, store.NewTask{
			ID: id, AgentID: agentID, Description: "stored ask", Status: ts.status, CreatedBy: "user-1", Metadata: meta,
			OriginType: ts.origin, OriginID: ts.originID, CausationID: "cause-" + id[:8],
		}, time.Now().Add(-ts.age)); err != nil {
			return err
		}
		var exec, result any
		if ts.execution != "" {
			exec = ts.execution
		}
		if ts.result != "" {
			result = ts.result
		}
		_, err := s.Q().Exec(ctx, `UPDATE tasks SET execution_id = $2, result = $3::text::json, error = 'Task dispatch failed' WHERE id = $1`, id, exec, result)
		return err
	})
	if err != nil {
		t.Fatal(err)
	}
	return id
}

func TestTaskReadsForStreams(t *testing.T) {
	d := openDB(t)
	p, _ := seed(t, d)
	ws, _ := scope.NewWorkspace(p.WorkspaceID, "")
	other, _ := seed(t, d)
	otherWS, _ := scope.NewWorkspace(other.WorkspaceID, "")
	ctx := context.Background()
	trigger := uuid.NewString()

	own := seedTask(t, d, ws, p.AgentID, taskSeed{status: "completed", result: `{"own_cost": "0.25", "total_cost": "1.5"}`})
	total := seedTask(t, d, ws, p.AgentID, taskSeed{status: "completed", result: `{"own_cost": null, "total_cost": 2}`})
	none := seedTask(t, d, ws, p.AgentID, taskSeed{status: "failed", result: `"plain text"`})
	bare := seedTask(t, d, ws, p.AgentID, taskSeed{status: "pending"})

	s := NewSurface(SurfaceDeps{DB: d, Log: quiet(), Now: fixedNow})
	statuses, err := s.Statuses(ctx, ws, []string{own, none, "not-a-uuid", uuid.NewString()})
	if err != nil || len(statuses) != 2 || statuses[own] != "completed" || statuses[none] != "failed" {
		t.Fatalf("%v %v", statuses, err)
	}
	if got, _ := s.Statuses(ctx, otherWS, []string{own}); len(got) != 0 {
		t.Fatalf("another workspace reads statuses: %v", got)
	}
	costs, err := s.Costs(ctx, ws, []string{own, total, none, bare})
	if err != nil || costs[own] != 0.25 || costs[total] != 2 || costs[none] != 0 || costs[bare] != 0 || len(costs) != 4 {
		t.Fatalf("%v %v", costs, err)
	}

	origin := seedTask(t, d, ws, p.AgentID, taskSeed{status: "running", origin: "trigger", originID: trigger})
	o, ok, err := s.Origin(ctx, ws, origin)
	if err != nil || !ok || o != (api.TaskOrigin{OriginType: "trigger", OriginID: trigger, CausationID: "cause-" + origin[:8]}) {
		t.Fatalf("%+v %v %v", o, ok, err)
	}
	if _, ok, err := s.Origin(ctx, otherWS, origin); ok || err != nil {
		t.Fatalf("another workspace reads the origin: %v %v", ok, err)
	}
	if _, ok, err := s.Origin(ctx, ws, "nope"); ok || err != nil {
		t.Fatalf("%v %v", ok, err)
	}
	if st, ok, err := s.Task(ctx, ws, origin); err != nil || !ok || st.Status != "running" || st.ExecutionID != "" {
		t.Fatalf("%+v %v %v", st, ok, err)
	}
	if _, ok, err := s.Task(ctx, otherWS, origin); ok || err != nil {
		t.Fatalf("another workspace reads the task: %v %v", ok, err)
	}
}

func TestOpenRunFromAsksTheWorkflow(t *testing.T) {
	d := openDB(t)
	p, _ := seed(t, d)
	ws, _ := scope.NewWorkspace(p.WorkspaceID, "")
	ctx := context.Background()
	trigger := uuid.NewString()
	seedTask(t, d, ws, p.AgentID, taskSeed{status: "pending", origin: "trigger", originID: trigger, age: 4 * time.Minute})
	gone := seedTask(t, d, ws, p.AgentID, taskSeed{status: "running", origin: "trigger", originID: trigger, execution: "task-gone", age: 3 * time.Minute})
	seedTask(t, d, ws, p.AgentID, taskSeed{status: "completed", origin: "trigger", originID: trigger, execution: "task-done", age: 2 * time.Minute})
	seedTask(t, d, ws, p.AgentID, taskSeed{status: "running", origin: "trigger", originID: trigger, execution: "task-closed", age: 90 * time.Second})
	open := seedTask(t, d, ws, p.AgentID, taskSeed{status: "running", origin: "trigger", originID: trigger, execution: "task-open", age: time.Minute})
	seedTask(t, d, ws, p.AgentID, taskSeed{status: "running", origin: "trigger", originID: uuid.NewString(), execution: "task-elsewhere"})

	x := workflowStatuses{by: map[string]durable.Status{
		"task-done": durable.StatusRunning, "task-closed": durable.StatusCompleted, "task-open": durable.StatusRunning, "task-elsewhere": durable.StatusRunning,
	}}
	s := NewSurface(SurfaceDeps{DB: d, Executor: x, Log: quiet(), Now: fixedNow})
	got, err := s.OpenRunFrom(ctx, ws, "trigger", trigger)
	if err != nil || got != open {
		t.Fatalf("got %q %v, want %s", got, err, open)
	}
	x.by["task-open"] = durable.StatusTerminated
	if got, err := s.OpenRunFrom(ctx, ws, "trigger", trigger); err != nil || got != "" {
		t.Fatalf("got %q %v", got, err)
	}
	unasked := NewSurface(SurfaceDeps{DB: d, Log: quiet(), Now: fixedNow})
	if got, err := unasked.OpenRunFrom(ctx, ws, "trigger", trigger); err != nil || got != gone {
		t.Fatalf("without an executor the oldest started run stands: %q %v", got, err)
	}
}

func TestRestartUndispatched(t *testing.T) {
	d := openDB(t)
	p, _ := seed(t, d)
	ws, _ := scope.NewWorkspace(p.WorkspaceID, "")
	ctx := context.Background()
	l := &fakeLauncher{}
	s := NewSurface(SurfaceDeps{DB: d, Launcher: l, Log: quiet(), Now: fixedNow})

	failed := seedTask(t, d, ws, p.AgentID, taskSeed{status: "failed", policy: true})
	if err := s.RestartUndispatched(ctx, ws, failed, "the ask again"); err != nil {
		t.Fatal(err)
	}
	if len(l.launched) != 1 || l.launched[0].Description != "the ask again" || l.launched[0].ID != failed {
		t.Fatalf("%+v", l.launched)
	}
	if n := count(t, d, p, `SELECT count(*) FROM tasks WHERE id = $1 AND status = 'running' AND execution_id = $2 AND error IS NULL AND description = 'stored ask'`, failed, "task-"+failed); n != 1 {
		t.Fatal("the restarted task is not running under its workflow with its stored ask")
	}
	if err := s.RestartUndispatched(ctx, ws, failed, "x"); err == nil {
		t.Fatal("a started task was started again")
	}
	if err := s.RestartUndispatched(ctx, ws, seedTask(t, d, ws, p.AgentID, taskSeed{status: "pending"}), "x"); err == nil {
		t.Fatal("a task with no stored policy was started")
	}

	l.fail = errors.New("temporal down")
	pending := seedTask(t, d, ws, p.AgentID, taskSeed{status: "pending", policy: true})
	if err := s.RestartUndispatched(ctx, ws, pending, "x"); !errors.Is(err, api.ErrTaskDispatchFailed) {
		t.Fatalf("got %v", err)
	}
	if n := count(t, d, p, `SELECT count(*) FROM tasks WHERE id = $1 AND status = 'failed' AND execution_id IS NULL`, pending); n != 1 {
		t.Fatal("a failed restart did not leave the task failed")
	}
}
