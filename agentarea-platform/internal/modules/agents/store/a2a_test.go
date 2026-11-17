package store

import (
	"context"
	"testing"

	"github.com/google/uuid"
)

func TestA2AAgentReadsAcrossWorkspaces(t *testing.T) {
	ctx := context.Background()
	pool, s, _ := session(t)
	id := uuid.New()
	if _, err := pool.Exec(ctx, `INSERT INTO agents (id, name, description, status, workspace_id, created_by, slug, tools, planning, a2ui_enabled)
		VALUES ($1, 'Helper', NULL, 'archived', $2, 'u', 'h', '[{"tool_type":"mcp"}]', true, true)`, id, s.Workspace().ID()); err != nil {
		t.Fatal(err)
	}
	a, ok, err := A2AAgent(ctx, pool, id)
	if err != nil || !ok {
		t.Fatalf("%v %v", ok, err)
	}
	if a.ID != id.String() || a.WorkspaceID != s.Workspace().ID() || a.Status != "archived" || a.Description != nil ||
		a.Planning == nil || !*a.Planning || a.A2UIEnabled == nil || !*a.A2UIEnabled || string(a.Tools) == "" {
		t.Errorf("%+v", a)
	}
	if _, ok, err := A2AAgent(ctx, pool, uuid.New()); ok || err != nil {
		t.Fatalf("unknown agent: %v %v", ok, err)
	}
}
