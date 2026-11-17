package store

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/domain"
)

func ownExit(t *testing.T, s db.Session, name string) domain.EgressExit {
	t.Helper()
	e, err := EgressExits{}.Create(context.Background(), s, domain.EgressExit{ID: uuid.NewString(), Name: name,
		UpstreamURL: ptr("https://proxy.example.com:443"), CreatedBy: "member"}, time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	return e
}

func platformExit(t *testing.T, pool *pgxpool.Pool) uuid.UUID {
	t.Helper()
	ws, err := scope.NewWorkspace("platform", "")
	if err != nil {
		t.Fatal(err)
	}
	id := uuid.New()
	if err := DeclareEgressExit(context.Background(), db.NewSession(ws, pool),
		api.DeclaredEgressExit{ID: id, Name: "hop-" + id.String()[:8], Via: "hop-a"}, "platform", time.Now()); err != nil {
		t.Fatal(err)
	}
	return id
}

func TestAWorkspaceSeesOnlyTheExitsItCreated(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	tenant, other := workspace(t, pool), workspace(t, pool)
	older := ownExit(t, tenant, "office")
	foreign := ownExit(t, other, "office")
	platform := platformExit(t, pool)
	newer, err := EgressExits{}.Create(ctx, tenant, domain.EgressExit{ID: uuid.NewString(), Name: "home",
		UpstreamURL: ptr("socks5://1.2.3.4:1080"), Username: ptr("u"), AllowPlaintextCredentials: true, CreatedBy: "member"},
		time.Date(2026, 1, 3, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	if newer.WorkspaceID != tenant.Workspace().ID() || newer.CreatedBy != "member" || !newer.AllowPlaintextCredentials ||
		newer.ManagedBy != nil || newer.IsPlatform() || !newer.CreatedAt.Equal(newer.UpdatedAt) {
		t.Fatalf("created %+v", newer)
	}

	listed, err := EgressExits{}.List(ctx, tenant)
	if err != nil {
		t.Fatal(err)
	}
	if len(listed) != 2 || listed[0].ID != newer.ID || listed[1].ID != older.ID {
		t.Fatalf("listed %+v, want the workspace's own, newest first", listed)
	}
	for _, id := range []string{foreign.ID, platform.String()} {
		if _, found, err := (EgressExits{}).Get(ctx, tenant, uuid.MustParse(id)); err != nil || found {
			t.Fatalf("tenant sees exit %s: %v %v", id, found, err)
		}
	}
	got, found, err := EgressExits{}.Get(ctx, tenant, uuid.MustParse(older.ID))
	if err != nil || !found || got.Name != "office" || *got.UpstreamURL != "https://proxy.example.com:443" {
		t.Fatalf("get %+v %v %v", got, found, err)
	}
}

func TestNoTenantEditsOrDeletesAPlatformExit(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	tenant := workspace(t, pool)
	platform := platformExit(t, pool)

	_, updated, err := EgressExits{}.Update(ctx, tenant, platform, EgressExitChanges{"upstream_url": ptr("http://attacker:3128")}, time.Now())
	if err != nil || updated {
		t.Fatalf("update %v %v", updated, err)
	}
	if deleted, err := (EgressExits{}).Delete(ctx, tenant, platform); err != nil || deleted {
		t.Fatalf("delete %v %v", deleted, err)
	}
	var upstream *string
	if err := pool.QueryRow(ctx, `SELECT upstream_url FROM egress_exits WHERE id = $1`, platform).Scan(&upstream); err != nil || upstream != nil {
		t.Fatalf("platform exit changed: %v %v", upstream, err)
	}
}

func TestAnUpdateWritesTheChangedColumnsAndADeleteRemovesTheRow(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	tenant := workspace(t, pool)
	e := ownExit(t, tenant, "office")
	later := time.Date(2026, 2, 1, 0, 0, 0, 0, time.UTC)
	up, ok, err := EgressExits{}.Update(ctx, tenant, uuid.MustParse(e.ID),
		EgressExitChanges{"description": ptr("the office"), "username": nil, "allow_plaintext_credentials": true}, later)
	if err != nil || !ok || *up.Description != "the office" || up.Username != nil || !up.AllowPlaintextCredentials ||
		!up.UpdatedAt.Equal(later) || !up.CreatedAt.Equal(e.CreatedAt) {
		t.Fatalf("update %+v %v %v", up, ok, err)
	}
	if _, _, err := (EgressExits{}).Update(ctx, tenant, uuid.MustParse(e.ID), EgressExitChanges{"managed_by": ptr("platform")}, later); err == nil {
		t.Fatal("an update wrote a column no patch may name")
	}
	if deleted, err := (EgressExits{}).Delete(ctx, tenant, uuid.MustParse(e.ID)); err != nil || !deleted {
		t.Fatalf("delete %v %v", deleted, err)
	}
	if _, found, _ := (EgressExits{}).Get(ctx, tenant, uuid.MustParse(e.ID)); found {
		t.Fatal("the deleted exit is still there")
	}
}

func TestOnlyAPlatformExitMayLeaveWithoutAnUpstream(t *testing.T) {
	pool := openPool(t)
	tenant := workspace(t, pool)
	_, err := EgressExits{}.Create(context.Background(), tenant, domain.EgressExit{ID: uuid.NewString(), Name: "hop",
		Via: ptr("hop-a"), CreatedBy: "member"}, time.Now())
	if err == nil || !strings.Contains(err.Error(), "ck_egress_exits_route") {
		t.Fatalf("create without an upstream: %v", err)
	}
}
