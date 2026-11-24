package handlers

import (
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/insights/service"
)

// utcISO is utc_isoformat: a naive value read as UTC, microseconds only when set.
func utcISO(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/1000 == 0 {
		return t.Format("2006-01-02T15:04:05") + "Z"
	}
	return t.Format("2006-01-02T15:04:05.000000") + "Z"
}

func optTime(t *time.Time) any {
	if t == nil {
		return nil
	}
	return utcISO(*t)
}

func optMoney(d *money.Decimal) any {
	if d == nil {
		return nil
	}
	return *d
}

func optStr(s *string) any {
	if s == nil {
		return nil
	}
	return *s
}

func list[T any](items []T, f func(T) wirejson.Object) []any {
	out := make([]any, len(items))
	for i, x := range items {
		out[i] = f(x)
	}
	return out
}

func daySpendJSON(d service.DaySpend) wirejson.Object {
	return wirejson.Object{{Key: "date", Value: d.Date}, {Key: "usd", Value: d.USD}}
}

func hitlJSON(b service.HITLBlocker) wirejson.Object {
	return wirejson.Object{
		{Key: "task_id", Value: b.TaskID}, {Key: "agent_id", Value: b.AgentID}, {Key: "agent_name", Value: optStr(b.AgentName)},
		{Key: "status", Value: b.Status}, {Key: "description", Value: b.Description}, {Key: "created_at", Value: utcISO(b.CreatedAt)},
	}
}

func taskJSON(t service.DashboardTask) wirejson.Object {
	return wirejson.Object{
		{Key: "task_id", Value: t.TaskID}, {Key: "agent_id", Value: t.AgentID}, {Key: "agent_name", Value: optStr(t.AgentName)},
		{Key: "title", Value: t.Title}, {Key: "status", Value: t.Status},
		{Key: "started_at", Value: optTime(t.StartedAt)}, {Key: "finished_at", Value: optTime(t.FinishedAt)},
		{Key: "cost_usd", Value: optMoney(t.Cost)},
	}
}

