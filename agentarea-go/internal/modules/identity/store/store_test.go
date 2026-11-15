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
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/schema"
)

func openPool(t *testing.T) *pgxpool.Pool {
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
	return pool
}

func newWorkspace(t *testing.T, pool *pgxpool.Pool, owner string) db.Session {
	t.Helper()
	var st Store
	id := uuid.NewString()
	w, err := st.InsertWorkspace(context.Background(), pool, domain.Workspace{ID: id, Slug: "ws-" + id[:8], Name: "W", OwnerUserID: owner})
	if err != nil {
		t.Fatal(err)
	}
	ws, err := scope.NewWorkspace(w.ID, w.Slug)
	if err != nil {
		t.Fatal(err)
	}
	return db.NewSession(ws, pool)
}

func TestWorkspaceSlugAndOwnership(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	var st Store
	owner := "owner-" + uuid.NewString()
	s := newWorkspace(t, pool, owner)
	taken, err := st.SlugTaken(ctx, pool, s.Workspace().Slug())
	if err != nil || !taken {
		t.Fatalf("slug taken = %v %v", taken, err)
	}
	if taken, _ := st.SlugTaken(ctx, pool, "free-"+uuid.NewString()[:8]); taken {
		t.Fatal("a free slug reads as taken")
	}
	_, err = st.InsertWorkspace(ctx, pool, domain.Workspace{ID: uuid.NewString(), Slug: s.Workspace().Slug(), Name: "W", OwnerUserID: owner})
	if err == nil {
		t.Fatal("a duplicate slug was inserted")
	}
	ids, err := st.OwnedWorkspaceIDs(ctx, pool, owner)
	if err != nil || len(ids) != 1 || ids[0] != s.Workspace().ID() {
		t.Fatalf("owned %v %v", ids, err)
	}
}

func TestInvitationAcceptAndAdmit(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	var st Store
	s := newWorkspace(t, pool, "owner")
	email := "a@b.co"
	now := time.Date(2026, 11, 12, 1, 0, 0, 0, time.UTC)
	hash := uuid.NewString()[:32] + uuid.NewString()[:32]
	inv, err := st.InsertInvitation(ctx, s, uuid.New(), &email, hash, "owner", now.AddDate(0, 0, 7), now)
	if err != nil {
		t.Fatal(err)
	}
	if inv.Status != domain.StatusPending || *inv.Email != email || !inv.ExpiresAt.Equal(now.AddDate(0, 0, 7)) || inv.AcceptedAt != nil {
		t.Fatalf("inserted %+v", inv)
	}
	found, ok, err := st.InvitationByTokenHash(ctx, pool, hash)
	if err != nil || !ok || found.ID != inv.ID {
		t.Fatalf("by hash %+v %v %v", found, ok, err)
	}
	if _, ok, _ := st.InvitationByTokenHash(ctx, pool, "nope"); ok {
		t.Fatal("unknown hash found")
	}
	id := uuid.MustParse(inv.ID)
	if granted, err := st.AddForInvitation(ctx, pool, id, s.Workspace().ID(), "member", now, now); err != nil || granted {
		t.Fatalf("a pending invitation admitted: %v %v", granted, err)
	}
	if err := st.MarkAccepted(ctx, pool, id, "member", now, now); err != nil {
		t.Fatal(err)
	}
	if granted, err := st.AddForInvitation(ctx, pool, id, s.Workspace().ID(), "someone-else", now, now); err != nil || granted {
		t.Fatalf("another user admitted: %v %v", granted, err)
	}
	for range 2 {
		if granted, err := st.AddForInvitation(ctx, pool, id, s.Workspace().ID(), "member", now, now); err != nil || !granted {
			t.Fatalf("admit: %v %v", granted, err)
		}
	}
	var rows int
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM workspace_memberships WHERE workspace_id = $1 AND user_id = 'member'`, s.Workspace().ID()).Scan(&rows); err != nil || rows != 1 {
		t.Fatalf("memberships %d %v", rows, err)
	}
	if ok, err := st.MembershipExists(ctx, pool, s.Workspace().ID(), "member"); err != nil || !ok {
		t.Fatalf("membership exists %v %v", ok, err)
	}
	found, _, _ = st.InvitationByTokenHash(ctx, pool, hash)
	if found.Status != domain.StatusAccepted || *found.AcceptedByUserID != "member" || found.MembershipGrantedAt == nil {
		t.Fatalf("after admit %+v", found)
	}
}

func TestInsertAPIKey(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	var st Store
	s := newWorkspace(t, pool, "owner")
	now := time.Date(2026, 11, 12, 1, 0, 0, 0, time.UTC)
	k, err := st.InsertAPIKey(ctx, s, NewAPIKey{ID: uuid.New(), CreatedBy: "owner", Name: "ci", TokenHash: "h" + uuid.NewString(), TokenPrefix: "aat_abcdefgh"}, now)
	if err != nil {
		t.Fatal(err)
	}
	if !k.IsActive || k.AccessCount != 0 || k.ExpiresAt != nil || k.LastAccessedAt != nil || k.AgentID != nil || !k.CreatedAt.Equal(now) {
		t.Fatalf("key %+v", k)
	}
}
