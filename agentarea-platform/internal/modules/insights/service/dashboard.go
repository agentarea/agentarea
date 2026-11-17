package service

import (
	"context"
	"fmt"
	"slices"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/insights/domain"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	streamsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
)

func (s *Service) billingCurrency() string {
	if s.d.Reads.Pricing == nil {
		return string(money.USDAtProviderCost{}.Currency())
	}
	return string(s.d.Reads.Pricing.Currency())
}

func utcDay(t time.Time) time.Time {
	t = t.UTC()
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
}

type names map[string]string

func (n names) of(id string) *string {
	if v, ok := n[id]; ok {
		return &v
	}
	return nil
}

func (s *Service) agentNames(ctx context.Context, ws scope.Workspace) (names, error) {
	all, err := s.d.Reads.Agents.AllAgents(ctx, ws)
	if err != nil {
		return nil, fmt.Errorf("agents: %w", err)
	}
	out := make(names, len(all))
	for _, a := range all {
		out[a.ID] = a.Name
	}
	return out, nil
}

// Dashboard is GET /dashboard: one read of the workspace's spend, blockers,
// runs, schedule and health. Every member sees it.
func (s *Service) Dashboard(ctx context.Context, c authn.Caller) (Dashboard, error) {
	r, ws := s.d.Reads, c.Workspace
	now := s.d.Now().UTC()
	billing := s.billingCurrency()
	today, monthStart := utcDay(now), time.Date(now.Year(), now.Month(), 1, 0, 0, 0, 0, time.UTC)
	var out Dashboard

	cap, err := r.Caps.MonthlyCap(ctx, ws)
	if err != nil {
		return out, fmt.Errorf("spend cap: %w", err)
	}
	todayUSD, err := r.Ledger.SpendSince(ctx, ws, runsapi.SpendQuery{Since: today, Currency: billing})
	if err != nil {
		return out, fmt.Errorf("spend today: %w", err)
	}
	mtd, err := r.Ledger.SpendSince(ctx, ws, runsapi.SpendQuery{Since: monthStart, Currency: billing})
	if err != nil {
		return out, fmt.Errorf("spend this month: %w", err)
	}
	covered, err := r.Caps.CapCurrencies(ctx, ws, billing)
	if err != nil {
		return out, fmt.Errorf("cap currencies: %w", err)
	}
	byCurrency, err := r.Ledger.SpendByCurrencySince(ctx, ws, monthStart)
	if err != nil {
		return out, fmt.Errorf("spend by currency: %w", err)
	}
	estimate, err := r.Ledger.SpendSince(ctx, ws, runsapi.SpendQuery{Since: monthStart, Currency: billing, EstimateOnly: true})
	if err != nil {
		return out, fmt.Errorf("estimated spend: %w", err)
	}
	out.Spend = SpendCard{Today: todayUSD, MTD: mtd, Cap: cap, PctOfCap: PctOfCap(mtd, cap),
		NotCovered: NotCovered(byCurrency, covered), MTDEstimateUSD: estimate}

	agentNames, err := s.agentNames(ctx, ws)
	if err != nil {
		return out, err
	}
	top, err := r.Ledger.TopAgents(ctx, ws, runsapi.SpendQuery{Since: monthStart, Currency: billing}, TopAgentsLimit)
	if err != nil {
		return out, fmt.Errorf("top agents: %w", err)
	}
	out.TopAgents = make([]AgentSpend, 0, len(top))
	for _, a := range top {
		out.TopAgents = append(out.TopAgents, AgentSpend{AgentID: a.AgentID, AgentName: agentNames.of(a.AgentID), USD: a.Amount})
	}

	if out.Blockers, err = s.blockers(ctx, ws, now, agentNames); err != nil {
		return out, err
	}
	active, err := r.Tasks.Tasks(ctx, ws, runsapi.TaskQuery{Statuses: activeStatuses(), Order: runsapi.ByActivity, Limit: TaskListLimit})
	if err != nil {
		return out, fmt.Errorf("active tasks: %w", err)
	}
	out.ActiveTasks = s.dashboardTasks(ctx, active, agentNames, nil, TaskListLimit)
	shown := map[string]bool{}
	for _, b := range slices.Concat(out.Blockers.Blocked24h, out.Blockers.Failed24h) {
		shown[b.TaskID] = true
	}
	recent, err := r.Tasks.Tasks(ctx, ws, runsapi.TaskQuery{Statuses: finishedStatuses(), Order: runsapi.ByEnded, Limit: TaskListLimit + len(shown)})
	if err != nil {
		return out, fmt.Errorf("recent tasks: %w", err)
	}
	out.RecentTasks = s.dashboardTasks(ctx, recent, agentNames, shown, TaskListLimit)

	if out.Health, err = s.health(ctx, ws, agentNames); err != nil {
		return out, err
	}
	if r.Usage != nil {
		u, err := r.Usage.UsageSince(ctx, ws.ID(), monthStart)
		if err != nil {
			return out, fmt.Errorf("runtime usage: %w", err)
		}
		out.Usage = &RuntimeUsage{CPUCoreHours: Quantize(u.CPUCoreHours, 2),
			MemoryGiBHours: Quantize(u.MemoryGiBHours, 2), StorageGiB: Quantize(u.StorageGiB, 6)}
	}
	if out.Schedule, err = s.schedule(ctx, ws, now, agentNames); err != nil {
		return out, err
	}
	since := today.AddDate(0, 0, -(DailySpendDays - 1))
	byDay, err := r.Ledger.SpendByDay(ctx, ws, runsapi.SpendQuery{Since: since, Currency: billing})
	if err != nil {
		return out, fmt.Errorf("daily spend: %w", err)
	}
	out.DailySpend = DaySeries(since, DailySpendDays, byDay)
	out.Spend.ProjectedEOM = ProjectMonthEnd(mtd, byDay, s.d.Now())
	return out, nil
}

