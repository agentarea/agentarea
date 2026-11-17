package app

import (
	"context"
	"log/slog"
	"net/url"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	agentsstore "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/store"
	catalogstore "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/store"
	connectionsstore "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/store"
	governancestore "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/store"
	identitystore "github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/store"
	insightsdomain "github.com/agentarea/agentarea/agentarea-go/internal/modules/insights/domain"
	insightsservice "github.com/agentarea/agentarea/agentarea-go/internal/modules/insights/service"
	insightsstore "github.com/agentarea/agentarea/agentarea-go/internal/modules/insights/store"
	modelsstore "github.com/agentarea/agentarea/agentarea-go/internal/modules/models/store"
	runsstore "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/store"
	streamsstore "github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store"
	"github.com/agentarea/agentarea/agentarea-go/internal/schema"
)

// pulseDB is a fresh, migrated database; it needs AGENTAREA_DB_TEST_URL.
func pulseDB(t *testing.T) db.Database {
	t.Helper()
	raw := os.Getenv("AGENTAREA_DB_TEST_URL")
	if raw == "" {
		t.Skip("AGENTAREA_DB_TEST_URL not set")
	}
	ctx := context.Background()
	admin, err := schema.Open(raw)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = admin.Close() }()
	name := "aa_go_pulse_" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
	if _, err := admin.ExecContext(ctx, "CREATE DATABASE "+name); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if a, err := schema.Open(raw); err == nil {
			_, _ = a.ExecContext(ctx, "DROP DATABASE "+name+" WITH (FORCE)")
			_ = a.Close()
		}
	})
	u, _ := url.Parse(raw)
	u.Path = "/" + name
	conn, err := schema.Open(u.String())
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Migrate(ctx, conn, schema.Core()); err != nil {
		t.Fatal(err)
	}
	_ = conn.Close()
	port, _ := strconv.Atoi(u.Port())
	pass, _ := u.User.Password()
	pools, err := db.Open(ctx, db.Config{Host: u.Hostname(), Port: port, Name: name, User: u.User.Username(), Password: pass,
		SSLMode: u.Query().Get("sslmode"), PoolSize: 4, PoolTimeout: 10 * time.Second}, slog.New(slog.DiscardHandler))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pools.Close)
	return pools
}

func TestInstallationPulseReadsEveryOwnersTables(t *testing.T) {
	d := pulseDB(t)
	ctx := context.Background()
	now := time.Now().UTC()
	seed := []string{
		`INSERT INTO workspaces (id, name, owner_user_id, slug, created_at) VALUES
			('u1', 'Personal', 'u1', 'u1', now() - interval '12 hours'),
			('team', 'Team', 'u1', 'team', now() - interval '40 days')`,
		`INSERT INTO workspace_memberships (id, workspace_id, user_id, created_at, updated_at) VALUES
			(gen_random_uuid(), 'team', 'u2', now(), now())`,
		`INSERT INTO agents (id, name, status, workspace_id, created_by, slug) VALUES
			(gen_random_uuid(), 'a', 'active', 'u1', 'u1', 'a'),
			(gen_random_uuid(), 'p', 'active', 'platform', 'system', 'p')`,
		`INSERT INTO tasks (id, agent_id, description, status, workspace_id, created_by, started_at, completed_at, result, created_at) VALUES
			(gen_random_uuid(), gen_random_uuid(), 'd', 'completed', 'u1', 'u1', now() - interval '1 hour', now() - interval '50 minutes', NULL, now() - interval '2 hours'),
			(gen_random_uuid(), gen_random_uuid(), 'd', 'failed', 'team', 'u2', NULL, NULL, '{"failure_reason": "Budget Exceeded"}', now() - interval '3 hours')`,
		`INSERT INTO triggers (id, name, description, agent_id, trigger_type, is_active, task_parameters, conditions,
			failure_threshold, consecutive_failures, workspace_id, created_by) VALUES
			(gen_random_uuid(), 't', '', gen_random_uuid(), 'cron', true, '{}', '{}', 3, 0, 'team', 'u1')`,
	}
	for _, sql := range seed {
		if err := d.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
			_, err := q.Exec(ctx, sql)
			return err
		}); err != nil {
			t.Fatalf("%v\n%s", err, sql)
		}
	}
	reads := insightsservice.PulseReads{
		Identity: identitystore.TenantReads{DB: d}, Runs: runsstore.TenantReads{DB: d}, Agents: agentsstore.TenantReads{DB: d},
		Connections: connectionsstore.TenantReads{DB: d}, Catalog: catalogstore.TenantReads{DB: d}, Models: modelsstore.TenantReads{DB: d},
		Streams: streamsstore.TenantReads{DB: d}, Governance: governancestore.TenantReads{DB: d},
	}
	got, err := insightsservice.CollectPulse(ctx, reads, now)
	if err != nil {
		t.Fatal(err)
	}
	ws := got["workspaces"].(map[string]any)
	users := got["users"].(map[string]any)
	if ws["total"] != 2 || ws["active_7d"] != 2 || users["total"] != 2 || users["active_7d"] != 2 {
		t.Fatalf("workspaces %v users %v", ws, users)
	}
	runs := got["runs_24h"].(map[string]any)
	if runs["by_status"].(map[string]int)["completed"] != 1 || runs["failed_by_reason"].(map[string]int)["other"] != 1 ||
		runs["median_duration_seconds"] != 600.0 || runs["by_origin"].(map[string]int)["unknown"] != 2 {
		t.Fatalf("runs %v", runs)
	}
	act := got["activation_7d"].(map[string]any)
	if act["personal_workspaces"] != 1 || act["with_agent"] != 1 || act["succeeded_within_1d"] != 1 || act["succeeded_within_7d"] != 1 {
		t.Fatalf("activation %v", act)
	}
	if sizes := got["workspace_sizes"].(map[string]int); sizes["1"] != 2 || sizes["2-5"] != 0 {
		t.Fatalf("sizes %v", sizes)
	}
	if got["agents"].(map[string]any)["total"] != 1 || got["triggers_active"].(map[string]int)["cron"] != 1 || got["policies"] != 0 {
		t.Fatalf("%v", got)
	}

	cat, err := catalogstore.TenantReads{DB: d}.TenantCounts(ctx, []string{uuid.NewString()}, []string{uuid.NewString()}, []string{uuid.NewString()})
	if err != nil || len(cat.SpecSlugs) != 0 || len(cat.ItemSlugs) != 0 || len(cat.ProviderTypes) != 0 {
		t.Fatalf("catalog lookups %+v %v", cat, err)
	}

	lock := insightsstore.Installation{}
	var seen []insightsdomain.Installation
	for range 2 {
		if _, err := lock.LockForPulse(ctx, d, db.Key(insightsservice.PulseLockKey), now, func(_ context.Context, row insightsdomain.Installation) (bool, error) {
			seen = append(seen, row)
			return row.LastPulse == nil, nil
		}); err != nil {
			t.Fatal(err)
		}
	}
	if len(seen) != 2 || seen[0].LastPulse != nil || seen[1].LastPulse == nil || !seen[1].LastPulse.Equal(now.Truncate(time.Microsecond)) {
		t.Fatalf("pulse stamps %+v", seen)
	}

	path := "/skills/x"
	attr := insightsdomain.Attribution{Channel: "skills_catalog", LandingPath: &path}
	for i, want := range []bool{true, false} {
		inserted, err := insightsstore.Signups{}.Insert(ctx, d.Global(), "identity-1", now, nil, attr, now)
		if err != nil || inserted != want {
			t.Fatalf("sign-up %d: %v %v", i, inserted, err)
		}
	}
}
