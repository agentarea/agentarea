package store

import (
	"context"
	"errors"
	"slices"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestUndispatchedLaunchCycle(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := workspace(t, pool), workspace(t, pool)
	var r Runs
	now := time.Now().UTC()
	at := func(status, origin string, age time.Duration, execution *string) string {
		id := uuid.NewString()
		if err := r.CreateTask(ctx, s, NewTask{
			ID: id, AgentID: uuid.NewString(), Description: "d", Status: status, CreatedBy: "user-1",
			Metadata: map[string]any{"governance_snapshot": map[string]any{"effective_policy": map[string]any{}}}, OriginType: origin,
		}, now); err != nil {
			t.Fatal(err)
		}
		if _, err := pool.Exec(ctx, `UPDATE tasks SET created_at = $2, execution_id = $3 WHERE id = $1`, id, now.Add(-age), execution); err != nil {
			t.Fatal(err)
		}
		return id
	}
	started := "task-x"
	stale := at("pending", "agent", 5*time.Minute, nil)
	fresh := at("pending", "agent", 30*time.Second, nil)
	old := at("pending", "agent", 48*time.Hour, nil)
	trig := at("pending", "trigger", 5*time.Minute, nil)
	running := at("running", "agent", 5*time.Minute, nil)
	dispatched := at("pending", "agent", 5*time.Minute, &started)

	found, err := FindUndispatched(ctx, pool, now.Add(-2*time.Minute), now.Add(-24*time.Hour), 1000)
	if err != nil {
		t.Fatal(err)
	}
	var ids []string
	for _, f := range found {
		ids = append(ids, f.ID)
		if f.ID == stale && (f.WorkspaceID != s.Workspace().ID() || f.Owner != "user-1") {
			t.Fatalf("%+v", f)
		}
	}
	if !slices.Contains(ids, stale) {
		t.Fatalf("stale pending task not found in %v", ids)
	}
	for _, id := range []string{fresh, old, trig, running, dispatched} {
		if slices.Contains(ids, id) {
			t.Fatalf("%s listed", id)
		}
	}

	task, err := r.TaskToLaunch(ctx, s, stale)
	if err != nil || task.Status != "pending" || task.ExecutionID != "" || task.Metadata["governance_snapshot"] == nil {
		t.Fatalf("%+v %v", task, err)
	}
	if _, err := r.TaskToLaunch(ctx, other, stale); !errors.Is(err, ErrTaskNotFound) {
		t.Fatalf("another workspace reads it: %v", err)
	}
	if ok, err := r.MarkLaunched(ctx, other, stale, "running", "task-"+stale, now); ok || err != nil {
		t.Fatalf("another workspace marked it: %v %v", ok, err)
	}
	for range 2 {
		if ok, err := r.MarkLaunched(ctx, s, stale, "running", "task-"+stale, now.Add(time.Minute)); !ok || err != nil {
			t.Fatalf("%v %v", ok, err)
		}
	}
	task, _ = r.TaskToLaunch(ctx, s, stale)
	var startedAt time.Time
	if err := pool.QueryRow(ctx, `SELECT started_at FROM tasks WHERE id = $1`, stale).Scan(&startedAt); err != nil {
		t.Fatal(err)
	}
	if task.Status != "running" || task.ExecutionID != "task-"+stale || startedAt.IsZero() {
		t.Fatalf("%+v %v", task, startedAt)
	}
}
