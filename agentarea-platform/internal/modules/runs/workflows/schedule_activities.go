package workflows

import (
	"context"
	"fmt"
	"time"

	"go.temporal.io/sdk/activity"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/service"
)

// ScheduleActivities adapt the scheduling use cases (ACTIVITIES.md steps 13-14) to Temporal.
type ScheduleActivities struct {
	svc *service.Scheduling
}

// NewScheduleActivities is the activity side of the reconciler, the cron sync and the triggers.
func NewScheduleActivities(svc *service.Scheduling) *ScheduleActivities {
	return &ScheduleActivities{svc: svc}
}

func (a *ScheduleActivities) byName() map[string]any {
	return map[string]any{
		api.ActivityStartUndispatchedTasks:    a.StartUndispatchedTasks,
		api.ActivitySyncCronSchedules:         a.SyncCronSchedules,
		api.ActivityEvaluateTriggerConditions: a.EvaluateTriggerConditions,
		api.ActivityExecuteTrigger:            a.ExecuteTrigger,
		api.ActivityRecordTriggerExecution:    a.RecordTriggerExecution,
		api.ActivityFireTriggerBatch:          a.FireTriggerBatch,
		api.ActivityCloseTriggerBatch:         a.CloseTriggerBatch,
	}
}

// RegisterScheduleActivities registers the step 13-14 activities of queue on w.
func RegisterScheduleActivities(w durable.Worker, a *ScheduleActivities, queue Queue) {
	fns := a.byName()
	for _, s := range ActivitySpecs() {
		if fn, ok := fns[s.Name]; ok && s.Queue == queue {
			w.RegisterActivity(durable.Activity{Name: s.Name, Kind: s.Kind, Fn: fn})
		}
	}
}

// QueueActivities is every activity name ActivitySpecs places on queue.
func QueueActivities(queue Queue) []string {
	var out []string
	for _, s := range ActivitySpecs() {
		if s.Queue == queue {
			out = append(out, s.Name)
		}
	}
	return out
}

func (a *ScheduleActivities) StartUndispatchedTasks(ctx context.Context) (StartUndispatchedResult, error) {
	n, err := a.svc.StartUndispatched(ctx)
	return StartUndispatchedResult{Started: n}, err
}

func (a *ScheduleActivities) SyncCronSchedules(ctx context.Context) error {
	_, err := a.svc.SyncCronSchedules(ctx)
	return err
}

func (a *ScheduleActivities) EvaluateTriggerConditions(ctx context.Context, req EvaluateTriggerConditionsRequest) (EvaluateTriggerConditionsResult, error) {
	stop := heartbeating(ctx)
	defer stop()
	return EvaluateTriggerConditionsResult{TriggerID: req.TriggerID, ConditionsMet: a.svc.EvaluateTriggerConditions(ctx, req.TriggerID, req.EventData)}, nil
}

func (a *ScheduleActivities) ExecuteTrigger(ctx context.Context, req ExecuteTriggerRequest) (ExecuteTriggerResult, error) {
	stop := heartbeating(ctx)
	defer stop()
	run, err := a.svc.ExecuteTrigger(ctx, req.TriggerID, req.ExecutionData, activity.GetInfo(ctx).WorkflowExecution.ID)
	if err != nil {
		return ExecuteTriggerResult{}, err
	}
	data := req.ExecutionData
	if data == nil {
		data = map[string]any{}
	}
	return ExecuteTriggerResult{
		TriggerID: req.TriggerID, Status: run.Status, TaskID: run.TaskID, ExecutionID: run.ExecutionID,
		Duration: run.Elapsed, Reason: run.Reason, Error: run.Error, TriggerData: data,
	}, nil
}

func (a *ScheduleActivities) RecordTriggerExecution(ctx context.Context, req RecordTriggerExecutionRequest) (RecordTriggerExecutionResult, error) {
	d := req.ExecutionData
	status, ok := d["status"].(string)
	if !ok {
		return RecordTriggerExecutionResult{}, fmt.Errorf("execution data of trigger %s has no status", req.TriggerID)
	}
	rec := service.TriggerExecutionRecord{Status: status}
	if ms, ok := numberOf(d["execution_time_ms"]); ok {
		rec.ExecutionTime = time.Duration(ms * float64(time.Millisecond))
	}
	rec.ErrorMessage, _ = d["error_message"].(string)
	rec.TaskID, _ = d["task_id"].(string)
	rec.TriggerData, _ = d["trigger_data"].(map[string]any)
	if rec.TriggerData == nil {
		rec.TriggerData = map[string]any{}
	}
	out, err := a.svc.RecordTriggerExecution(ctx, req.TriggerID, rec)
	if err != nil {
		return RecordTriggerExecutionResult{}, err
	}
	return RecordTriggerExecutionResult{ExecutionID: out.ID, TriggerID: req.TriggerID, Status: status, RecordedAt: out.ExecutedAt}, nil
}

func batchOf(b OpenBatch) service.TriggerBatch {
	return service.TriggerBatch{
		TriggerID: b.Spec.TriggerID, SubscriptionID: b.Spec.SubscriptionID, WorkspaceID: b.Spec.WorkspaceID,
		ConfiguredBy: b.Spec.ConfiguredBy, Caller: b.Spec.Caller, WorkflowID: b.WorkflowID, EventIDs: b.EventIDs, Reason: b.Reason,
	}
}

func (a *ScheduleActivities) FireTriggerBatch(ctx context.Context, b OpenBatch) (BatchResult, error) {
	n, err := a.svc.FireBatch(ctx, batchOf(b))
	return BatchResult{Events: n}, err
}

func (a *ScheduleActivities) CloseTriggerBatch(ctx context.Context, b OpenBatch) (BatchResult, error) {
	n, err := a.svc.CloseBatch(ctx, batchOf(b))
	return BatchResult{Events: n}, err
}