func (s *Service) blockers(ctx context.Context, ws scope.Workspace, now time.Time, agentNames names) (Blockers, error) {
	r := s.d.Reads
	var b Blockers
	waiting, err := r.Tasks.Tasks(ctx, ws, runsapi.TaskQuery{
		Statuses: slices.Concat(hitlStatuses(), continuationStatuses()), Order: runsapi.ByUpdated, Limit: 2 * BlockerListLimit,
	})
	if err != nil {
		return b, fmt.Errorf("waiting tasks: %w", err)
	}
	b.HITL, b.AwaitingContinuation = []HITLBlocker{}, []HITLBlocker{}
	for _, t := range waiting {
		hb := HITLBlocker{TaskID: t.ID, AgentID: t.AgentID, AgentName: agentNames.of(t.AgentID), Status: t.Status,
			Description: t.Description, CreatedAt: t.CreatedAt}
		switch {
		case In(t.Status, hitlStatuses()) && len(b.HITL) < BlockerListLimit:
			b.HITL = append(b.HITL, hb)
		case In(t.Status, continuationStatuses()) && len(b.AwaitingContinuation) < BlockerListLimit:
			b.AwaitingContinuation = append(b.AwaitingContinuation, hb)
		}
	}
	exhausted, err := r.Wallets.Exhausted(ctx, ws)
	if err != nil {
		return b, fmt.Errorf("exhausted wallets: %w", err)
	}
	b.WalletExhausted = []WalletBlocker{}
	for _, w := range exhausted {
		b.WalletExhausted = append(b.WalletExhausted, WalletBlocker{AgentID: w.AgentID, AgentName: agentNames.of(w.AgentID), Budget: w.Budget, Period: w.Period})
	}
	dayAgo := now.Add(-24 * time.Hour)
	ended, err := r.Tasks.Tasks(ctx, ws, runsapi.TaskQuery{
		Statuses: slices.Concat(blockedStatuses(), []string{"failed"}), EndedSince: &dayAgo, Order: runsapi.ByEnded, Limit: 2 * BlockerListLimit,
	})
	if err != nil {
		return b, fmt.Errorf("ended tasks: %w", err)
	}
	b.Blocked24h, b.Failed24h = []EndedBlocker{}, []EndedBlocker{}
	for _, t := range ended {
		at := t.UpdatedAt
		if t.CompletedAt != nil {
			at = *t.CompletedAt
		}
		eb := EndedBlocker{TaskID: t.ID, AgentID: t.AgentID, AgentName: agentNames.of(t.AgentID), Description: t.Description, Error: t.Error, OccurredAt: at}
		switch {
		case In(t.Status, blockedStatuses()) && len(b.Blocked24h) < BlockerListLimit:
			b.Blocked24h = append(b.Blocked24h, eb)
		case t.Status == "failed" && len(b.Failed24h) < BlockerListLimit:
			b.Failed24h = append(b.Failed24h, eb)
		}
	}
	return b, nil
}

// dashboardTasks renders rows, leaving out hidden ones, at most limit.
func (s *Service) dashboardTasks(ctx context.Context, rows []runsapi.TaskRow, agentNames names, hidden map[string]bool, limit int) []DashboardTask {
	out := []DashboardTask{}
	for _, t := range rows {
		if hidden[t.ID] || len(out) >= limit {
			continue
		}
		started := t.CreatedAt
		if t.StartedAt != nil {
			started = *t.StartedAt
		}
		finished := t.CompletedAt
		if finished == nil && In(t.Status, finishedStatuses()) {
			u := t.UpdatedAt
			finished = &u
		}
		cost, err := TaskCost(t.TotalCost)
		if err != nil {
			s.d.Log.WarnContext(ctx, "task reports an unreadable total_cost", "task_id", t.ID, "total_cost", t.TotalCost, "error", err)
		}
		out = append(out, DashboardTask{TaskID: t.ID, AgentID: t.AgentID, AgentName: agentNames.of(t.AgentID),
			Title: Cut(t.Description, TitleLength), Status: t.Status, StartedAt: &started, FinishedAt: finished, Cost: cost})
	}
	return out
}

