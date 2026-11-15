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
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
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

// insertConnection writes an openapi_connections row the way the (unported)
// create path does, so the reads have something to read.
func insertConnection(t *testing.T, pool *pgxpool.Pool, ws db.Session, name string, managed *string, headers string) uuid.UUID {
	t.Helper()
	id := uuid.New()
	if _, err := pool.Exec(context.Background(), `
		INSERT INTO openapi_connections (id, workspace_id, created_by, name, description, base_url,
			custom_headers, url_variables, available_tools, status, managed_by, created_at, updated_at)
		VALUES ($1, $2, 'u1', $3, 'd', 'https://api.example.test', $4::json, '[]', '[]', 'active', $5, now(), now())`,
		id, ws.Workspace().ID(), name, headers, managed); err != nil {
		t.Fatal(err)
	}
	return id
}

func TestAuthConfigCRUD(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := workspace(t, pool), workspace(t, pool)
	a := Auth{}
	id := uuid.New()
	now := time.Now()
	created, err := a.Insert(ctx, s, id, "u1", domain.AuthConfigNew{Name: "key", AuthType: "api_key",
		Config: map[string]any{"header_name": "X-Key", "n": 3}}, now)
	if err != nil {
		t.Fatal(err)
	}
	if created.Name != "key" || created.Config["header_name"] != "X-Key" || created.SecretKey != nil {
		t.Fatalf("created = %+v", created)
	}
	if err := a.SetSecretKey(ctx, s, id, domain.SecretKeyFor(id.String()), now); err != nil {
		t.Fatal(err)
	}
	got, ok, err := a.Get(ctx, s, id)
	if err != nil || !ok || got.SecretKey == nil || *got.SecretKey != "mcp_auth_cred:"+id.String() {
		t.Fatalf("get = %+v ok=%v err=%v", got, ok, err)
	}
	if _, ok, _ := a.Get(ctx, other, id); ok {
		t.Fatal("another workspace reads the auth config")
	}
	if err := a.Update(ctx, s, id, ptr("renamed"), nil, nil, now); err != nil {
		t.Fatal(err)
	}
	got, _, _ = a.Get(ctx, s, id)
	if got.Name != "renamed" || got.Description != nil || got.Config["header_name"] != "X-Key" {
		t.Fatalf("partial update changed other fields: %+v", got)
	}
	list, err := a.List(ctx, s)
	if err != nil || len(list) != 1 {
		t.Fatalf("list = %d err=%v", len(list), err)
	}
	insts, err := a.LinkedInstances(ctx, s, id)
	if err != nil || len(insts) != 0 {
		t.Fatalf("linked = %v err=%v", insts, err)
	}
	if ok, err := a.Delete(ctx, other, id); err != nil || ok {
		t.Fatalf("another workspace deleted the config: ok=%v err=%v", ok, err)
	}
	if ok, err := a.Delete(ctx, s, id); err != nil || !ok {
		t.Fatalf("delete ok=%v err=%v", ok, err)
	}
}

func TestOAuthLinkCRUD(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := workspace(t, pool)
	inst := uuid.New()
	if _, err := pool.Exec(ctx, `INSERT INTO mcp_server_instances (id, server_spec_id, name, json_spec, workspace_id,
		created_by, transport, verification) VALUES ($1, '', 'i', '{}', $2, 'u1', 'url', '{}')`, inst, s.Workspace().ID()); err != nil {
		t.Fatal(err)
	}
	l := Links{}
	now := time.Now()
	exp := now.Add(time.Hour)
	created, err := l.Insert(ctx, s, uuid.New(), "u1", inst, uuid.NewString(), "workspace", map[string]any{"provider": "x"}, &exp, now)
	if err != nil {
		t.Fatal(err)
	}
	if !created.IsActive || created.ExpiresAt == nil || created.ProviderConfig["provider"] != "x" {
		t.Fatalf("created = %+v", created)
	}
	rows, err := l.List(ctx, s, inst)
	if err != nil || len(rows) != 1 {
		t.Fatalf("list = %d err=%v", len(rows), err)
	}
	if ok, err := l.Deactivate(ctx, s, uuid.MustParse(created.ID), now); err != nil || !ok {
		t.Fatalf("deactivate ok=%v err=%v", ok, err)
	}
	got, ok, err := l.Get(ctx, s, uuid.MustParse(created.ID))
	if err != nil || !ok || got.IsActive {
		t.Fatalf("get after revoke = %+v ok=%v err=%v", got, ok, err)
	}
}

func TestOpenAPIReadsAndLookups(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := workspace(t, pool), workspace(t, pool)
	own := insertConnection(t, pool, s, "alpha", nil, `[{"name":"X-Key","secret":true},{"name":"Accept","secret":false,"value":"json"}]`)
	platform := insertConnection(t, pool, other, "beta", ptr("platform"), "[]")
	hidden := insertConnection(t, pool, other, "gamma", nil, "[]")

	o := OpenAPI{}
	rows, err := o.List(ctx, s, Filter{}, 1000, 0)
	if err != nil {
		t.Fatal(err)
	}
	seen := map[string]bool{}
	for _, r := range rows {
		seen[r.ID] = true
	}
	if !seen[own.String()] || !seen[platform.String()] || seen[hidden.String()] {
		t.Fatalf("workspace sees own=%v platform=%v other=%v", seen[own.String()], seen[platform.String()], seen[hidden.String()])
	}
	found, ok, err := o.Get(ctx, s, own)
	if err != nil || !ok || len(found.CustomHeaders) != 2 || !found.CustomHeaders[0].Secret || found.CustomHeaders[1].Value == nil {
		t.Fatalf("get own = %+v ok=%v err=%v", found, ok, err)
	}
	if _, ok, _ := o.Get(ctx, s, hidden); ok {
		t.Fatal("a connection of another workspace is visible")
	}
	pl, ok, err := o.Get(ctx, s, platform)
	if err != nil || !ok || pl.VisibleBaseURL() != nil {
		t.Fatalf("platform connection visible base = %v ok=%v err=%v", pl.VisibleBaseURL(), ok, err)
	}
	if ok, err := o.Delete(ctx, s, platform); err != nil || ok {
		t.Fatalf("delete of a platform connection ok=%v err=%v", ok, err)
	}
	search, err := o.List(ctx, s, Filter{Pattern: ptr("%alp%")}, 1000, 0)
	if err != nil || len(search) != 1 || search[0].Name != "alpha" {
		t.Fatalf("search = %+v err=%v", search, err)
	}
	none, err := o.List(ctx, s, Filter{Status: ptr("pending")}, 1000, 0)
	if err != nil || len(none) != 0 {
		t.Fatalf("status filter = %d err=%v", len(none), err)
	}

	lk := Lookup{}
	flags, err := lk.OpenAPIConnectionFlags(ctx, s, []uuid.UUID{platform, hidden, own})
	if err != nil || len(flags) != 2 || flags[platform] == nil || *flags[platform] != "platform" {
		t.Fatalf("flags = %v err=%v", flags, err)
	}
	names, err := lk.OpenAPIConnectionNames(ctx, s, []uuid.UUID{own, hidden})
	if err != nil || names[own] != "alpha" || len(names) != 1 {
		t.Fatalf("names = %v err=%v", names, err)
	}
}
