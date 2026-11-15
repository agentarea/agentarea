package service

import (
	"context"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/store"
)

// InsightsReads implements api.SpendLedger and api.TaskBoard over the read
// pool. An agent id that is not a UUID names nothing.
type InsightsReads struct {
	DB db.Database
}

var (
	_ api.SpendLedger = InsightsReads{}
	_ api.TaskBoard   = InsightsReads{}
)

func (r InsightsReads) read(ctx context.Context, ws scope.Workspace, fn func(q *store.Queries) error) error {
	s, release, err := r.DB.Read(ctx, ws)
	if err != nil {
		return err
	}
	defer release()
	return fn(store.New(s.Q()))
}

// agentFilter is the agent narrowing of q; ok false when the id names no agent.
func agentFilter(id string) (uuid.NullUUID, bool) {
	if id == "" {
		return uuid.NullUUID{}, true
	}
	u, err := uuid.Parse(id)
	if err != nil {
		return uuid.NullUUID{}, false
	}
	return uuid.NullUUID{UUID: u, Valid: true}, true
}

func amount(text string) (money.Decimal, error) { return money.Parse(text) }

// SpendSince implements api.SpendLedger.
func (r InsightsReads) SpendSince(ctx context.Context, ws scope.Workspace, q api.SpendQuery) (money.Decimal, error) {
	agent, ok := agentFilter(q.AgentID)
	if !ok {
		return money.Zero(), nil
	}
	var total string
	err := r.read(ctx, ws, func(s *store.Queries) error {
		var err error
		total, err = s.InsightsSpendSince(ctx, store.InsightsSpendSinceParams{
			WorkspaceID: ws.ID(), Since: store.Timestamptz(q.Since), Currency: store.Text(&q.Currency),
			AgentID: agent, EstimateOnly: q.EstimateOnly,
		})
		return err
	})
	if err != nil {
		return money.Decimal{}, err
	}
	d, err := amount(total)
	if err == nil && d.IsZero() {
		d = money.Zero()
	}
	return d, err
}

// SpendByCurrencySince implements api.SpendLedger.
func (r InsightsReads) SpendByCurrencySince(ctx context.Context, ws scope.Workspace, since time.Time) (map[string]money.Decimal, error) {
	var rows []store.InsightsSpendByCurrencyRow
	err := r.read(ctx, ws, func(s *store.Queries) error {
		var err error
		rows, err = s.InsightsSpendByCurrency(ctx, store.InsightsSpendByCurrencyParams{WorkspaceID: ws.ID(), Since: store.Timestamptz(since)})
		return err
	})
	if err != nil {
		return nil, err
	}
	out := make(map[string]money.Decimal, len(rows))
	for _, row := range rows {
		if out[row.Currency], err = amount(row.Total); err != nil {
			return nil, err
		}
	}
	return out, nil
}

// SpendByDay implements api.SpendLedger.
func (r InsightsReads) SpendByDay(ctx context.Context, ws scope.Workspace, q api.SpendQuery) (map[string]money.Decimal, error) {
	out := map[string]money.Decimal{}
	agent, ok := agentFilter(q.AgentID)
	if !ok {
		return out, nil
	}
	var rows []store.InsightsSpendByDayRow
	err := r.read(ctx, ws, func(s *store.Queries) error {
		var err error
		rows, err = s.InsightsSpendByDay(ctx, store.InsightsSpendByDayParams{
			WorkspaceID: ws.ID(), Since: store.Timestamptz(q.Since), Currency: store.Text(&q.Currency), AgentID: agent,
		})
		return err
	})
	if err != nil {
		return nil, err
	}
	for _, row := range rows {
		if out[row.Day], err = amount(row.Total); err != nil {
			return nil, err
		}
	}
	return out, nil
}

