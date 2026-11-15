package service

import (
	"context"
	"slices"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

func insightsWorkspace(t *testing.T, d db.Database) scope.Workspace {
	t.Helper()
	id := uuid.NewString()
	ws, err := scope.NewWorkspace(id, "")
	if err != nil {
		t.Fatal(err)
	}
	exec(t, d, ws, `INSERT INTO workspaces (id, name, owner_user_id, slug) VALUES ($1, 'W', 'owner', $2)`, id, "ws-"+id[:8])
	return ws
}

func exec(t *testing.T, d db.Database, ws scope.Workspace, sql string, args ...any) {
	t.Helper()
	err := d.Write(context.Background(), ws, func(ctx context.Context, s db.Session) error {
		_, err := s.Q().Exec(ctx, sql, args...)
		return err
	})
	if err != nil {
		t.Fatal(err)
	}
}

// cost books one ledger line; supersedes names the line it replaces.
func cost(t *testing.T, d db.Database, ws scope.Workspace, agent, amount string, currency any, at time.Time, estimate bool, supersedes any) string {
	t.Helper()
	id := uuid.NewString()
	var agentID any
	if agent != "" {
		agentID = agent
	}
	exec(t, d, ws, `INSERT INTO cost_entries (id, workspace_id, created_by, event_id, category, agent_id, subject_type, amount, currency,
		source, occurred_at, payer, estimate, supersedes_id)
		VALUES ($1, $2, 'u', gen_random_uuid(), 'llm', $3, 'model', $4, $5, 'test', $6, 'workspace', $7, $8)`,
		id, ws.ID(), agentID, amount, currency, at, estimate, supersedes)
	return id
}

func TestInsightsSpendReadsTheCurrentLines(t *testing.T) {
	d := openDB(t)
	ws := insightsWorkspace(t, d)
	r := InsightsReads{DB: d}
	ctx := context.Background()
	day := time.Date(2026, 11, 14, 23, 30, 0, 0, time.UTC)
	a1, a2 := uuid.NewString(), uuid.NewString()

	if got, err := r.SpendSince(ctx, ws, api.SpendQuery{Since: day, Currency: "USD"}); err != nil || got.String() != "0" {
		t.Fatalf("empty ledger: %s %v", got, err)
	}
	old := cost(t, d, ws, a1, "5", "USD", day, false, nil)
	cost(t, d, ws, a1, "2.5", "USD", day, false, old)
	cost(t, d, ws, a2, "1", nil, day.Add(time.Hour), true, nil)
	cost(t, d, ws, a2, "300", "RUB", day.Add(time.Hour), false, nil)
	cost(t, d, ws, a2, "9", "USD", day.Add(-48*time.Hour), false, nil)

	got, err := r.SpendSince(ctx, ws, api.SpendQuery{Since: day, Currency: "USD"})
	if err != nil || got.String() != "3.500000000000" {
		t.Fatalf("since: %s %v", got, err)
	}
	if got, _ := r.SpendSince(ctx, ws, api.SpendQuery{Since: day, Currency: "USD", AgentID: a1}); got.String() != "2.500000000000" {
		t.Fatalf("one agent: %s", got)
	}
	if got, _ := r.SpendSince(ctx, ws, api.SpendQuery{Since: day, Currency: "USD", EstimateOnly: true}); got.String() != "1.000000000000" {
		t.Fatalf("estimates: %s", got)
	}
	if got, _ := r.SpendSince(ctx, ws, api.SpendQuery{Since: day, Currency: "USD", AgentID: "not-a-uuid"}); got.String() != "0" {
		t.Fatalf("a non-uuid agent: %s", got)
	}
	by, err := r.SpendByCurrencySince(ctx, ws, day)
	if err != nil || len(by) != 3 || by["RUB"].String() != "300.000000000000" || by[""].String() != "1.000000000000" {
		t.Fatalf("by currency: %v %v", by, err)
	}
	days, err := r.SpendByDay(ctx, ws, api.SpendQuery{Since: day.Add(-72 * time.Hour), Currency: "USD"})
	if err != nil || days["2026-11-14"].String() != "2.500000000000" || days["2026-11-15"].String() != "1.000000000000" || days["2026-11-12"].String() != "9.000000000000" {
		t.Fatalf("by day: %v %v", days, err)
	}
	top, err := r.TopAgents(ctx, ws, api.SpendQuery{Since: day.Add(-72 * time.Hour), Currency: "USD"}, 1)
	if err != nil || len(top) != 1 || top[0].AgentID != a2 || top[0].Amount.String() != "10.000000000000" {
		t.Fatalf("top: %v %v", top, err)
	}
}

func task(t *testing.T, d db.Database, ws scope.Workspace, agent, status string, created time.Time, started, completed, scheduled any, result string) string {
	t.Helper()
	id := uuid.NewString()
	var res any
	if result != "" {
		res = result
	}
	exec(t, d, ws, `INSERT INTO tasks (id, agent_id, description, status, workspace_id, created_by, created_at, updated_at, started_at, completed_at, scheduled_at, result)
		VALUES ($1, $2, 'do it', $3, $4, 'u', $5, $5, $6, $7, $8, $9)`, id, agent, status, ws.ID(), created, started, completed, scheduled, res)
	return id
}

func TestInsightsTaskBoard(t *testing.T) {
	d := openDB(t)
	ws := insightsWorkspace(t, d)
	r := InsightsReads{DB: d}
	ctx := context.Background()
	now := time.Date(2026, 11, 15, 12, 0, 0, 0, time.UTC)
	a1, a2 := uuid.NewString(), uuid.NewString()
	early := task(t, d, ws, a1, "running", now.Add(-3*time.Hour), now.Add(-time.Hour), nil, nil, `{"total_cost": "0.25"}`)
	late := task(t, d, ws, a1, "running", now.Add(-2*time.Hour), nil, nil, nil, `[1]`)
	task(t, d, ws, a2, "completed", now.Add(-time.Hour), now.Add(-time.Hour), now, nil, "")
	failed := task(t, d, ws, a1, "failed", now.Add(-50*time.Hour), nil, now.Add(-49*time.Hour), nil, "")
	booked := task(t, d, ws, a1, "scheduled", now, nil, nil, now.Add(24*time.Hour), "")
	task(t, d, ws, a1, "scheduled", now, nil, nil, now.Add(24*time.Hour*60), "")

	rows, err := r.Tasks(ctx, ws, api.TaskQuery{Statuses: []string{"running"}, Order: api.ByActivity, Limit: 10})
	if err != nil || len(rows) != 2 || rows[0].ID != early || rows[1].ID != late || rows[0].TotalCost != `"0.25"` || rows[1].TotalCost != "" {
		t.Fatalf("activity order: %+v %v", rows, err)
	}
	since := now.Add(-24 * time.Hour)
	rows, _ = r.Tasks(ctx, ws, api.TaskQuery{Statuses: []string{"failed", "completed"}, EndedSince: &since, Order: api.ByEnded, Limit: 10})
	if len(rows) != 1 || rows[0].Status != "completed" {
		t.Fatalf("ended since: %+v", rows)
	}
	rows, _ = r.Tasks(ctx, ws, api.TaskQuery{Statuses: []string{"failed"}, AgentID: a1, Order: api.ByEnded, Limit: 10})
	if len(rows) != 1 || rows[0].ID != failed {
		t.Fatalf("one agent: %+v", rows)
	}
	until := now.Add(42 * 24 * time.Hour)
	rows, _ = r.Tasks(ctx, ws, api.TaskQuery{Statuses: []string{"scheduled"}, ScheduledUntil: &until, Order: api.ByScheduled, Limit: 10})
	if len(rows) != 1 || rows[0].ID != booked || rows[0].ScheduledAt == nil {
		t.Fatalf("booked: %+v", rows)
	}

	act, err := r.AgentActivity(ctx, ws, a1, time.Date(2026, 11, 15, 0, 0, 0, 0, time.UTC), now.Add(-14*24*time.Hour), []string{"waiting_for_input"})
	if err != nil || act.DoneToday != 0 || act.FailedToday != 0 || act.LastActivityAt == nil {
		t.Fatalf("activity: %+v %v", act, err)
	}
	if c := act.Days["2026-11-13"]; c.Failed != 1 {
		t.Fatalf("days: %+v", act.Days)
	}
	keys := make([]string, 0, len(act.Days))
	for k := range act.Days {
		keys = append(keys, k)
	}
	slices.Sort(keys)
	if len(keys) != 2 {
		t.Fatalf("days: %v", keys)
	}
	if other, _ := r.AgentActivity(ctx, ws, a2, time.Date(2026, 11, 15, 0, 0, 0, 0, time.UTC), now.Add(-14*24*time.Hour), nil); other.DoneToday != 1 {
		t.Fatalf("other agent: %+v", other)
	}
}
