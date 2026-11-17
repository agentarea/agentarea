package service

import (
	"context"
	"errors"
	"log/slog"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	connectionsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	streamsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
	walletapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/wallet/api"
)

// world fakes every read insights makes; calls records which ran.
type world struct {
	agentsapi.Lookup
	streamsapi.Triggers
	walletapi.Wallets
	catalogapi.MCPSpecs
	governanceapi.SpendCaps

	calls   []string
	cap     *money.Decimal
	spend   map[string]money.Decimal
	tasks   map[string][]runsapi.TaskRow
	agents  []agentsapi.AgentName
	crons   []streamsapi.CronTrigger
	broken  []streamsapi.BrokenTrigger
	failing []connectionsapi.MCPInstanceState
	members []string
	insts   []connectionsapi.MCPInstanceState
	setCap  *money.Decimal
	err     error
	readErr error
}

func (w *world) note(s string) { w.calls = append(w.calls, s) }

func (w *world) SpendSince(_ context.Context, _ scope.Workspace, q runsapi.SpendQuery) (money.Decimal, error) {
	w.note("spend")
	key := q.Since.Format(time.DateOnly)
	if q.EstimateOnly {
		key = "estimate"
	}
	if d, ok := w.spend[key]; ok {
		return d, w.err
	}
	return money.Zero(), w.err
}

func (w *world) SpendByCurrencySince(context.Context, scope.Workspace, time.Time) (map[string]money.Decimal, error) {
	return map[string]money.Decimal{"USD": money.MustParse("12"), "RUB": money.MustParse("300")}, w.err
}

func (w *world) SpendByDay(context.Context, scope.Workspace, runsapi.SpendQuery) (map[string]money.Decimal, error) {
	return map[string]money.Decimal{"2026-11-14": money.MustParse("7")}, w.err
}

func (w *world) TopAgents(context.Context, scope.Workspace, runsapi.SpendQuery, int) ([]runsapi.AgentSpend, error) {
	return []runsapi.AgentSpend{{AgentID: "a1", Amount: money.MustParse("12")}}, w.err
}

func (w *world) Tasks(_ context.Context, _ scope.Workspace, q runsapi.TaskQuery) ([]runsapi.TaskRow, error) {
	w.note("tasks")
	return w.tasks[q.Statuses[0]], w.err
}

func (w *world) AgentActivity(context.Context, scope.Workspace, string, time.Time, time.Time, []string) (runsapi.AgentActivity, error) {
	w.note("activity")
	return runsapi.AgentActivity{DoneToday: 2, Days: map[string]runsapi.DayCounts{"2026-11-15": {Completed: 2}}}, w.err
}

func (w *world) BrokenTriggers(context.Context, scope.Workspace, int) ([]streamsapi.BrokenTrigger, error) {
	return w.broken, w.err
}

func (w *world) CronTriggers(context.Context, scope.Workspace, *string) ([]streamsapi.CronTrigger, error) {
	return w.crons, w.err
}

func (w *world) Exhausted(context.Context, scope.Workspace) ([]walletapi.Exhausted, error) {
	return []walletapi.Exhausted{{AgentID: "a1", Budget: money.MustParse("5"), Period: "month"}}, w.err
}

func (w *world) FailingMCPInstances(context.Context, scope.Workspace, int) ([]connectionsapi.MCPInstanceState, error) {
	return w.failing, w.err
}

func (w *world) MCPInstances(context.Context, scope.Workspace) ([]connectionsapi.MCPInstanceState, error) {
	return w.insts, w.readErr
}

func (w *world) Get(_ context.Context, _ scope.Workspace, id string, o catalogapi.MCPSpecGet) (catalogapi.MCPSpec, bool, error) {
	w.note("spec " + id)
	if !o.PlatformBacked {
		return catalogapi.MCPSpec{}, false, nil
	}
	return catalogapi.MCPSpec{JSONSpec: map[string]any{"icons": []any{map[string]any{"src": "https://icons/gh.svg"}}}}, true, nil
}

func (w *world) OpenAPIConnections(context.Context, scope.Workspace) ([]connectionsapi.OpenAPIState, error) {
	return nil, w.err
}

