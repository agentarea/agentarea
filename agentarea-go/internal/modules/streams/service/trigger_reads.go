package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store"
)

// ExecutionQuery is the execution history route's filters and page.
type ExecutionQuery struct {
	Status   *string
	Start    *time.Time
	End      *time.Time
	Page     int
	PageSize int
}

// CostedExecution is an execution row with what its task has spent; nil when it created
// no task, the task is gone, or no task port is wired.
type CostedExecution struct {
	domain.Execution
	CostUSD *float64
}

// ExecutionPage is a page of a trigger's executions.
type ExecutionPage struct {
	Executions []CostedExecution
	Total      int
	Page       int
	PageSize   int
	HasNext    bool
}

// Metrics is get_execution_metrics plus the trigger's spend.
type Metrics struct {
	store.ExecutionMetrics
	PeriodHours      *int
	SuccessRate      float64
	FailureRate      float64
	TotalCostUSD     float64
	AvgCostUSD       float64
	CostedExecutions int
}

// TriggerStatus is the status route's answer: the trigger, and its schedule when it has one.
type TriggerStatus struct {
	Trigger      domain.Trigger
	ScheduleInfo map[string]any
}

func (s *Service) existing(ctx context.Context, id string) (uuid.UUID, error) {
	if _, err := s.Get(ctx, id); err != nil {
		return uuid.Nil, err
	}
	return uuid.Parse(id)
}

// Executions is get_execution_history: the page, newest first, with each run's task cost.
func (s *Service) Executions(ctx context.Context, id string, q ExecutionQuery) (ExecutionPage, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return ExecutionPage{}, err
	}
	u, err := s.existing(ctx, id)
	if err != nil {
		return ExecutionPage{}, err
	}
	f := store.ExecutionFilter{Start: q.Start, End: q.End}
	if q.Status != nil && *q.Status != "" {
		st := strings.ToLower(*q.Status)
		if !domain.ValidExecutionStatus(st) {
			return ExecutionPage{}, domain.Invalid("Invalid status: " + *q.Status)
		}
		f.Status = &st
	}
	offset := (q.Page - 1) * q.PageSize
	var rows []domain.Execution
	var total int
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		rows, total, err = s.st.ExecutionsPage(ctx, sess, u, f, q.PageSize, offset)
		return err
	})
	if err != nil {
		return ExecutionPage{}, err
	}
	costs, err := s.costs(ctx, taskIDs(rows))
	if err != nil {
		return ExecutionPage{}, err
	}
	out := ExecutionPage{Executions: make([]CostedExecution, 0, len(rows)), Total: total, Page: q.Page,
		PageSize: q.PageSize, HasNext: offset+q.PageSize < total}
	for _, e := range rows {
		ce := CostedExecution{Execution: e}
		if e.TaskID != nil {
			if v, ok := costs[*e.TaskID]; ok {
				ce.CostUSD = &v
			}
		}
		out.Executions = append(out.Executions, ce)
	}
	return out, nil
}

func taskIDs(rows []domain.Execution) []string {
	var ids []string
	for _, e := range rows {
		if e.TaskID != nil {
			ids = append(ids, *e.TaskID)
		}
	}
	return ids
}

// costs is the spend of each existing workspace task in ids (own_cost, else total_cost, else 0).
func (s *Service) costs(ctx context.Context, ids []string) (map[string]float64, error) {
	out := map[string]float64{}
	if len(ids) == 0 || s.d.TaskReads == nil {
		return out, nil
	}
	c, err := callerOf(ctx)
	if err != nil {
		return nil, err
	}
	seen := map[string]bool{}
	unique := make([]string, 0, len(ids))
	for _, id := range ids {
		if !seen[id] {
			seen[id] = true
			unique = append(unique, id)
		}
	}
	got, err := s.d.TaskReads.Costs(ctx, c.Workspace, unique)
	if err != nil {
		return nil, err
	}
	for id, tc := range got {
		v := 0.0
		if tc.CostUSD != nil {
			v = *tc.CostUSD
		}
		out[id] = v
	}
	return out, nil
}

