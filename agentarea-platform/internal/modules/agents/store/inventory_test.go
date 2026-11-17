package store

import (
	"context"
	"testing"

	"github.com/google/uuid"
)

func TestInventoryAgentsLeavesOutArchivedAndHarnessAgents(t *testing.T) {
	ctx := context.Background()
	pool, s, _ := session(t)
	ws := s.Workspace().ID()
	active, archived, harness, client := uuid.New(), uuid.New(), uuid.New(), uuid.New()
	if _, err := pool.Exec(ctx, `INSERT INTO clients (id, created_at, updated_at, workspace_id, created_by, name)
		VALUES ($1, now(), now(), $2, 'u', 'Laptop')`, client, ws); err != nil {
		t.Fatal(err)
	}
	for _, r := range []struct {
		id     uuid.UUID
		status string
		client any
	}{{active, "active", nil}, {archived, "archived", nil}, {harness, "active", client}} {
		if _, err := pool.Exec(ctx, `INSERT INTO agents (id, name, status, workspace_id, created_by, slug, harness_client_id)
			VALUES ($1, 'A', $2, $3, 'u', $4, $5)`, r.id, r.status, ws, r.id.String(), r.client); err != nil {
			t.Fatal(err)
		}
	}
	listed, err := New(s.Q()).InventoryAgents(ctx, InventoryAgentsParams{WorkspaceID: ws})
	if err != nil || len(listed) != 1 || listed[0].ID != active {
		t.Fatalf("working set %v %v", listed, err)
	}
	all, err := New(s.Q()).InventoryAgents(ctx, InventoryAgentsParams{WorkspaceID: ws, IncludeArchived: true})
	if err != nil || len(all) != 3 {
		t.Fatalf("all %v %v", all, err)
	}
}

func TestMoveSkillForksKeepsOneForkPerWorkspace(t *testing.T) {
	ctx := context.Background()
	pool, s, other := session(t)
	oldItem, newItem := uuid.New(), uuid.New()
	forkA, forkB, heldNew := uuid.New(), uuid.New(), uuid.New()
	insert := func(id uuid.UUID, ws string, item uuid.UUID) {
		if _, err := pool.Exec(ctx, `INSERT INTO skills (id, name, description, workspace_id, created_by, slug, source_type, registry_item_id)
			VALUES ($1, 'S', '', $2, 'u', $3, 'catalog', $4)`, id, ws, id.String(), item); err != nil {
			t.Fatal(err)
		}
	}
	insert(forkA, s.Workspace().ID(), oldItem)
	insert(forkB, other.Workspace().ID(), oldItem)
	insert(heldNew, other.Workspace().ID(), newItem)
	n, err := New(s.Q()).MoveSkillForks(ctx, MoveSkillForksParams{OldID: oldItem, NewID: newItem})
	if err != nil || n != 1 {
		t.Fatalf("moved %d %v", n, err)
	}
	refs, err := New(s.Q()).SkillReferencedItems(ctx, []uuid.UUID{oldItem, newItem, uuid.New()})
	if err != nil || len(refs) != 2 {
		t.Fatalf("referenced %v %v", refs, err)
	}
}
