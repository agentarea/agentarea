package api

import (
	"context"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// SpendQuery selects a workspace's current cost lines (no newer line
// supersedes them) since Since: in Currency or with none, of one agent when
// AgentID is set, only the estimated ones when EstimateOnly.
type SpendQuery struct {
	Since        time.Time
	Currency     string
	AgentID      string
	EstimateOnly bool
}

// AgentSpend is what one agent's current lines add up to.
type AgentSpend struct {
	AgentID string
	Amount  money.Decimal
}

// SpendLedger is what the dashboard and the agent overview read of
// cost_entries (CostEntryRepository).
type SpendLedger interface {
	SpendSince(ctx context.Context, ws scope.Workspace, q SpendQuery) (money.Decimal, error)
	// SpendByCurrencySince totals every current line since an instant per
	// currency; "" is the lines stored without one.
	SpendByCurrencySince(ctx context.Context, ws scope.Workspace, since time.Time) (map[string]money.Decimal, error)
	// SpendByDay totals per UTC day, keyed YYYY-MM-DD.
	SpendByDay(ctx context.Context, ws scope.Workspace, q SpendQuery) (map[string]money.Decimal, error)
	// TopAgents is the agents that spent the most, highest first, then by id.
	TopAgents(ctx context.Context, ws scope.Workspace, q SpendQuery, limit int) ([]AgentSpend, error)
}

// TaskOrder is the order a task list is read in.
type TaskOrder string

// Task list orders: newest first by the named moment, or soonest booked first.
const (
	ByUpdated   TaskOrder = "updated"
	ByEnded     TaskOrder = "ended"
	ByActivity  TaskOrder = "activity"
	ByCreated   TaskOrder = "created"
	ByScheduled TaskOrder = "scheduled"
)

// TaskQuery lists a workspace's tasks in Statuses. EndedSince keeps those
// whose completed_at, else updated_at, is at or after it; ScheduledUntil
// keeps those booked at or before it. Timestamps of tasks are naive UTC.
type TaskQuery struct {
	Statuses       []string
	AgentID        string
	EndedSince     *time.Time
	ScheduledUntil *time.Time
	Order          TaskOrder
	Limit          int
}

// TaskRow is a task as a board shows it. TotalCost is result.total_cost as
// JSON text, "" when the result has none.
type TaskRow struct {
	ID          string
	AgentID     string
	Status      string
	Description string
	Error       *string
	TotalCost   string
	CreatedAt   time.Time
	UpdatedAt   time.Time
	StartedAt   *time.Time
	CompletedAt *time.Time
	ScheduledAt *time.Time
}

// DayCounts is one day of an agent's tasks by outcome.
type DayCounts struct {
	Completed     int64
	Failed        int64
	InputRequired int64
}

// AgentActivity is an agent's task counts by their activity moment
// (started_at, else created_at): completed and failed since Today, the
// latest activity, and per day since DaysSince keyed YYYY-MM-DD.
type AgentActivity struct {
	DoneToday      int64
	FailedToday    int64
	LastActivityAt *time.Time
	Days           map[string]DayCounts
}

// TaskBoard is what the dashboard and the agent overview read of tasks.
type TaskBoard interface {
	Tasks(ctx context.Context, ws scope.Workspace, q TaskQuery) ([]TaskRow, error)
	// AgentActivity counts InputStatuses as input required.
	AgentActivity(ctx context.Context, ws scope.Workspace, agentID string, today, daysSince time.Time, inputStatuses []string) (AgentActivity, error)
}