// Metrics is get_execution_metrics over the last hours (nil: the whole history) with the spend
// of the tasks those runs created; rates are over the runs that tried to start a task.
func (s *Service) Metrics(ctx context.Context, id string, hours *int) (Metrics, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return Metrics{}, err
	}
	u, err := s.existing(ctx, id)
	if err != nil {
		return Metrics{}, err
	}
	var since *time.Time
	if hours != nil {
		t := s.now().Add(-time.Duration(*hours) * time.Hour)
		since = &t
	}
	var m store.ExecutionMetrics
	var tasks []string
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		if m, err = s.st.Metrics(ctx, sess, u, since); err != nil {
			return err
		}
		tasks, err = s.st.ExecutionTasks(ctx, sess, u, since)
		return err
	})
	if err != nil {
		return Metrics{}, err
	}
	out := Metrics{ExecutionMetrics: m, PeriodHours: hours}
	if attempts := m.Successful + m.Failed + m.TimedOut; attempts > 0 {
		out.SuccessRate = float64(m.Successful) / float64(attempts) * 100
		out.FailureRate = float64(m.Failed+m.TimedOut) / float64(attempts) * 100
	}
	costs, err := s.costs(ctx, tasks)
	if err != nil {
		return Metrics{}, err
	}
	total := 0.0
	for _, t := range tasks {
		if v, ok := costs[t]; ok {
			total += v
			out.CostedExecutions++
		}
	}
	out.TotalCostUSD = round6(total)
	if out.CostedExecutions > 0 {
		out.AvgCostUSD = round6(total / float64(out.CostedExecutions))
	}
	return out, nil
}

func round6(v float64) float64 { return math.RoundToEven(v*1e6) / 1e6 }

// Timeline is get_execution_timeline: the last hours of executions in buckets of bucketMinutes.
func (s *Service) Timeline(ctx context.Context, id string, hours, bucketMinutes int) ([]store.TimelineBucket, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return nil, err
	}
	u, err := s.existing(ctx, id)
	if err != nil {
		return nil, err
	}
	since := s.now().Add(-time.Duration(hours) * time.Hour)
	var out []store.TimelineBucket
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		out, err = s.st.Timeline(ctx, sess, u, since, time.Duration(bucketMinutes)*time.Minute)
		return err
	})
	return out, err
}

// Correlations is get_execution_correlations: a page of executions, newest first, and the total.
func (s *Service) Correlations(ctx context.Context, id string, page, pageSize int) ([]domain.Execution, int, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return nil, 0, err
	}
	u, err := s.existing(ctx, id)
	if err != nil {
		return nil, 0, err
	}
	var rows []domain.Execution
	var total int
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		rows, total, err = s.st.ExecutionsPage(ctx, sess, u, store.ExecutionFilter{}, pageSize, (page-1)*pageSize)
		return err
	})
	return rows, total, err
}

// Status is get_trigger_status: the trigger with a cron trigger's schedule as Temporal
// describes it; a schedule that cannot be read is logged and left out.
func (s *Service) Status(ctx context.Context, id string) (TriggerStatus, error) {
	t, err := s.Get(ctx, id)
	if err != nil {
		return TriggerStatus{}, err
	}
	out := TriggerStatus{Trigger: t}
	if t.Type == domain.TypeCron {
		out.ScheduleInfo = s.scheduleInfo(ctx, t.ID)
	}
	return out, nil
}

func (s *Service) scheduleInfo(ctx context.Context, triggerID string) map[string]any {
	if s.d.Schedules == nil {
		s.log.WarnContext(ctx, "no scheduler; cannot describe the schedule of a trigger", "trigger_id", triggerID)
		return nil
	}
	id := "cron-trigger-" + triggerID
	info, err := s.d.Schedules.Describe(ctx, id)
	if errors.Is(err, durable.ErrNotFound) {
		return nil
	}
	if err != nil {
		s.log.ErrorContext(ctx, "could not describe the schedule of a cron trigger", "trigger_id", triggerID, "error", err)
		return nil
	}
	crons := info.Cron
	if len(crons) == 0 {
		crons = cronFromArgs(info)
	}
	next := make([]string, 0, len(info.NextActions))
	for _, t := range info.NextActions {
		next = append(next, isoUTC(t))
	}
	recent := make([]map[string]any, 0, len(info.RecentActions))
	for _, a := range info.RecentActions {
		recent = append(recent, map[string]any{
			"scheduled_time": optionalISO(a.ScheduledTime), "actual_time": optionalISO(a.ActualTime),
			"start_workflow_result": optionalString(a.WorkflowID),
		})
	}
	if crons == nil {
		crons = []string{}
	}
	return map[string]any{
		"schedule_id": id, "trigger_id": triggerID, "cron_expressions": crons, "timezone": info.TimeZone,
		"paused": info.Paused, "note": info.Note, "next_action_times": next, "recent_actions": recent,
	}
}

