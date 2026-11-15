package service

import (
	"context"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
)

func TestStandingReadsStatusAndSavedTaskInTheWorkspace(t *testing.T) {
	d := clientOpenDB(t)
	ctx := context.Background()
	ws, _ := scope.NewWorkspace(uuid.NewString(), "")
	other, _ := scope.NewWorkspace(uuid.NewString(), "")
	active, archived, def := uuid.NewString(), uuid.NewString(), uuid.NewString()
	if err := d.Write(ctx, ws, func(ctx context.Context, s db.Session) error {
		for id, status := range map[string]string{active: "active", archived: "archived"} {
			if _, err := s.Q().Exec(ctx, `INSERT INTO agents (id, name, status, workspace_id, created_by, slug) VALUES ($1, 'A', $2, $3, 'u', $4)`,
				id, status, ws.ID(), "a-"+id[:8]); err != nil {
				return err
			}
		}
		_, err := s.Q().Exec(ctx, `INSERT INTO task_definitions (id, name, description, agent_id, parameters, workspace_id, created_by, created_at, updated_at)
			VALUES ($1, 'Digest', 'Summarise the day', $2, '{"k": 1}', $3, 'u', now(), now())`, def, active, ws.ID())
		return err
	}); err != nil {
		t.Fatal(err)
	}
	l := &Lookup{DB: d}
	var s api.Standing = l
	if st, ok, err := s.AgentStatus(ctx, ws, active); err != nil || !ok || st != api.StatusActive {
		t.Fatalf("%q %v %v", st, ok, err)
	}
	if st, ok, err := s.AgentStatus(ctx, ws, archived); err != nil || !ok || st != api.StatusArchived {
		t.Fatalf("%q %v %v", st, ok, err)
	}
	for _, c := range []struct {
		ws scope.Workspace
		id string
	}{{other, active}, {ws, uuid.NewString()}, {ws, "not-a-uuid"}} {
		if _, ok, err := s.AgentStatus(ctx, c.ws, c.id); ok || err != nil {
			t.Fatalf("%v: %v %v", c, ok, err)
		}
	}
	got, ok, err := s.TaskDefinition(ctx, ws, def)
	if err != nil || !ok || got.Description != "Summarise the day" || string(got.Parameters) != `{"k": 1}` || got.AgentID != active {
		t.Fatalf("%+v %v %v", got, ok, err)
	}
	if _, ok, err := s.TaskDefinition(ctx, other, def); ok || err != nil {
		t.Fatalf("another workspace reads the saved task: %v %v", ok, err)
	}
	if _, ok, err := s.TaskDefinition(ctx, ws, "x"); ok || err != nil {
		t.Fatalf("%v %v", ok, err)
	}
}