func (w *world) NetworkAgents(context.Context, scope.Workspace) ([]agentsapi.NetworkAgent, error) {
	return nil, w.err
}

func (w *world) NetworkSkills(context.Context, scope.Workspace) ([]agentsapi.NetworkSkill, []agentsapi.SkillMember, error) {
	return nil, nil, w.err
}

func (w *world) AllAgents(context.Context, scope.Workspace) ([]agentsapi.AgentName, error) {
	w.note("agents")
	return w.agents, w.err
}

func (w *world) AgentExists(_ context.Context, _ scope.Workspace, id string) (bool, error) {
	w.note("exists")
	for _, a := range w.agents {
		if a.ID == id {
			return true, nil
		}
	}
	return false, nil
}

func (w *world) ListTriggers(context.Context, scope.Workspace, *string) ([]streamsapi.TriggerSummary, error) {
	return nil, w.err
}

func (w *world) MonthlyCap(context.Context, scope.Workspace) (*money.Decimal, error) {
	w.note("cap")
	return w.cap, w.err
}

func (w *world) CapCurrencies(context.Context, scope.Workspace, string) (map[string]bool, error) {
	if w.cap == nil {
		return nil, w.err
	}
	return map[string]bool{"USD": true}, w.err
}

func (w *world) SetMonthlyCap(_ context.Context, _ authn.Caller, amount *money.Decimal) error {
	w.note("set")
	w.setCap = amount
	return w.err
}

func (w *world) Owner(context.Context, string) (string, bool, error) {
	w.note("owner")
	return "u-owner", true, w.err
}

func (w *world) Read(context.Context, authz.Query) ([]authz.Tuple, error) {
	w.note("members")
	if w.readErr != nil {
		return nil, w.readErr
	}
	out := make([]authz.Tuple, len(w.members))
	for i, m := range w.members {
		out[i] = authz.Tuple{User: authz.TypeUser + ":" + m}
	}
	return out, nil
}

var now = time.Date(2026, 11, 15, 10, 0, 0, 0, time.UTC)

func newService(w *world, admin error) *Service {
	return New(Deps{DB: fakeDB{}, Log: slog.New(slog.DiscardHandler), Now: func() time.Time { return now },
		Admin: func(context.Context) error { return admin },
		Reads: Reads{Ledger: w, Tasks: w, Triggers: w, AllTriggers: w, Wallets: w, Connections: w, Specs: w, Agents: w,
			Lookup: w, Caps: w, Owners: w, Members: w}})
}

func at(h int) *time.Time { t := now.Add(time.Duration(h) * time.Hour); return &t }

