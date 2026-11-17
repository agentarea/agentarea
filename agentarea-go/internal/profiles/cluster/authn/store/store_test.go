package store

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"os"
	"slices"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	port "github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	authn "github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster/authn"
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

type noGraph struct{}

func (noGraph) Check(context.Context, string, string, string, string) (bool, error) {
	return false, nil
}
func (noGraph) Read(context.Context, authz.Query) ([]authz.Tuple, error) { return nil, nil }

// pythonKey is an API key minted by agentarea_mcp's access_token_service.
func pythonKey(t *testing.T) (token, prefix, hash string) {
	t.Helper()
	raw, err := os.ReadFile("../testdata/python_golden.json")
	if err != nil {
		t.Fatal(err)
	}
	var g struct {
		APIKeys []struct{ Token, Prefix, Hash string } `json:"api_keys"`
	}
	if err := json.Unmarshal(raw, &g); err != nil {
		t.Fatal(err)
	}
	k := g.APIKeys[0]
	return k.Token, k.Prefix, k.Hash
}

func TestAPIKeysAgainstTheBaselineSchema(t *testing.T) {
	pool := openPool(t)
	ctx := context.Background()
	suffix := time.Now().Format("150405.000000")
	owner := "authn-owner-" + suffix
	ws := "authn-ws-" + suffix
	wsSlug := "authn-" + time.Now().Format("150405") + "-" + suffix[7:]
	exec := func(q string, args ...any) {
		t.Helper()
		if _, err := pool.Exec(ctx, q, args...); err != nil {
			t.Fatal(err)
		}
	}
	exec(`INSERT INTO workspaces (id, name, owner_user_id, slug) VALUES ($1, 'w', $2, $3)`, ws, owner, wsSlug)
	exec(`INSERT INTO clients (id, created_at, updated_at, workspace_id, created_by, name) VALUES ($1, now(), now(), $2, $3, 'c')`,
		"9a9a9a9a-0000-4000-8000-"+suffix[:6]+"000001", ws, owner)
	pyToken, pyPrefix, pyHash := pythonKey(t)
	exec(`DELETE FROM api_keys WHERE token_hash = $1`, pyHash)
	insert := func(id, hash, prefix string, active bool, expires *time.Time, agent, client *string) {
		t.Helper()
		exec(`INSERT INTO api_keys (id, workspace_id, created_by, name, token_hash, token_prefix, is_active, expires_at, agent_id, client_id)
			VALUES ($1, $2, $3, 'k', $4, $5, $6, $7, $8, $9)`, id, ws, owner, hash, prefix, active, expires, agent, client)
	}
	pastNaive := time.Now().UTC().Add(-time.Minute)
	futureNaive := time.Now().UTC().Add(time.Hour)
	agent := "1b1b1b1b-0000-4000-8000-" + suffix[:6] + "000002"
	client := "9a9a9a9a-0000-4000-8000-" + suffix[:6] + "000001"
	keyID := "2c2c2c2c-0000-4000-8000-" + suffix[:6] + "000001"
	insert(keyID, pyHash, pyPrefix, true, &futureNaive, nil, nil)

	mint := func(active bool, expires *time.Time, agentID, clientID *string) string {
		t.Helper()
		token, prefix, hash, err := port.NewAPIKey()
		if err != nil {
			t.Fatal(err)
		}
		id := "3d3d3d3d-0000-4000-8000-" + hash[:12]
		insert(id, hash, prefix, active, expires, agentID, clientID)
		return token
	}
	revoked := mint(false, nil, nil, nil)
	expired := mint(true, &pastNaive, nil, nil)
	agentKey := mint(true, nil, &agent, nil)
	runnerKey := mint(true, nil, nil, &client)

	s := New(pool)
	k, ok, err := s.APIKeyByHash(ctx, pyHash)
	if err != nil || !ok {
		t.Fatalf("lookup: %v %v", ok, err)
	}
	if k.ID != keyID || k.WorkspaceID != ws || k.CreatedBy != owner || !k.IsActive || k.AgentID != "" || k.ClientID != "" ||
		k.ExpiresAt == nil || k.ExpiresAt.Location() != time.UTC || k.ExpiresAt.Sub(futureNaive).Abs() > time.Millisecond {
		t.Fatalf("%+v", k)
	}
	if _, ok, err := s.APIKeyByHash(ctx, "0000"); ok || err != nil {
		t.Fatalf("unknown hash: %v %v", ok, err)
	}

	clock := time.Now()
	gate, err := authn.New(authn.Config{Issuer: "http://kratos", Audience: "agentarea-api", HydraURL: "http://127.0.0.1:9", APIURL: "http://localhost:8000"},
		authn.Deps{Store: s, Graph: noGraph{}, Now: func() time.Time { return clock }, Log: slog.New(slog.DiscardHandler)})
	if err != nil {
		t.Fatal(err)
	}
	p, err := gate.Verify(ctx, pyToken)
	if err != nil {
		t.Fatalf("Python-minted key: %v", err)
	}
	if p.UserID != owner || p.BoundWorkspaceID != ws || p.Credential.KeyID != keyID {
		t.Fatalf("%+v", p)
	}
	var count int
	var last *time.Time
	if err := pool.QueryRow(ctx, `SELECT access_count, last_accessed_at FROM api_keys WHERE id = $1`, keyID).Scan(&count, &last); err != nil {
		t.Fatal(err)
	}
	if count != 1 || last == nil || last.Sub(clock.UTC()).Abs() > time.Millisecond {
		t.Fatalf("use not recorded: %d %v (at %v)", count, last, clock.UTC())
	}

	for name, token := range map[string]string{"revoked": revoked, "expired": expired} {
		_, err := gate.Verify(ctx, token)
		var r *port.Error
		if !errors.As(err, &r) || r.Status != 401 || r.Detail != port.DetailInvalidAPIKey {
			t.Errorf("%s: %v", name, err)
		}
	}
	if p, err := gate.Verify(ctx, agentKey); err != nil || p.BoundAgentID != agent {
		t.Fatalf("agent key: %+v %v", p, err)
	}
	if p, err := gate.RunnerKey(ctx, runnerKey); err != nil || p == nil || p.BoundClientID != client {
		t.Fatalf("runner key: %+v %v", p, err)
	}

	owned, err := s.OwnedOrNamed(ctx, owner, "", "")
	if err != nil || len(owned) != 1 || owned[0].ID != ws || owned[0].Slug != wsSlug {
		t.Fatalf("owned: %+v %v", owned, err)
	}
	named, err := s.OwnedOrNamed(ctx, "nobody-"+suffix, wsSlug, "")
	if err != nil || len(named) != 1 {
		t.Fatalf("named: %+v %v", named, err)
	}
	if none, err := s.OwnedOrNamed(ctx, "nobody-"+suffix, "", ""); err != nil || len(none) != 0 {
		t.Fatalf("none: %+v %v", none, err)
	}
	if w, ok, err := s.WorkspaceBySlug(ctx, wsSlug); err != nil || !ok || w.ID != ws || w.OwnerUserID != owner {
		t.Fatalf("by slug: %+v %v %v", w, ok, err)
	}
	if _, ok, err := s.WorkspaceByID(ctx, "missing-"+suffix); ok || err != nil {
		t.Fatalf("missing: %v %v", ok, err)
	}

	c, err := gate.Caller(ctx, p, port.Route{WorkspaceRef: wsSlug, HasWorkspaceRef: true})
	if err != nil || c.Workspace.ID() != ws || !slices.Equal(c.AdminWorkspaces, []string{ws}) {
		t.Fatalf("caller: %+v %v", c, err)
	}
}