// cronFromArgs recovers the expression a schedule was created with from its action's
// {"cron_expression": ...} argument; Temporal reports cron specs back as calendars.
func cronFromArgs(info durable.ScheduleInfo) []string {
	for _, raw := range info.Args {
		var payload map[string]any
		if err := json.Unmarshal(raw, &payload); err != nil {
			continue
		}
		if c, ok := payload["cron_expression"].(string); ok && c != "" {
			return []string{c}
		}
	}
	return nil
}

func isoUTC(t time.Time) string { return t.UTC().Format(time.RFC3339Nano) }

func optionalISO(t time.Time) any {
	if t.IsZero() {
		return nil
	}
	return isoUTC(t)
}

func optionalString(s string) any {
	if s == "" {
		return nil
	}
	return s
}

func component(status, message string, details map[string]any) map[string]any {
	if details == nil {
		details = map[string]any{}
	}
	return map[string]any{"status": status, "message": message, "details": details}
}

// Health is check_all_components for the caller's workspace; it never fails, a broken
// component reports itself unhealthy.
func (s *Service) Health(ctx context.Context) map[string]any {
	now := s.now()
	components := map[string]any{}
	var counts store.HealthCounts
	var hour, hourFailures, day, dayFailures int
	c, err := callerOf(ctx)
	if err == nil {
		started := time.Now()
		err = s.read(ctx, c.Workspace, func(sess db.Session) error {
			if counts, err = s.st.Health(ctx, sess); err != nil {
				return err
			}
			if hour, hourFailures, err = s.st.FiringsSince(ctx, sess, now.Add(-time.Hour)); err != nil {
				return err
			}
			day, dayFailures, err = s.st.FiringsSince(ctx, sess, now.Add(-24*time.Hour))
			return err
		})
		elapsed := float64(time.Since(started).Microseconds()) / 1000
		if err == nil {
			components["database"] = component("healthy", "Database connectivity OK", map[string]any{
				"trigger_count": counts.Triggers, "recent_executions": hour,
				"response_time_ms": math.Round(elapsed*100) / 100,
			})
		}
	}
	if err != nil {
		s.log.ErrorContext(ctx, "trigger health check: database failed", "error", err)
		components["database"] = component("unhealthy", "Database connectivity failed: "+err.Error(), map[string]any{"error": err.Error()})
		components["execution_metrics"] = component("unhealthy", "Execution metrics check failed: "+err.Error(), map[string]any{"error": err.Error()})
	} else {
		components["execution_metrics"] = executionHealth(hour, hourFailures, day, dayFailures)
	}
	if s.d.Schedules == nil {
		components["temporal_schedules"] = component("unknown", "Temporal schedule manager not available", nil)
	} else {
		details := map[string]any{"task_queue": s.d.TriggerQueue}
		if err == nil {
			details["active_schedules"] = counts.ActiveCrons
		}
		components["temporal_schedules"] = component("healthy", "Temporal schedules operational", details)
	}
	components["webhook_manager"] = component("healthy", "Webhook manager operational", map[string]any{
		"base_url": s.webhookBase(), "rate_limit_per_minute": s.d.Settings.WebhookRate,
	})
	overall := "healthy"
	for _, v := range components {
		switch v.(map[string]any)["status"] {
		case "unhealthy":
			overall = "unhealthy"
		case "degraded":
			if overall == "healthy" {
				overall = "degraded"
			}
		}
	}
	return map[string]any{"overall_status": overall, "timestamp": isoUTC(now), "components": components, "service": "triggers"}
}

func (s *Service) webhookBase() string {
	base := s.d.WebhookURL
	if base == "" {
		base = s.d.APIURL
	}
	return strings.TrimRight(base, "/") + "/webhooks"
}

func executionHealth(hour, hourFailures, day, dayFailures int) map[string]any {
	rateHour := float64(hourFailures) / float64(max(hour, 1)) * 100
	rateDay := float64(dayFailures) / float64(max(day, 1)) * 100
	status, message := "healthy", "Execution metrics normal"
	switch {
	case rateHour > 50:
		status, message = "unhealthy", fmt.Sprintf("High failure rate in last hour: %.1f%%", rateHour)
	case rateHour > 25:
		status, message = "degraded", fmt.Sprintf("Elevated failure rate in last hour: %.1f%%", rateHour)
	}
	return component(status, message, map[string]any{
		"executions_last_hour": hour, "executions_last_day": day,
		"failure_rate_hour_percent": math.Round(rateHour*10) / 10, "failure_rate_day_percent": math.Round(rateDay*10) / 10,
		"failures_last_hour": hourFailures, "failures_last_day": dayFailures,
	})
}