// TopAgents implements api.SpendLedger.
func (r InsightsReads) TopAgents(ctx context.Context, ws scope.Workspace, q api.SpendQuery, limit int) ([]api.AgentSpend, error) {
	var rows []store.InsightsTopAgentsRow
	err := r.read(ctx, ws, func(s *store.Queries) error {
		var err error
		rows, err = s.InsightsTopAgents(ctx, store.InsightsTopAgentsParams{
			WorkspaceID: ws.ID(), Since: store.Timestamptz(q.Since), Currency: store.Text(&q.Currency), Lim: int32(limit), //nolint:gosec // a small constant
		})
		return err
	})
	if err != nil {
		return nil, err
	}
	out := make([]api.AgentSpend, 0, len(rows))
	for _, row := range rows {
		a, err := amount(row.Total)
		if err != nil {
			return nil, err
		}
		out = append(out, api.AgentSpend{AgentID: row.AgentID.String(), Amount: a})
	}
	return out, nil
}

// Tasks implements api.TaskBoard.
func (r InsightsReads) Tasks(ctx context.Context, ws scope.Workspace, q api.TaskQuery) ([]api.TaskRow, error) {
	agent, ok := agentFilter(q.AgentID)
	if !ok || len(q.Statuses) == 0 || q.Limit <= 0 {
		return nil, nil
	}
	p := store.InsightsTasksParams{WorkspaceID: ws.ID(), Statuses: q.Statuses, AgentID: agent, Ord: string(q.Order), Lim: int32(q.Limit)} //nolint:gosec // bounded by the caller's limits
	if q.EndedSince != nil {
		p.EndedSince = store.Timestamp(*q.EndedSince)
	}
	if q.ScheduledUntil != nil {
		p.ScheduledUntil = store.Timestamptz(*q.ScheduledUntil)
	}
	var rows []store.InsightsTasksRow
	err := r.read(ctx, ws, func(s *store.Queries) error {
		var err error
		rows, err = s.InsightsTasks(ctx, p)
		return err
	})
	if err != nil {
		return nil, err
	}
	out := make([]api.TaskRow, 0, len(rows))
	for _, row := range rows {
		t := api.TaskRow{
			ID: row.ID.String(), AgentID: row.AgentID.String(), Status: row.Status, Description: row.Description,
			TotalCost: row.TotalCost, CreatedAt: row.CreatedAt.Time, UpdatedAt: row.UpdatedAt.Time,
			StartedAt: store.TimestampPtr(row.StartedAt), CompletedAt: store.TimestampPtr(row.CompletedAt),
			Error: store.TextPtr(row.Error), ScheduledAt: store.TimestamptzPtr(row.ScheduledAt),
		}
		out = append(out, t)
	}
	return out, nil
}

// AgentActivity implements api.TaskBoard.
func (r InsightsReads) AgentActivity(ctx context.Context, ws scope.Workspace, agentID string, today, daysSince time.Time, inputStatuses []string) (api.AgentActivity, error) {
	out := api.AgentActivity{Days: map[string]api.DayCounts{}}
	agent, err := uuid.Parse(agentID)
	if err != nil {
		return out, nil
	}
	err = r.read(ctx, ws, func(s *store.Queries) error {
		sum, err := s.InsightsAgentSummary(ctx, store.InsightsAgentSummaryParams{Today: store.Timestamp(today), WorkspaceID: ws.ID(), AgentID: agent})
		if err != nil {
			return err
		}
		out.DoneToday, out.FailedToday, out.LastActivityAt = sum.DoneToday, sum.FailedToday, store.TimestampPtr(sum.LastActivity)
		days, err := s.InsightsAgentDays(ctx, store.InsightsAgentDaysParams{
			InputStatuses: inputStatuses, WorkspaceID: ws.ID(), AgentID: agent, Since: store.Timestamp(daysSince),
		})
		for _, d := range days {
			out.Days[d.Day] = api.DayCounts{Completed: d.Completed, Failed: d.Failed, InputRequired: d.InputRequired}
		}
		return err
	})
	return out, err
}