func (s *Service) health(ctx context.Context, ws scope.Workspace, agentNames names) (Health, error) {
	h := Health{Connections: []BrokenConnection{}, Triggers: []BrokenTrigger{}}
	failing, err := s.d.Reads.Connections.FailingMCPInstances(ctx, ws, HealthListLimit)
	if err != nil {
		return h, fmt.Errorf("failing connections: %w", err)
	}
	for _, i := range failing {
		reason, state := "verification_failed", i.Verification
		if st, _ := i.Verification["status"].(string); st != "failed" {
			reason, state = "last_call_failed", i.LastDispatch
		}
		bc := BrokenConnection{InstanceID: i.ID, Name: i.Name, Reason: reason, Error: ConnectionError(state["error"])}
		if at, ok := state["at"].(string); ok {
			bc.At = &at
		}
		h.Connections = append(h.Connections, bc)
	}
	broken, err := s.d.Reads.Triggers.BrokenTriggers(ctx, ws, HealthListLimit)
	if err != nil {
		return h, fmt.Errorf("broken triggers: %w", err)
	}
	for _, t := range broken {
		reason := "stopped_after_failures"
		switch {
		case t.NeedsNewOwner:
			reason = "needs_owner"
		case t.IsActive:
			reason = "failing"
		}
		h.Triggers = append(h.Triggers, BrokenTrigger{TriggerID: t.ID, Name: t.Name, AgentID: t.AgentID, AgentName: agentNames.of(t.AgentID),
			Reason: reason, ConsecutiveFailures: t.ConsecutiveFailures, FailureThreshold: t.FailureThreshold, LastExecutionAt: t.LastExecutionAt})
	}
	return h, nil
}

// cronRuns expands one trigger's schedule; an error is an unusable schedule.
func cronRuns(t streamsapi.CronTrigger, start, end time.Time, limit int) ([]time.Time, domain.Cron, error) {
	c, err := domain.ParseCron(t.CronExpression)
	if err != nil {
		return nil, c, err
	}
	tz := ""
	if t.Timezone != nil {
		tz = *t.Timezone
	}
	loc, err := domain.Zone(tz)
	if err != nil {
		return nil, c, err
	}
	return c.Runs(loc, start, end, limit), c, nil
}

func (s *Service) schedule(ctx context.Context, ws scope.Workspace, now time.Time, agentNames names) (Schedule, error) {
	out := Schedule{HorizonDays: ScheduleHorizonDays, Runs: []ScheduledRun{}, Frequent: []FrequentSchedule{}}
	horizon := now.AddDate(0, 0, ScheduleHorizonDays)
	triggers, err := s.d.Reads.Triggers.CronTriggers(ctx, ws, nil)
	if err != nil {
		return out, fmt.Errorf("cron triggers: %w", err)
	}
	listed := ScheduleHorizonDays * MaxListedRunsPerDay
	for _, t := range triggers {
		if t.CronExpression == "" {
			continue
		}
		fires, c, err := cronRuns(t, now, horizon, listed+1)
		if err != nil {
			s.d.Log.WarnContext(ctx, "trigger has an unusable schedule", "trigger_id", t.ID, "error", err)
			continue
		}
		id := t.ID
		if len(fires) > listed {
			out.Frequent = append(out.Frequent, FrequentSchedule{TriggerID: id, AgentID: t.AgentID, AgentName: agentNames.of(t.AgentID),
				Title: t.Name, CronExpression: t.CronExpression, RunsPerDay: c.RunsPerDay(), NextRunAt: fires[0]})
			continue
		}
		for _, at := range fires {
			out.Runs = append(out.Runs, ScheduledRun{FiresAt: at, TriggerID: &id, AgentID: t.AgentID, AgentName: agentNames.of(t.AgentID), Title: t.Name})
		}
	}
	byFire := func(a, b ScheduledRun) int { return a.FiresAt.Compare(b.FiresAt) }
	slices.SortStableFunc(out.Runs, byFire)
	slices.SortStableFunc(out.Frequent, func(a, b FrequentSchedule) int { return b.RunsPerDay - a.RunsPerDay })
	booked, err := s.d.Reads.Tasks.Tasks(ctx, ws, runsapi.TaskQuery{Statuses: scheduledStatuses(), ScheduledUntil: &horizon,
		Order: runsapi.ByScheduled, Limit: BookedTaskScanLimit})
	if err != nil {
		return out, fmt.Errorf("booked tasks: %w", err)
	}
	if len(booked) == 0 {
		return out, nil
	}
	for _, t := range booked {
		id := t.ID
		out.Runs = append(out.Runs, ScheduledRun{FiresAt: t.ScheduledAt.UTC(), TaskID: &id, AgentID: t.AgentID,
			AgentName: agentNames.of(t.AgentID), Title: Cut(t.Description, TitleLength)})
	}
	slices.SortStableFunc(out.Runs, byFire)
	return out, nil
}
