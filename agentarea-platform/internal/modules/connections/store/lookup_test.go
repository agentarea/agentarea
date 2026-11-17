package store

import (
	"context"
	"os"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/schema"
)

func session(t *testing.T) (*pgxpool.Pool, db.Session, db.Session) {
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
	mk := func() db.Session {
		ws, err := scope.NewWorkspace(uuid.NewString(), "ws-"+uuid.NewString()[:8])
		if err != nil {
			t.Fatal(err)
		}
		return db.NewSession(ws, pool)
	}
	return pool, mk(), mk()
}

func TestLookupSeesTheWorkspaceAndPlatformInstances(t *testing.T) {
	ctx := context.Background()
	pool, s, other := session(t)
	own, platform := uuid.New(), uuid.New()
	insert := `INSERT INTO mcp_server_instances (id, server_spec_id, name, workspace_id, created_by, transport, managed_by) VALUES ($1, 'spec', $2, $3, 'u', 'url', $4)`
	if _, err := pool.Exec(ctx, insert, own, "Own", s.Workspace().ID(), "user"); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, insert, platform, "Shared", other.Workspace().ID(), "platform"); err != nil {
		t.Fatal(err)
	}
	var l Lookup
	if ok, _ := l.MCPInstanceExists(ctx, other, own); ok {
		t.Fatal("another workspace sees the instance")
	}
	names, err := l.MCPInstanceNames(ctx, s, []uuid.UUID{own, platform})
	if err != nil || names[own] != "Own" || names[platform] != "Shared" {
		t.Fatalf("names %v %v", names, err)
	}
}