func dashboardJSON(d service.Dashboard) wirejson.Object {
	var pct any
	if d.Spend.PctOfCap != nil {
		pct = wirejson.Float(*d.Spend.PctOfCap)
	}
	spend := wirejson.Object{
		{Key: "today_usd", Value: d.Spend.Today}, {Key: "mtd_usd", Value: d.Spend.MTD}, {Key: "cap_usd", Value: optMoney(d.Spend.Cap)},
		{Key: "pct_of_cap", Value: pct}, {Key: "projected_eom_usd", Value: d.Spend.ProjectedEOM},
		{Key: "projection_method", Value: service.ProjectionMethod},
		{Key: "not_covered", Value: list(d.Spend.NotCovered, func(c service.CurrencySpend) wirejson.Object {
			return wirejson.Object{{Key: "currency", Value: c.Currency}, {Key: "amount", Value: c.Amount}}
		})},
		{Key: "mtd_estimate_usd", Value: d.Spend.MTDEstimateUSD},
	}
	ended := func(withDescription bool) func(service.EndedBlocker) wirejson.Object {
		return func(b service.EndedBlocker) wirejson.Object {
			o := wirejson.Object{{Key: "task_id", Value: b.TaskID}, {Key: "agent_id", Value: b.AgentID}, {Key: "agent_name", Value: optStr(b.AgentName)}}
			if withDescription {
				o = append(o, wirejson.Member{Key: "description", Value: b.Description})
			}
			return append(o, wirejson.Member{Key: "error", Value: optStr(b.Error)}, wirejson.Member{Key: "occurred_at", Value: utcISO(b.OccurredAt)})
		}
	}
	blockers := wirejson.Object{
		{Key: "hitl", Value: list(d.Blockers.HITL, hitlJSON)},
		{Key: "awaiting_continuation", Value: list(d.Blockers.AwaitingContinuation, hitlJSON)},
		{Key: "blocked_24h", Value: list(d.Blockers.Blocked24h, ended(true))},
		{Key: "wallet_exhausted", Value: list(d.Blockers.WalletExhausted, func(w service.WalletBlocker) wirejson.Object {
			return wirejson.Object{{Key: "agent_id", Value: w.AgentID}, {Key: "agent_name", Value: optStr(w.AgentName)},
				{Key: "budget_usd", Value: w.Budget}, {Key: "period", Value: w.Period}}
		})},
		{Key: "failed_24h", Value: list(d.Blockers.Failed24h, ended(false))},
	}
	schedule := wirejson.Object{
		{Key: "horizon_days", Value: d.Schedule.HorizonDays},
		{Key: "runs", Value: list(d.Schedule.Runs, func(r service.ScheduledRun) wirejson.Object {
			return wirejson.Object{{Key: "fires_at", Value: utcISO(r.FiresAt)}, {Key: "trigger_id", Value: optStr(r.TriggerID)},
				{Key: "task_id", Value: optStr(r.TaskID)}, {Key: "agent_id", Value: r.AgentID}, {Key: "agent_name", Value: optStr(r.AgentName)},
				{Key: "title", Value: r.Title}}
		})},
		{Key: "frequent", Value: list(d.Schedule.Frequent, func(f service.FrequentSchedule) wirejson.Object {
			return wirejson.Object{{Key: "trigger_id", Value: f.TriggerID}, {Key: "agent_id", Value: f.AgentID}, {Key: "agent_name", Value: optStr(f.AgentName)},
				{Key: "title", Value: f.Title}, {Key: "cron_expression", Value: f.CronExpression}, {Key: "runs_per_day", Value: f.RunsPerDay},
				{Key: "next_run_at", Value: utcISO(f.NextRunAt)}}
		})},
	}
	health := wirejson.Object{
		{Key: "connections", Value: list(d.Health.Connections, func(c service.BrokenConnection) wirejson.Object {
			return wirejson.Object{{Key: "instance_id", Value: c.InstanceID}, {Key: "name", Value: c.Name}, {Key: "reason", Value: c.Reason},
				{Key: "error", Value: optStr(c.Error)}, {Key: "at", Value: optStr(c.At)}}
		})},
		{Key: "triggers", Value: list(d.Health.Triggers, func(t service.BrokenTrigger) wirejson.Object {
			return wirejson.Object{{Key: "trigger_id", Value: t.TriggerID}, {Key: "name", Value: t.Name}, {Key: "agent_id", Value: t.AgentID},
				{Key: "agent_name", Value: optStr(t.AgentName)}, {Key: "reason", Value: t.Reason},
				{Key: "consecutive_failures", Value: t.ConsecutiveFailures}, {Key: "failure_threshold", Value: t.FailureThreshold},
				{Key: "last_execution_at", Value: optTime(t.LastExecutionAt)}}
		})},
	}
	var usage any
	if d.Usage != nil {
		usage = wirejson.Object{{Key: "cpu_core_hours", Value: d.Usage.CPUCoreHours}, {Key: "memory_gib_hours", Value: d.Usage.MemoryGiBHours},
			{Key: "storage_gib", Value: d.Usage.StorageGiB}}
	}
	return wirejson.Object{
		{Key: "spend", Value: spend}, {Key: "blockers", Value: blockers},
		{Key: "active_tasks", Value: list(d.ActiveTasks, taskJSON)}, {Key: "recent_tasks", Value: list(d.RecentTasks, taskJSON)},
		{Key: "schedule", Value: schedule}, {Key: "daily_spend", Value: list(d.DailySpend, daySpendJSON)},
		{Key: "top_agents", Value: list(d.TopAgents, func(a service.AgentSpend) wirejson.Object {
			return wirejson.Object{{Key: "agent_id", Value: a.AgentID}, {Key: "agent_name", Value: optStr(a.AgentName)}, {Key: "usd", Value: a.USD}}
		})},
		{Key: "health", Value: health}, {Key: "usage", Value: usage},
	}
}

