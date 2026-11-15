package service

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

// ErrAgentNotFound is an agent the workspace does not have (404 "Agent not found").
var ErrAgentNotFound = errors.New("Agent not found") //nolint:staticcheck // Python's detail

// Overview is GET /agents/{agent_id}/overview: one agent's spend, task
// counts and agenda. An unknown agent is ErrAgentNotFound before any
// aggregate, so it never reads as an idle one.
func (s *Service) Overview(ctx context.Context, c authn.Caller, agentID string) (Overview, error) {
	r, ws := s.d.Reads, c.Workspace
	var out Overview
	ok, err := r.Lookup.AgentExists(ctx, ws, agentID)
	if err != nil {
		return out, fmt.Errorf("agent: %w", err)
	}
	if !ok {
		return out, ErrAgentNotFound
	}
	now := s.d.Now().UTC()
	today := utcDay(now)
	monthStart := time.Date(now.Year(), now.Month(), 1, 0, 0, 0, 0, time.UTC)
	billing := s.billingCurrency()

	tasksSince := today.AddDate(0, 0, -(OverviewTaskDays - 1))
	act, err := r.Tasks.AgentActivity(ctx, ws, agentID, today, tasksSince, hitlStatuses())
	if err != nil {
		return out, fmt.Errorf("agent activity: %w", err)
	}
	out.TasksDoneToday, out.TasksFailedToday, out.LastActivityAt = act.DoneToday, act.FailedToday, act.LastActivityAt
	out.DailyTasks = make([]DayTasks, OverviewTaskDays)
	for i := range out.DailyTasks {
		d := tasksSince.AddDate(0, 0, i).Format(time.DateOnly)
		n := act.Days[d]
		out.DailyTasks[i] = DayTasks{Date: d, Completed: n.Completed, Failed: n.Failed, InputRequired: n.InputRequired}
	}

	spendSince := today.AddDate(0, 0, -(DailySpendDays - 1))
	byDay, err := r.Ledger.SpendByDay(ctx, ws, runsapi.SpendQuery{Since: spendSince, Currency: billing, AgentID: agentID})
	if err != nil {
		return out, fmt.Errorf("agent daily spend: %w", err)
	}
	out.DailySpend = DaySeries(spendSince, DailySpendDays, byDay)
	if out.CostToday, err = r.Ledger.SpendSince(ctx, ws, runsapi.SpendQuery{Since: today, Currency: billing, AgentID: agentID}); err != nil {
		return out, fmt.Errorf("agent spend today: %w", err)
	}
	if out.CostMTD, err = r.Ledger.SpendSince(ctx, ws, runsapi.SpendQuery{Since: monthStart, Currency: billing, AgentID: agentID}); err != nil {
		return out, fmt.Errorf("agent spend this month: %w", err)
	}

	out.Upcoming = []UpcomingItem{}
	horizon := now.AddDate(0, 0, OverviewUpcomingDays)
	triggers, err := r.Triggers.CronTriggers(ctx, ws, &agentID)
	if err != nil {
		return out, fmt.Errorf("agent cron triggers: %w", err)
	}
	for _, t := range triggers {
		if t.CronExpression == "" {
			continue
		}
		id, cron := t.ID, t.CronExpression
		fires, _, err := cronRuns(t, now, horizon, OverviewTriggerRuns)
		if err != nil {
			s.d.Log.WarnContext(ctx, "trigger has an unusable schedule", "trigger_id", t.ID, "error", err)
			out.Upcoming = append(out.Upcoming, UpcomingItem{FiresAt: now, Kind: "trigger",
				Title: t.Name + OverviewInvalidSuffix, TriggerID: &id, CronExpression: &cron})
			continue
		}
		for _, at := range fires {
			out.Upcoming = append(out.Upcoming, UpcomingItem{FiresAt: at, Kind: "trigger", Title: t.Name, TriggerID: &id, CronExpression: &cron})
		}
	}
	pending, err := r.Tasks.Tasks(ctx, ws, runsapi.TaskQuery{Statuses: activeStatuses(), AgentID: agentID,
		Order: runsapi.ByCreated, Limit: OverviewPendingLimit})
	if err != nil {
		return out, fmt.Errorf("agent open tasks: %w", err)
	}
	for _, t := range pending {
		at := t.CreatedAt
		if t.StartedAt != nil {
			at = *t.StartedAt
		}
		kind := "pending_task"
		if In(t.Status, runningStatuses()) {
			kind = "running_task"
		}
		title := OverviewUnnamedTitle
		if t.Description != "" {
			title = Cut(t.Description, OverviewTitleLength)
		}
		id := t.ID
		out.Upcoming = append(out.Upcoming, UpcomingItem{FiresAt: at, Kind: kind, Title: title, TaskID: &id})
	}
	slices.SortStableFunc(out.Upcoming, func(a, b UpcomingItem) int { return a.FiresAt.Compare(b.FiresAt) })
	return out, nil
}
