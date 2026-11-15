package store

import (
	"context"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
)

// ExecutionFilter narrows a trigger's execution history; nil fields do not narrow.
type ExecutionFilter struct {
	Status *string
	Start  *time.Time
	End    *time.Time
}

// ExecutionMetrics is the aggregate of a trigger's execution rows over a window.
type ExecutionMetrics struct {
	Total, Successful, Failed, TimedOut, Skipped int
	AvgMs                                        float64
	MinMs, MaxMs                                 int
}

// TimelineBucket is one time bucket of a trigger's execution rows.
type TimelineBucket struct {
	Start                               time.Time
	Total, Successful, Failed, TimedOut int
}

// HealthCounts is what the trigger health check counts in a workspace.
type HealthCounts struct {
	Triggers, ActiveCrons int
}

func toExecution(r TriggerExecution) (domain.Execution, error) {
	data, err := unmarshalMap(r.TriggerData)
	if err != nil {
		return domain.Execution{}, err
	}
	return domain.Execution{
		ID: r.ID.String(), TriggerID: deref(fromNullUUID(r.TriggerID)), ExecutedAt: fromNaive(r.ExecutedAt), Status: r.Status,
		TaskID: fromNullUUID(r.TaskID), ExecutionTimeMs: int(r.ExecutionTimeMs), ErrorMessage: fromText(r.ErrorMessage),
		TriggerData: data, WorkflowID: fromText(r.WorkflowID), RunID: fromText(r.RunID), FiredBy: fromText(r.FiredBy),
	}, nil
}

func deref(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

// ExecutionsPage is a page of the trigger's executions, newest first, and how many match f.
func (Triggers) ExecutionsPage(ctx context.Context, s db.Session, triggerID uuid.UUID, f ExecutionFilter, limit, offset int) ([]domain.Execution, int, error) {
	q := New(s.Q())
	tid := uuid.NullUUID{UUID: triggerID, Valid: true}
	rows, err := q.TriggerExecutionsPage(ctx, TriggerExecutionsPageParams{
		WorkspaceID: s.Workspace().ID(), TriggerID: tid, Status: text(f.Status),
		StartTime: nullNaive(f.Start), EndTime: nullNaive(f.End), Lim: int32(limit), Off: int32(offset),
	})
	if err != nil {
		return nil, 0, err
	}
	out := make([]domain.Execution, 0, len(rows))
	for _, r := range rows {
		e, err := toExecution(r)
		if err != nil {
			return nil, 0, err
		}
		out = append(out, e)
	}
	total, err := q.CountTriggerExecutions(ctx, CountTriggerExecutionsParams{
		WorkspaceID: s.Workspace().ID(), TriggerID: tid, Status: text(f.Status),
		StartTime: nullNaive(f.Start), EndTime: nullNaive(f.End),
	})
	return out, int(total), err
}

// Metrics aggregates the trigger's executions since since; nil is the whole history.
func (Triggers) Metrics(ctx context.Context, s db.Session, triggerID uuid.UUID, since *time.Time) (ExecutionMetrics, error) {
	r, err := New(s.Q()).TriggerExecutionMetrics(ctx, TriggerExecutionMetricsParams{
		WorkspaceID: s.Workspace().ID(), TriggerID: uuid.NullUUID{UUID: triggerID, Valid: true}, Since: nullNaive(since),
	})
	return ExecutionMetrics{Total: int(r.Total), Successful: int(r.Successful), Failed: int(r.Failed),
		TimedOut: int(r.TimedOut), Skipped: int(r.Skipped), AvgMs: r.AvgMs, MinMs: int(r.MinMs), MaxMs: int(r.MaxMs)}, err
}

// ExecutionTasks is the task of each of the trigger's executions since since that created one.
func (Triggers) ExecutionTasks(ctx context.Context, s db.Session, triggerID uuid.UUID, since *time.Time) ([]string, error) {
	ids, err := New(s.Q()).TriggerExecutionTasks(ctx, TriggerExecutionTasksParams{
		WorkspaceID: s.Workspace().ID(), TriggerID: uuid.NullUUID{UUID: triggerID, Valid: true}, Since: nullNaive(since),
	})
	if err != nil {
		return nil, err
	}
	out := make([]string, len(ids))
	for i, id := range ids {
		out[i] = id.String()
	}
	return out, nil
}

// Timeline buckets the trigger's executions since since by bucket, oldest first.
func (Triggers) Timeline(ctx context.Context, s db.Session, triggerID uuid.UUID, since time.Time, bucket time.Duration) ([]TimelineBucket, error) {
	rows, err := New(s.Q()).TriggerExecutionTimeline(ctx, TriggerExecutionTimelineParams{
		BucketSeconds: int32(bucket / time.Second), WorkspaceID: s.Workspace().ID(),
		TriggerID: uuid.NullUUID{UUID: triggerID, Valid: true}, Since: naive(since),
	})
	if err != nil {
		return nil, err
	}
	out := make([]TimelineBucket, 0, len(rows))
	for _, r := range rows {
		out = append(out, TimelineBucket{Start: fromNaive(r.TimeBucket), Total: int(r.Total),
			Successful: int(r.Successful), Failed: int(r.Failed), TimedOut: int(r.TimedOut)})
	}
	return out, nil
}

// Health counts the workspace's triggers and its active cron triggers.
func (Triggers) Health(ctx context.Context, s db.Session) (HealthCounts, error) {
	q := New(s.Q())
	n, err := q.CountWorkspaceTriggers(ctx, s.Workspace().ID())
	if err != nil {
		return HealthCounts{}, err
	}
	crons, err := q.CountActiveCronTriggers(ctx, s.Workspace().ID())
	return HealthCounts{Triggers: int(n), ActiveCrons: int(crons)}, err
}

// FiringsSince counts the workspace's trigger firings since since, and how many failed or timed out.
func (Triggers) FiringsSince(ctx context.Context, s db.Session, since time.Time) (total, failures int, err error) {
	r, err := New(s.Q()).CountFiringsSince(ctx, CountFiringsSinceParams{WorkspaceID: s.Workspace().ID(), Since: naive(since)})
	return int(r.Total), int(r.Failures), err
}
