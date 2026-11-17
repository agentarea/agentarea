package service

import (
	"context"
	"errors"
	"log/slog"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/analytics"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	connectionsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	identityapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/insights/domain"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

type pulseLock struct {
	row     domain.Installation
	held    bool
	stamped bool
}

func (l *pulseLock) LockForPulse(ctx context.Context, _ db.Database, _ db.LockKey, _ time.Time, fn func(context.Context, domain.Installation) (bool, error)) (bool, error) {
	if !l.held {
		return false, nil
	}
	ok, err := fn(ctx, l.row)
	l.stamped = ok && err == nil
	return l.stamped, err
}

type signups struct{ seen map[string]domain.Attribution }

func (s *signups) Insert(_ context.Context, _ db.Global, id string, _ time.Time, _ *string, a domain.Attribution, _ time.Time) (bool, error) {
	if _, ok := s.seen[id]; ok {
		return false, nil
	}
	s.seen[id] = a
	return true, nil
}

type identityPulse struct{}

var created = time.Date(2026, 11, 10, 9, 0, 0, 0, time.UTC)

func (identityPulse) TenantCounts(context.Context, time.Time) (identityapi.TenantCounts, error) {
	return identityapi.TenantCounts{Workspaces: 3, Users: 4, WorkspacesByMembers: map[int]int{0: 1, 1: 1, 3: 1, 7: 2},
		NewPersonal: []identityapi.NewWorkspace{{ID: "u1", CreatedAt: created}, {ID: "u2", CreatedAt: created}}}, nil
}

type runsPulse struct{ got []string }

func (r *runsPulse) TenantCounts(_ context.Context, _ runsapi.Windows, ws []string) (runsapi.TenantCounts, error) {
	r.got = ws
	m := 12.46
	return runsapi.TenantCounts{ActiveWorkspaces7d: 2, ByStatus: map[string]int{"completed": 3, "Weird Status": 1},
		ByOrigin: map[string]int{}, FailedByReason: map[string]int{}, MedianDurationSeconds: &m,
		FirstCompleted: map[string]time.Time{"u1": created.Add(2 * time.Hour), "u2": created.Add(3 * 24 * time.Hour)}}, nil
}

type agentsPulse struct{}

func (agentsPulse) TenantCounts(context.Context, time.Time, []string) (agentsapi.TenantCounts, error) {
	return agentsapi.TenantCounts{Agents: 5, SkillsByItem: map[string]int{"": 2, "item-1": 1}, ClientsByKind: map[string]int{"harness": 1}, WithAgent: 1}, nil
}

type connectionsPulse struct{}

func (connectionsPulse) TenantCounts(context.Context) (connectionsapi.TenantCounts, error) {
	return connectionsapi.TenantCounts{MCP: 3, OpenAPI: 1,
		MCPBySpec:         []connectionsapi.Connectors{{Source: "spec-1", AuthType: "oauth2", Count: 2}, {Source: "spec-x", AuthType: "none", Count: 1}},
		OpenAPIByItem:     []connectionsapi.Connectors{{Source: "", AuthType: "api_key", Count: 1}},
		MCPByVerification: map[string]int{"succeeded": 3}}, nil
}

type catalogPulse struct{ specs, items, providers []string }

func (c *catalogPulse) TenantCounts(_ context.Context, specs, items, providers []string) (catalogapi.TenantCounts, error) {
	c.specs, c.items, c.providers = specs, items, providers
	return catalogapi.TenantCounts{SpecSlugs: map[string]string{"spec-1": "github"}, ItemSlugs: map[string]string{"item-1": "pdf-tools"},
		ProviderTypes: map[string]string{"p1": "anthropic"}, Bundles: []catalogapi.Bundle{{Name: "research", Catalog: true, Count: 2}, {Name: "mine", Count: 1}, {Name: "other", Count: 1}}}, nil
}

type countPulse map[string]int

func (c countPulse) TenantCounts(context.Context) (map[string]int, error) { return c, nil }

type policyPulse int

func (p policyPulse) TenantCounts(context.Context) (int, error) { return int(p), nil }

func pulseReads(r *runsPulse, c *catalogPulse) PulseReads {
	return PulseReads{Identity: identityPulse{}, Runs: r, Agents: agentsPulse{}, Connections: connectionsPulse{}, Catalog: c,
		Models: countPulse{"p1": 2, "gone": 1}, Streams: countPulse{"cron": 2}, Governance: policyPulse(7)}
}

func TestCollectPulseNamesOnlyTheCatalogsOwnItems(t *testing.T) {
	r, c := &runsPulse{}, &catalogPulse{}
	got, err := CollectPulse(context.Background(), pulseReads(r, c), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if len(r.got) != 2 || len(c.specs) != 2 || len(c.providers) != 2 {
		t.Fatalf("reads %v %v %v", r.got, c.specs, c.providers)
	}
	conn := got["connectors"].(map[string]any)
	if cat := conn["by_catalog"].(map[string]int); cat["github"] != 2 || cat["custom"] != 2 {
		t.Fatalf("by_catalog %v", cat)
	}
	if auth := conn["by_auth_type"].(map[string]int); auth["oauth2"] != 2 || auth["none"] != 1 || auth["api_key"] != 1 {
		t.Fatalf("by_auth_type %v", auth)
	}
	if s := got["skills"].(map[string]int); s["custom"] != 2 || s["pdf-tools"] != 1 {
		t.Fatalf("skills %v", s)
	}
	if llm := got["llm_providers"].(map[string]int); len(llm) != 1 || llm["anthropic"] != 2 {
		t.Fatalf("llm %v", llm)
	}
	runs := got["runs_24h"].(map[string]any)
	if st := runs["by_status"].(map[string]int); st["completed"] != 3 || st["other"] != 1 || runs["median_duration_seconds"] != 12.5 {
		t.Fatalf("runs %v", runs)
	}
	act := got["activation_7d"].(map[string]any)
	if act["personal_workspaces"] != 2 || act["with_agent"] != 1 || act["succeeded_within_1d"] != 1 || act["succeeded_within_7d"] != 2 || got["policies"] != 7 {
		t.Fatalf("activation %v", act)
	}
	if sizes := got["workspace_sizes"].(map[string]int); sizes["1"] != 2 || sizes["2-5"] != 1 || sizes["6+"] != 2 {
		t.Fatalf("sizes %v", sizes)
	}
	if b := got["bundles"].(map[string]int); len(b) != 2 || b["research"] != 2 || b["custom"] != 2 {
		t.Fatalf("bundles %v", b)
	}
}

func runtime(t *testing.T, enabled bool, lock *pulseLock, c *collector, now time.Time) (*Analytics, *analytics.Handle) {
	t.Helper()
	h := &analytics.Handle{}
	a := NewAnalytics(AnalyticsDeps{DB: fakeDB{}, Installations: &fakeInstallations{id: "inst"}, Lock: lock,
		Signups: &signups{seen: map[string]domain.Attribution{}}, Collector: c, Counter: h,
		Pulse:   func() PulseReads { return pulseReads(&runsPulse{}, &catalogPulse{}) },
		Enabled: enabled, Version: "1.0.0", Edition: "oss", SignupHookKey: "k", Now: func() time.Time { return now },
		Log: slog.New(slog.DiscardHandler)})
	if err := a.Start(context.Background()); err != nil {
		t.Fatal(err)
	}
	return a, h
}

func TestPulseIsSentOnceADayFromTheReplicaHoldingTheLock(t *testing.T) {
	now := time.Date(2026, 11, 17, 12, 0, 0, 0, time.UTC)
	created := now.Add(-50 * time.Hour)
	lock, c := &pulseLock{row: domain.Installation{ID: "inst", CreatedAt: created}}, &collector{}
	a, _ := runtime(t, true, lock, c, now)
	if sent, err := a.PulseOnce(context.Background()); sent || err != nil || len(c.batches) != 0 {
		t.Fatalf("without the lock: %v %v", sent, err)
	}
	lock.held = true
	recent := now.Add(-23 * time.Hour)
	lock.row.LastPulse = &recent
	if sent, _ := a.PulseOnce(context.Background()); sent {
		t.Fatal("sent within a day of the last pulse")
	}
	due := now.Add(-24 * time.Hour)
	lock.row.LastPulse = &due
	if sent, err := a.PulseOnce(context.Background()); !sent || err != nil || !lock.stamped || len(c.batches) != 1 {
		t.Fatalf("due: %v %v", sent, err)
	}
	e := c.batches[0][0]
	if e["event"] != "installation_pulse" || e["properties"].(map[string]any)["install_age_days"] != 2 {
		t.Fatalf("%v", e)
	}
	_ = a.Stop(context.Background())
}

func TestAnalyticsOffStartsNothingAndCountsNothing(t *testing.T) {
	c := &collector{}
	a, h := runtime(t, false, &pulseLock{held: true}, c, time.Now())
	analytics.Count(h, "run_refused", map[string]string{"reason": "x"})
	if sent, err := a.PulseOnce(context.Background()); sent || err != nil {
		t.Fatal(sent, err)
	}
	_ = a.Stop(context.Background())
	if len(c.batches) != 0 {
		t.Fatal("sent with analytics off")
	}
}

func TestAStartThatFailsLeavesAnalyticsOff(t *testing.T) {
	a := NewAnalytics(AnalyticsDeps{DB: fakeDB{}, Installations: &fakeInstallations{err: errors.New("db down")}, Enabled: true,
		Log: slog.New(slog.DiscardHandler)})
	if err := a.Start(context.Background()); err != nil {
		t.Fatal("a failed start failed the process")
	}
	if a.sender.Load() != nil {
		t.Fatal("analytics is on")
	}
}

func TestCountsAndSignupsAreSentAtStop(t *testing.T) {
	c := &collector{}
	a, h := runtime(t, true, &pulseLock{}, c, time.Now())
	analytics.RunRefused(h, nil)
	url := "https://app.example.test/registration?utm_source=hn&aa_lp=/blog/post"
	hook := SignupHook{IdentityID: "id-1", CreatedAt: time.Now(), RequestURL: &url}
	if err := a.RecordSignup(context.Background(), hook, "oidc"); err != nil {
		t.Fatal(err)
	}
	if err := a.RecordSignup(context.Background(), hook, "oidc"); err != nil {
		t.Fatal(err)
	}
	if err := a.Stop(context.Background()); err != nil {
		t.Fatal(err)
	}
	var events []map[string]any
	for _, b := range c.batches {
		events = append(events, b...)
	}
	if len(events) != 2 || events[0]["event"] != "sign_up" || events[1]["event"] != "counters" {
		t.Fatalf("%v", events)
	}
	signup := events[0]
	props := signup["properties"].(map[string]any)
	if signup["user_id"] != domain.Pseudonymize("inst", "id-1") || props["channel"] != "campaign" || *props["landing_path"].(*string) != "/blog/*" || *props["method"].(*string) != "oidc" {
		t.Fatalf("%v", signup)
	}
	analytics.RunRefused(h, nil)
	if a.sender.Load() != nil {
		t.Fatal("still on after stop")
	}
}

func TestSignupKey(t *testing.T) {
	a := NewAnalytics(AnalyticsDeps{SignupHookKey: "secret"})
	if a.CheckSignupKey("secret") != nil || !errors.Is(a.CheckSignupKey("Bearer secret"), ErrSignupHookKey) {
		t.Fatal("key check")
	}
	if !errors.Is(NewAnalytics(AnalyticsDeps{}).CheckSignupKey("anything"), ErrSignupHookOff) {
		t.Fatal("no key configured must turn the hook off")
	}
}