func TestDashboardAssemblesEveryCard(t *testing.T) {
	capUSD := money.MustParse("40")
	w := &world{cap: &capUSD, agents: []agentsapi.AgentName{{ID: "a1", Name: "Scout"}},
		spend: map[string]money.Decimal{"2026-11-15": money.MustParse("2"), "2026-11-01": money.MustParse("12"), "estimate": money.MustParse("1")},
		tasks: map[string][]runsapi.TaskRow{
			"submitted":         {{ID: "t-run", AgentID: "a1", Status: "running", Description: "crawl", TotalCost: `"0.50"`, CreatedAt: now, UpdatedAt: now}},
			"waiting_for_input": {{ID: "t-hitl", AgentID: "a1", Status: "waiting_for_input", CreatedAt: now}},
			"blocked":           {{ID: "t-fail", AgentID: "a1", Status: "failed", UpdatedAt: now}},
			"scheduled":         {{ID: "t-book", AgentID: "a1", Status: "scheduled", Description: "later", ScheduledAt: at(3)}},
		},
		crons:   []streamsapi.CronTrigger{{ID: "c1", Name: "Hourly", AgentID: "a1", CronExpression: "0 * * * *"}, {ID: "c2", Name: "Weekly", AgentID: "a1", CronExpression: "0 9 * * mon"}, {ID: "c3", Name: "Bad", CronExpression: "nope"}},
		broken:  []streamsapi.BrokenTrigger{{ID: "b1", Name: "Sync", AgentID: "a1", NeedsNewOwner: true}},
		failing: []connectionsapi.MCPInstanceState{{ID: "m1", Name: "GH", Verification: map[string]any{"status": "failed", "error": "401", "at": "2026-11-15T09:00:00Z"}}},
	}
	d, err := newService(w, nil).Dashboard(context.Background(), caller(t))
	if err != nil {
		t.Fatal(err)
	}
	s := d.Spend
	if s.Today.String() != "2" || s.MTD.String() != "12" || s.PctOfCap == nil || *s.PctOfCap != 30 || s.MTDEstimateUSD.String() != "1" {
		t.Fatalf("spend %+v", s)
	}
	if len(s.NotCovered) != 1 || s.NotCovered[0].Currency != "RUB" {
		t.Fatalf("not covered %+v", s.NotCovered)
	}
	if len(d.Blockers.HITL) != 1 || len(d.Blockers.Failed24h) != 1 || len(d.Blockers.WalletExhausted) != 1 || *d.Blockers.HITL[0].AgentName != "Scout" {
		t.Fatalf("blockers %+v", d.Blockers)
	}
	if len(d.ActiveTasks) != 1 || d.ActiveTasks[0].Cost.String() != "0.50" {
		t.Fatalf("active %+v", d.ActiveTasks)
	}
	if len(d.Schedule.Frequent) != 1 || d.Schedule.Frequent[0].TriggerID != "c1" || d.Schedule.Frequent[0].RunsPerDay != 24 {
		t.Fatalf("frequent %+v", d.Schedule.Frequent)
	}
	var booked, weekly int
	for _, r := range d.Schedule.Runs {
		if r.TaskID != nil {
			booked++
		} else if *r.TriggerID == "c2" {
			weekly++
		}
	}
	if booked != 1 || weekly != 6 {
		t.Fatalf("runs: %d booked, %d weekly", booked, weekly)
	}
	if len(d.Health.Connections) != 1 || d.Health.Connections[0].Reason != "verification_failed" || *d.Health.Connections[0].Error != "401" {
		t.Fatalf("connections %+v", d.Health.Connections)
	}
	if len(d.Health.Triggers) != 1 || d.Health.Triggers[0].Reason != "needs_owner" {
		t.Fatalf("triggers %+v", d.Health.Triggers)
	}
	if len(d.DailySpend) != DailySpendDays || d.DailySpend[DailySpendDays-2].USD.String() != "7" || d.Usage != nil {
		t.Fatalf("daily %+v usage %+v", d.DailySpend, d.Usage)
	}
}

func TestDashboardFailsLoudOnARead(t *testing.T) {
	w := &world{err: errors.New("db down")}
	if _, err := newService(w, nil).Dashboard(context.Background(), caller(t)); err == nil {
		t.Fatal("a failed read rendered a dashboard")
	}
}

func TestOverviewUnknownAgentIsNotFoundBeforeAggregates(t *testing.T) {
	w := &world{}
	_, err := newService(w, nil).Overview(context.Background(), caller(t), "nope")
	if !errors.Is(err, ErrAgentNotFound) || len(w.calls) != 1 || w.calls[0] != "exists" {
		t.Fatalf("got %v after %v", err, w.calls)
	}
}

func TestOverviewAgenda(t *testing.T) {
	w := &world{agents: []agentsapi.AgentName{{ID: "a1", Name: "Scout"}},
		spend: map[string]money.Decimal{"2026-11-15": money.MustParse("1.5")},
		crons: []streamsapi.CronTrigger{{ID: "c1", Name: "Daily", CronExpression: "0 12 * * *"}, {ID: "c2", Name: "Broken", CronExpression: "x"}},
		tasks: map[string][]runsapi.TaskRow{"submitted": {{ID: "t1", Status: "running", CreatedAt: now.Add(-time.Hour)}}}}
	o, err := newService(w, nil).Overview(context.Background(), caller(t), "a1")
	if err != nil {
		t.Fatal(err)
	}
	if o.CostToday.String() != "1.5" || o.TasksDoneToday != 2 || len(o.DailyTasks) != OverviewTaskDays || o.DailyTasks[OverviewTaskDays-1].Completed != 2 {
		t.Fatalf("overview %+v", o)
	}
	if len(o.Upcoming) != 9 || o.Upcoming[0].Kind != "running_task" || o.Upcoming[0].Title != OverviewUnnamedTitle || o.Upcoming[1].Title != "Broken"+OverviewInvalidSuffix {
		t.Fatalf("upcoming %+v", o.Upcoming)
	}
}

