package store

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/projects/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/schema"
)

func openPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("AGENTAREA_DB_TEST_URL")
	if dsn == "" {
		t.Skip("AGENTAREA_DB_TEST_URL is not set")
	}
	sqlDB, err := schema.Open(dsn)
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Migrate(context.Background(), sqlDB, schema.Core()); err != nil {
		t.Fatal(err)
	}
	_ = sqlDB.Close()
	pool, err := pgxpool.New(context.Background(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	return pool
}

func workspace(t *testing.T, pool *pgxpool.Pool) db.Session {
	t.Helper()
	id := uuid.NewString()
	slug := "ws-" + id[:8]
	if _, err := pool.Exec(context.Background(),
		`INSERT INTO workspaces (id, name, owner_user_id, slug) VALUES ($1, 'W', 'owner', $2)`, id, slug); err != nil {
		t.Fatal(err)
	}
	ws, err := scope.NewWorkspace(id, slug)
	if err != nil {
		t.Fatal(err)
	}
	return db.NewSession(ws, pool)
}

func ptr(s string) *string { return &s }

func TestCreateGetListDelete(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := workspace(t, pool), workspace(t, pool)
	var p Projects
	now := time.Date(2026, 11, 12, 1, 2, 3, 123456789, time.Local)
	id := uuid.New()
	created, err := p.Create(ctx, s, id, "user-1", domain.New{Name: "Roadmap", Description: ptr("d")}, now)
	if err != nil {
		t.Fatal(err)
	}
	if created.ID != id.String() || created.WorkspaceID != s.Workspace().ID() || created.CreatedBy != "user-1" ||
		*created.Description != "d" || created.Instructions != nil || created.ParentProjectID != nil {
		t.Fatalf("created %+v", created)
	}
	var stamped time.Time
	if err := pool.QueryRow(ctx, `SELECT created_at FROM projects WHERE id = $1`, id).Scan(&stamped); err != nil {
		t.Fatal(err)
	}
	if want := time.Date(2026, 11, 12, 1, 2, 3, 123456000, time.UTC); !stamped.Equal(want) {
		t.Fatalf("created_at %v, want the naive local wall clock %v", stamped, want)
	}
	if _, ok, err := p.Get(ctx, other, id); err != nil || ok {
		t.Fatalf("another workspace sees the project: %v %v", ok, err)
	}
	if got, ok, err := p.Get(ctx, s, id); err != nil || !ok || got.Name != "Roadmap" {
		t.Fatalf("get %+v %v %v", got, ok, err)
	}
	list, err := p.List(ctx, s, 100, 0)
	if err != nil || len(list) != 1 {
		t.Fatalf("list %v %v", list, err)
	}
	if list, _ := p.List(ctx, s, 100, 1); len(list) != 0 {
		t.Fatalf("offset 1: %v", list)
	}
	if ok, err := p.Delete(ctx, other, id); err != nil || ok {
		t.Fatalf("delete from another workspace: %v %v", ok, err)
	}
	if ok, err := p.Delete(ctx, s, id); err != nil || !ok {
		t.Fatalf("delete: %v %v", ok, err)
	}
}

func TestUpdateSetsOnlyWhatIsSetAndMovesUpdatedAtOnChange(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := workspace(t, pool)
	var p Projects
	t0 := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	parent, child := uuid.New(), uuid.New()
	if _, err := p.Create(ctx, s, parent, "u", domain.New{Name: "P"}, t0); err != nil {
		t.Fatal(err)
	}
	if _, err := p.Create(ctx, s, child, "u", domain.New{Name: "C", Instructions: ptr("i")}, t0); err != nil {
		t.Fatal(err)
	}
	updatedAt := func() time.Time {
		var at time.Time
		if err := pool.QueryRow(ctx, `SELECT updated_at FROM projects WHERE id = $1`, child).Scan(&at); err != nil {
			t.Fatal(err)
		}
		return at
	}
	t1 := t0.Add(time.Hour)
	if ok, err := p.Update(ctx, s, child, domain.Patch{Name: ptr("C")}, t1); err != nil || !ok {
		t.Fatalf("no-op update: %v %v", ok, err)
	}
	if !updatedAt().Equal(t0) {
		t.Fatalf("an unchanged value moved updated_at")
	}
	parentID := parent.String()
	patch := domain.Patch{
		Description:     domain.Field{Set: true, Value: ptr("new")},
		Instructions:    domain.Field{Set: true},
		ParentProjectID: domain.Field{Set: true, Value: &parentID},
	}
	if ok, err := p.Update(ctx, s, child, patch, t1); err != nil || !ok {
		t.Fatalf("update: %v %v", ok, err)
	}
	got, _, _ := p.Get(ctx, s, child)
	if got.Name != "C" || *got.Description != "new" || got.Instructions != nil || *got.ParentProjectID != parentID {
		t.Fatalf("after update %+v", got)
	}
	if !updatedAt().Equal(t1) {
		t.Fatalf("updated_at did not move")
	}
	node, ok, err := p.Node(ctx, s, child)
	if err != nil || !ok || node.ParentProjectID == nil || *node.ParentProjectID != parentID {
		t.Fatalf("node %+v %v %v", node, ok, err)
	}
	if ok, err := p.Update(ctx, s, uuid.New(), domain.Patch{Name: ptr("x")}, t1); err != nil || ok {
		t.Fatalf("update of a missing project: %v %v", ok, err)
	}
}

func TestLinksAreIdempotentAndWorkspaceScoped(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := workspace(t, pool), workspace(t, pool)
	var p Projects
	id := uuid.New()
	if _, err := p.Create(ctx, s, id, "u", domain.New{Name: "P"}, time.Now()); err != nil {
		t.Fatal(err)
	}
	skill, agent, mcp, foreign := uuid.New(), uuid.New(), uuid.New(), uuid.New()
	ws := s.Workspace().ID()
	for _, q := range []struct {
		sql string
		id  uuid.UUID
		ws  string
	}{
		{`INSERT INTO skills (id, name, workspace_id, created_by, slug) VALUES ($1, 's', $2, 'u', 's')`, skill, ws},
		{`INSERT INTO agents (id, name, status, workspace_id, created_by, slug) VALUES ($1, 'a', 'active', $2, 'u', 'a')`, agent, ws},
		{`INSERT INTO agents (id, name, status, workspace_id, created_by, slug) VALUES ($1, 'f', 'active', $2, 'u', 'f')`, foreign, other.Workspace().ID()},
		{`INSERT INTO mcp_server_instances (id, server_spec_id, name, workspace_id, created_by, transport) VALUES ($1, 'spec', 'm', $2, 'u', 'url')`, mcp, ws},
	} {
		if _, err := pool.Exec(ctx, q.sql, q.id, q.ws); err != nil {
			t.Fatal(err)
		}
	}
	for _, l := range []struct {
		k  domain.LinkKind
		id uuid.UUID
	}{{domain.LinkSkill, skill}, {domain.LinkAgent, agent}, {domain.LinkMCPInstance, mcp}, {domain.LinkSkill, skill}} {
		if err := p.Link(ctx, s, l.k, id, l.id); err != nil {
			t.Fatal(err)
		}
	}
	if err := p.Link(ctx, other, domain.LinkAgent, id, foreign); err != nil {
		t.Fatal(err)
	}
	links, err := p.Links(ctx, s, []uuid.UUID{id})
	if err != nil {
		t.Fatal(err)
	}
	l := links[id.String()]
	if l == nil || len(l.Skills) != 1 || len(l.Agents) != 1 || len(l.MCPInstances) != 1 || l.Agents[0] != agent.String() {
		t.Fatalf("links %+v", l)
	}
	if got, err := p.AgentProjects(ctx, s, agent); err != nil || len(got) != 1 || got[0] != id {
		t.Fatalf("agent projects %v %v", got, err)
	}
	if got, err := p.AgentProjects(ctx, other, agent); err != nil || len(got) != 0 {
		t.Fatalf("agent projects seen from another workspace %v %v", got, err)
	}
	if err := p.Unlink(ctx, other, domain.LinkSkill, id, skill); err != nil {
		t.Fatal(err)
	}
	if err := p.Unlink(ctx, s, domain.LinkSkill, id, skill); err != nil {
		t.Fatal(err)
	}
	links, _ = p.Links(ctx, s, []uuid.UUID{id})
	if l := links[id.String()]; l != nil && len(l.Skills) != 0 {
		t.Fatalf("skill not unlinked: %+v", l)
	}
}