func overviewJSON(o service.Overview) wirejson.Object {
	return wirejson.Object{
		{Key: "cost_today_usd", Value: o.CostToday}, {Key: "cost_mtd_usd", Value: o.CostMTD},
		{Key: "tasks_done_today", Value: o.TasksDoneToday}, {Key: "tasks_failed_today", Value: o.TasksFailedToday},
		{Key: "last_activity_at", Value: optTime(o.LastActivityAt)},
		{Key: "daily_spend", Value: list(o.DailySpend, daySpendJSON)},
		{Key: "daily_tasks", Value: list(o.DailyTasks, func(d service.DayTasks) wirejson.Object {
			return wirejson.Object{{Key: "date", Value: d.Date}, {Key: "completed", Value: d.Completed}, {Key: "failed", Value: d.Failed},
				{Key: "input_required", Value: d.InputRequired}}
		})},
		{Key: "upcoming", Value: list(o.Upcoming, func(u service.UpcomingItem) wirejson.Object {
			return wirejson.Object{{Key: "fires_at", Value: utcISO(u.FiresAt)}, {Key: "kind", Value: u.Kind}, {Key: "title", Value: u.Title},
				{Key: "trigger_id", Value: optStr(u.TriggerID)}, {Key: "task_id", Value: optStr(u.TaskID)},
				{Key: "cron_expression", Value: optStr(u.CronExpression)}}
		})},
	}
}

func settingsJSON(cap *money.Decimal) wirejson.Object {
	return wirejson.Object{{Key: "monthly_cap_usd", Value: optMoney(cap)}}
}

func topologyJSON(t service.Topology) wirejson.Object {
	return wirejson.Object{
		{Key: "nodes", Value: list(t.Nodes, func(n service.Node) wirejson.Object {
			md := n.Metadata
			if md == nil {
				md = wirejson.Object{}
			}
			return wirejson.Object{{Key: "id", Value: n.ID}, {Key: "type", Value: n.Type}, {Key: "label", Value: n.Label},
				{Key: "status", Value: optStr(n.Status)}, {Key: "metadata", Value: md}}
		})},
		{Key: "edges", Value: list(t.Edges, func(e service.Edge) wirejson.Object {
			return wirejson.Object{{Key: "id", Value: e.ID}, {Key: "source", Value: e.Source}, {Key: "target", Value: e.Target}, {Key: "relation", Value: e.Relation}}
		})},
		{Key: "governance", Value: list(t.Governance, func(g service.Overlay) wirejson.Object {
			phases := make([]any, len(g.Phases))
			for i, p := range g.Phases {
				phases[i] = p
			}
			return wirejson.Object{{Key: "interceptor_name", Value: g.Name}, {Key: "category", Value: g.Category}, {Key: "phases", Value: phases}}
		})},
		{Key: "deployment_mode", Value: t.DeploymentMode},
	}
}

func peopleJSON(p service.PeopleAccess) wirejson.Object {
	return wirejson.Object{
		{Key: "workspace_id", Value: p.WorkspaceID},
		{Key: "people", Value: list(p.People, func(x service.Person) wirejson.Object {
			return wirejson.Object{{Key: "user_id", Value: x.UserID}, {Key: "display_name", Value: nil}, {Key: "email", Value: optStr(x.Email)}}
		})},
		{Key: "access", Value: list(p.Access, func(a service.Access) wirejson.Object {
			return wirejson.Object{{Key: "user_id", Value: a.UserID}, {Key: "agent_id", Value: a.AgentID}, {Key: "allowed", Value: a.Allowed}, {Key: "reason", Value: a.Reason}}
		})},
		{Key: "complete", Value: p.Complete}, {Key: "total_people", Value: p.TotalPeople}, {Key: "total_agents", Value: p.TotalAgents},
		{Key: "decision_source", Value: "agent_edge_admission"}, {Key: "directory_status", Value: "available"},
	}
}