func TestPeopleAccessChecksAdminBeforeReading(t *testing.T) {
	w := &world{}
	if _, err := newService(w, authz.ErrNotWorkspaceAdmin).PeopleAccess(context.Background(), caller(t)); !errors.Is(err, authz.ErrNotWorkspaceAdmin) || len(w.calls) != 0 {
		t.Fatalf("got %v after %v", err, w.calls)
	}
}

func TestPeopleAccessGraphDownIs503(t *testing.T) {
	w := &world{readErr: errors.New("fga down")}
	if _, err := newService(w, nil).PeopleAccess(context.Background(), caller(t)); !errors.Is(err, ErrMembershipGraphDown) {
		t.Fatalf("got %v", err)
	}
}

func TestPeopleAccessMatrix(t *testing.T) {
	w := &world{members: []string{"u-me", "u-other"}, agents: []agentsapi.AgentName{{ID: "a1", Name: "Scout"}}}
	c := caller(t)
	c.UserID, c.Email = "u-me", "me@example.com"
	p, err := newService(w, nil).PeopleAccess(context.Background(), c)
	if err != nil {
		t.Fatal(err)
	}
	if p.TotalPeople != 3 || p.TotalAgents != 1 || !p.Complete || len(p.Access) != 3 || !p.Access[0].Allowed {
		t.Fatalf("matrix %+v", p)
	}
	for _, x := range p.People {
		if (x.UserID == "u-me") != (x.Email != nil) {
			t.Fatalf("email shown for %s", x.UserID)
		}
	}
}

func TestTopologyFailsLoudOnARead(t *testing.T) {
	w := &world{readErr: errors.New("connections down")}
	if _, err := newService(w, nil).Topology(context.Background(), caller(t)); err == nil {
		t.Fatal("a failed read drew a partial graph")
	}
}

func TestSettingsReadAndWrite(t *testing.T) {
	capUSD := money.MustParse("25.00")
	w := &world{cap: &capUSD}
	s := newService(w, nil)
	got, err := s.Settings(context.Background(), caller(t))
	if err != nil || got.String() != "25.00" {
		t.Fatalf("settings %v %v", got, err)
	}
	if err := s.SetSettings(context.Background(), caller(t), nil); err != nil || w.setCap != nil || w.calls[len(w.calls)-1] != "set" {
		t.Fatalf("clear: %v %v", err, w.calls)
	}
}

func TestTopologyFindsThePlatformSpecIcon(t *testing.T) {
	w := &world{insts: []connectionsapi.MCPInstanceState{
		{ID: "m1", Name: "GitHub", ServerSpecID: "s1", Platform: true},
		{ID: "m2", Name: "GitHub 2", ServerSpecID: "s1", Platform: true},
		{ID: "m3", Name: "Own", JSONSpec: map[string]any{"icons": []any{map[string]any{"src": "https://own.svg"}}}},
	}}
	topo, err := newService(w, nil).Topology(context.Background(), caller(t))
	if err != nil {
		t.Fatal(err)
	}
	icons := map[string]any{}
	for _, n := range topo.Nodes {
		icons[n.ID], _ = n.Metadata.Get("icon_url")
	}
	if icons["m1"] != "https://icons/gh.svg" || icons["m2"] != "https://icons/gh.svg" || icons["m3"] != "https://own.svg" {
		t.Fatalf("icons %v", icons)
	}
	specReads := 0
	for _, c := range w.calls {
		if c == "spec s1" {
			specReads++
		}
	}
	if specReads != 1 {
		t.Fatalf("spec read %d times, want once", specReads)
	}
}
