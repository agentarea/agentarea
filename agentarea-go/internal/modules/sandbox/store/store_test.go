package store

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/schema"
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

func session(t *testing.T, pool *pgxpool.Pool) db.Session {
	t.Helper()
	id := uuid.NewString()
	ws, err := scope.NewWorkspace(id, "ws-"+id[:8])
	if err != nil {
		t.Fatal(err)
	}
	return db.NewSession(ws, pool)
}

func ptr(s string) *string { return &s }

func TestEventsInsertAndHistory(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := session(t, pool), session(t, pool)
	var e Events
	t0 := time.Date(2026, 11, 12, 1, 2, 3, 123456789, time.FixedZone("MSK", 3*3600))
	for i, ev := range []domain.ArtifactEvent{
		{Path: "a.txt", Action: domain.ActionCreated, ActorType: domain.ActorUser, CreatedBy: "u1", CreatedAt: t0},
		{Path: "a.txt", Action: domain.ActionModified, ActorType: domain.ActorAgent, CreatedBy: "u1", AgentID: ptr("ag"), TaskID: ptr("tk"), CreatedAt: t0.Add(time.Second)},
		{Path: "b.txt", Action: domain.ActionCreated, ActorType: domain.ActorUser, CreatedBy: "u1", CreatedAt: t0},
	} {
		if err := e.Insert(ctx, s, ev); err != nil {
			t.Fatal(i, err)
		}
	}
	if err := e.Insert(ctx, other, domain.ArtifactEvent{Path: "a.txt", Action: domain.ActionDeleted, ActorType: domain.ActorUser, CreatedBy: "u2", CreatedAt: t0}); err != nil {
		t.Fatal(err)
	}
	got, err := e.History(ctx, s, "a.txt")
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 || got[0].Action != domain.ActionModified || *got[0].AgentID != "ag" || *got[0].TaskID != "tk" ||
		got[1].Action != domain.ActionCreated || got[1].AgentID != nil {
		t.Fatalf("history %+v", got)
	}
	if want := time.Date(2026, 11, 11, 22, 2, 4, 123456000, time.UTC); !got[0].CreatedAt.Equal(want) {
		t.Fatalf("created_at %v, want the UTC wall clock %v", got[0].CreatedAt, want)
	}
	none, err := e.History(ctx, s, "missing")
	if err != nil || len(none) != 0 {
		t.Fatalf("%v %v", none, err)
	}
}

func TestEventsRenameCarriesHistory(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := session(t, pool), session(t, pool)
	var e Events
	t0 := time.Date(2026, 11, 12, 9, 0, 0, 0, time.UTC)
	for _, sess := range []db.Session{s, other} {
		if err := e.Insert(ctx, sess, domain.ArtifactEvent{Path: "a.txt", Action: domain.ActionCreated, ActorType: domain.ActorUser, CreatedBy: "u1", CreatedAt: t0}); err != nil {
			t.Fatal(err)
		}
	}
	if err := e.Rename(ctx, s, "a.txt", "b.txt", t0.Add(time.Minute)); err != nil {
		t.Fatal(err)
	}
	moved, err := e.History(ctx, s, "b.txt")
	if err != nil || len(moved) != 1 || moved[0].Action != domain.ActionCreated || !moved[0].CreatedAt.Equal(t0) {
		t.Fatalf("b.txt history %+v %v", moved, err)
	}
	if left, err := e.History(ctx, s, "a.txt"); err != nil || len(left) != 0 {
		t.Fatalf("a.txt history %+v %v", left, err)
	}
	if kept, err := e.History(ctx, other, "a.txt"); err != nil || len(kept) != 1 {
		t.Fatalf("another workspace's history moved: %+v %v", kept, err)
	}
}
