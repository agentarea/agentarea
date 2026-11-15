package store

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestA2ACountsAnAgentsTasksInItsWorkspace(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := workspace(t, pool), workspace(t, pool)
	agent := uuid.New()
	makeSurfaceTask(t, s, agent, "a", "running")
	makeSurfaceTask(t, s, agent, "b", "completed")
	makeSurfaceTask(t, s, uuid.New(), "c", "completed")
	makeSurfaceTask(t, other, agent, "d", "completed")
	n, err := A2ACountAgentTasks(ctx, s, agent)
	if err != nil || n != 2 {
		t.Fatalf("%d %v", n, err)
	}
}

func TestA2ASetParametersReplacesTheTasksParameters(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := workspace(t, pool), workspace(t, pool)
	id := makeSurfaceTask(t, s, uuid.New(), "a", "running")
	params := map[string]any{"a2a_push_configs": []any{map[string]any{"id": "c1", "url": "https://hooks.example/a"}}}
	if err := A2ASetParameters(ctx, other, id, params, time.Now()); err != nil {
		t.Fatal(err)
	}
	row, err := New(s.Q()).SurfaceTask(ctx, SurfaceTaskParams{ID: id, WorkspaceID: s.Workspace().ID()})
	if err != nil {
		t.Fatalf("%v %q", err, row.Parameters)
	}
	var untouched map[string]any
	if err := json.Unmarshal([]byte(row.Parameters), &untouched); err != nil || untouched["a2a_push_configs"] != nil {
		t.Fatalf("another workspace's write reached the task: %q", row.Parameters)
	}
	if err := A2ASetParameters(ctx, s, id, params, time.Now()); err != nil {
		t.Fatal(err)
	}
	row, err = New(s.Q()).SurfaceTask(ctx, SurfaceTaskParams{ID: id, WorkspaceID: s.Workspace().ID()})
	if err != nil {
		t.Fatal(err)
	}
	var got map[string]any
	if err := json.Unmarshal([]byte(row.Parameters), &got); err != nil {
		t.Fatal(err)
	}
	configs, _ := got["a2a_push_configs"].([]any)
	if len(configs) != 1 {
		t.Fatalf("%q", row.Parameters)
	}
}

func TestA2AFeedEndIsMinusOneForAnEmptyLog(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := workspace(t, pool)
	id := makeSurfaceTask(t, s, uuid.New(), "a", "running")
	n, err := A2AFeedEnd(ctx, s, id)
	if err != nil || n != -1 {
		t.Fatalf("%d %v", n, err)
	}
}
