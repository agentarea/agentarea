package service

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/google/uuid"

	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

func TestBundleTasksWriteSavedTasks(t *testing.T) {
	ctx := context.Background()
	d, g, s, c := clientSetup(t)
	agent, other := uuid.New(), uuid.New()
	for _, a := range []uuid.UUID{agent, other} {
		clientExec(t, d, c.Workspace, `INSERT INTO agents (id, name, status, workspace_id, created_by, slug) VALUES ($1, 'A', 'active', $2, 'u', $3)`,
			a, c.Workspace.ID(), a.String())
	}
	b := BundleTasks{X: NewTaskDefs(s, TaskDefPorts{Triggers: taskDefFakeTriggers{}})}
	id, err := b.CreateTask(ctx, c, catalogapi.BundleTaskSpec{Name: "Weekly", Prompt: "Write the report", AgentID: agent.String(),
		Parameters: map[string]any{"week": "current"}})
	if err != nil {
		t.Fatal(err)
	}
	if name, ok, err := b.TaskName(ctx, c, id); !ok || err != nil || name != "Weekly" {
		t.Fatalf("name = %q %v %v", name, ok, err)
	}
	if err := b.UpdateTask(ctx, c, id, catalogapi.BundleTaskSpec{Name: "Monthly", Prompt: "Write it monthly", AgentID: other.String()}); err != nil {
		t.Fatal(err)
	}
	row, err := b.X.Get(ctx, c, uuid.MustParse(id))
	var params map[string]any
	if err != nil || row.Name != "Monthly" || row.Description != "Write it monthly" || row.AgentID != other ||
		json.Unmarshal(row.Parameters, &params) != nil || len(params) != 0 {
		t.Fatalf("row = %+v, %v", row, err)
	}
	g.mu.Lock()
	g.deny[id] = true
	g.mu.Unlock()
	var refusal *catalogapi.BundleRefusal
	if err := b.UpdateTask(ctx, c, id, catalogapi.BundleTaskSpec{Name: "x", Prompt: "y", AgentID: other.String()}); !errors.As(err, &refusal) ||
		refusal.Msg != "you may not edit task definition "+id {
		t.Fatalf("denied update: %v", err)
	}
	if _, err := b.CreateTask(ctx, c, catalogapi.BundleTaskSpec{Name: "x", Prompt: "y", AgentID: uuid.NewString()}); !errors.As(err, &refusal) {
		t.Fatalf("unknown agent: %v", err)
	}
	if err := b.DeleteTask(ctx, c, id); err != nil {
		t.Fatal(err)
	}
	if _, ok, err := b.TaskName(ctx, c, id); ok || err != nil {
		t.Fatalf("after delete: %v %v", ok, err)
	}
}

func TestBundleTasksFindsSavedTasksByName(t *testing.T) {
	ctx := context.Background()
	d, _, s, c := clientSetup(t)
	agent := uuid.New()
	clientExec(t, d, c.Workspace, `INSERT INTO agents (id, name, status, workspace_id, created_by, slug) VALUES ($1, 'A', 'active', $2, 'u', $3)`,
		agent, c.Workspace.ID(), agent.String())
	b := BundleTasks{X: NewTaskDefs(s, TaskDefPorts{})}
	id, err := b.CreateTask(ctx, c, catalogapi.BundleTaskSpec{Name: "Report", Prompt: "go", AgentID: agent.String()})
	if err != nil {
		t.Fatal(err)
	}
	refs, err := b.TaskNamed(ctx, c, "Report")
	if err != nil || len(refs) != 1 || refs[0].ID != id || refs[0].AgentID != agent.String() {
		t.Fatalf("refs = %+v, %v", refs, err)
	}
	if refs, err := b.TaskNamed(ctx, c, "Other"); err != nil || len(refs) != 0 {
		t.Fatalf("other = %+v, %v", refs, err)
	}
}
