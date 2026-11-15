package store

import (
	"context"
	"os"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/schema"
)

func session(t *testing.T) (*pgxpool.Pool, db.Session, db.Session) {
	t.Helper()
	dsn := os.Getenv("AGENTAREA_TEST_POSTGRES_URL")
	if dsn == "" {
		t.Skip("AGENTAREA_TEST_POSTGRES_URL is not set")
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
	mk := func() db.Session {
		ws, err := scope.NewWorkspace(uuid.NewString(), "ws-"+uuid.NewString()[:8])
		if err != nil {
			t.Fatal(err)
		}
		return db.NewSession(ws, pool)
	}
	return pool, mk(), mk()
}

func TestLookupSeesOnlyTheWorkspace(t *testing.T) {
	ctx := context.Background()
	pool, s, other := session(t)
	agent, skill := uuid.New(), uuid.New()
	if _, err := pool.Exec(ctx, `INSERT INTO agents (id, name, status, workspace_id, created_by, slug) VALUES ($1, 'Helper', 'active', $2, 'u', 'h')`, agent, s.Workspace().ID()); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, `INSERT INTO skills (id, name, workspace_id, created_by, slug) VALUES ($1, 'Search', $2, 'u', 's')`, skill, s.Workspace().ID()); err != nil {
		t.Fatal(err)
	}
	var l Lookup
	if ok, err := l.AgentExists(ctx, s, agent); err != nil || !ok {
		t.Fatalf("agent exists %v %v", ok, err)
	}
	if ok, _ := l.AgentExists(ctx, other, agent); ok {
		t.Fatal("another workspace sees the agent")
	}
	if ok, _ := l.SkillExists(ctx, s, skill); !ok {
		t.Fatal("skill not found")
	}
	names, err := l.AgentNames(ctx, s, []uuid.UUID{agent, uuid.New()})
	if err != nil || len(names) != 1 || names[agent] != "Helper" {
		t.Fatalf("agent names %v %v", names, err)
	}
	if names, _ := l.SkillNames(ctx, other, []uuid.UUID{skill}); len(names) != 0 {
		t.Fatalf("skill names across workspaces %v", names)
	}
}
