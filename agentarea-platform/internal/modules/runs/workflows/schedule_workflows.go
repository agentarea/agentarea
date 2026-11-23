package workflows

import (
	"errors"
	"fmt"
	"time"

	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

// AgentQueueWorkflows are the workflows the agent queue runs besides the agent run.
func AgentQueueWorkflows() []durable.Workflow {
	return []durable.Workflow{
		AgentWorkflow(),
		{Name: api.WorkflowRemoteDelegation, Fn: RemoteDelegationWorkflow},
		{Name: api.WorkflowUndispatchedTasks, Fn: UndispatchedTaskReconcilerWorkflow},
	}
}

// TriggerQueueWorkflows are the trigger queue's workflows.
func TriggerQueueWorkflows() []durable.Workflow {
	return []durable.Workflow{
		{Name: api.WorkflowTriggerExecution, Fn: TriggerExecutionWorkflow},
		{Name: api.WorkflowTriggerBatch, Fn: TriggerBatchWorkflow},
		{Name: api.WorkflowCronScheduleSync, Fn: CronScheduleSyncWorkflow},
	}
}

// specCtx schedules an activity with its spec's options on the workflow's own queue.
func specCtx(ctx workflow.Context, name string, nonRetryableTypes ...string) workflow.Context {
	s := spec(name)
	p := retryPolicy(s.Retry)
	p.NonRetryableErrorTypes = nonRetryableTypes
	return workflow.WithActivityOptions(ctx, workflow.ActivityOptions{
		StartToCloseTimeout:    s.StartToClose,
		ScheduleToCloseTimeout: s.ScheduleToClose,
		HeartbeatTimeout:       s.Heartbeat,
		RetryPolicy:            p,
	})
}

// UndispatchedTaskReconcilerWorkflow starts tasks left pending with no
// workflow; one attempt, the next tick is the retry.
func UndispatchedTaskReconcilerWorkflow(ctx workflow.Context) (int, error) {
	var res StartUndispatchedResult
	err := workflow.ExecuteActivity(specCtx(ctx, api.ActivityStartUndispatchedTasks), api.ActivityStartUndispatchedTasks).Get(ctx, &res)
	return res.Started, err
}

// CronScheduleSyncWorkflow brings every cron trigger's schedule to what its
// trigger says; one attempt, the next tick is the retry.
func CronScheduleSyncWorkflow(ctx workflow.Context) error {
	return workflow.ExecuteActivity(specCtx(ctx, api.ActivitySyncCronSchedules), api.ActivitySyncCronSchedules).Get(ctx, nil)
}

// scheduledStartTime is the slot Temporal stamps on every workflow a schedule starts.
func scheduledStartTime() temporal.SearchAttributeKeyTime {
	return temporal.NewSearchAttributeKeyTime("TemporalScheduledStartTime")
}

// SignalCancelExecution and QueryExecutionStatus are the trigger firing's handlers.
const (
	SignalCancelExecution = "cancel_execution"
	QueryExecutionStatus  = "get_execution_status"
)

// The error types each trigger activity does not retry (trigger_execution_workflow.py).
func evaluateNonRetryable() []string {
	return []string{
		"TriggerValidationError", "TriggerNotFoundError", "InvalidConditionError", "TriggerDisabledError",
		"AgentNotFoundError", "AuthenticationError", "AuthorizationError",
	}
}

func executeNonRetryable() []string {
	return []string{
		"TriggerValidationError", "TriggerNotFoundError", "TriggerDisabledError", "AgentNotFoundError",
		"InvalidConfigurationError", "AuthenticationError", "AuthorizationError", "RateLimitExceededError",
		"CircuitBreakerOpenError",
	}
}

func recordNonRetryable() []string {
	return []string{"DatabaseConnectionError", "PermanentDatabaseError"}
}

const (
	triggerDefaultTimeout = 15 * time.Minute
	triggerMaxTimeout     = 30 * time.Minute
)

// TriggerExecutionWorkflow is one firing of a cron trigger, started by its
// schedule: evaluate the conditions, fire, and record a failed firing once
// after the last attempt (trigger_execution_workflow.py).
func TriggerExecutionWorkflow(ctx workflow.Context, triggerID string, executionData map[string]any) (map[string]any, error) {
	cancelled := false
	start := workflow.Now(ctx)
	if err := workflow.SetQueryHandler(ctx, QueryExecutionStatus, func() (map[string]any, error) {
		now := workflow.Now(ctx)
		return map[string]any{
			"is_cancelled": cancelled, "workflow_time": pyISOTime(now), "execution_start_time": pyISOTime(start),
			"execution_duration_ms": now.Sub(start).Milliseconds(), "is_running": true,
		}, nil
	}); err != nil {
		return nil, err
	}
	cancelSignal := workflow.GetSignalChannel(ctx, SignalCancelExecution)
	workflow.Go(ctx, func(ctx workflow.Context) {
		for {
			cancelSignal.Receive(ctx, nil)
			cancelled = true
		}
	})
	timeout := triggerDefaultTimeout
	if v, ok := numberOf(executionData["timeout_minutes"]); ok {
		timeout = time.Duration(v * float64(time.Minute))
	}
	timeout = min(timeout, triggerMaxTimeout)
	timeoutMinutes := timeout.Minutes()

	scheduled, ok := workflow.GetTypedSearchAttributes(ctx).GetTime(scheduledStartTime())
	if !ok {
		return nil, temporal.NewNonRetryableApplicationError(
			fmt.Sprintf("Trigger %s execution was not started by its schedule", triggerID), "ApplicationError", nil)
	}
	data := map[string]any{}
	for k, v := range executionData {
		data[k] = v
	}
	data["scheduled_time"] = pyISOTime(scheduled)
	elapsed := func() int64 { return workflow.Now(ctx).Sub(start).Milliseconds() }

	if cancelled {
		return map[string]any{
			"trigger_id": triggerID, "status": "cancelled", "reason": "workflow_cancelled",
			"execution_time_ms": 0, "workflow_timeout_minutes": timeoutMinutes,
		}, nil
	}
	var conditions EvaluateTriggerConditionsResult
	err := workflow.ExecuteActivity(specCtx(ctx, api.ActivityEvaluateTriggerConditions, evaluateNonRetryable()...),
		api.ActivityEvaluateTriggerConditions, EvaluateTriggerConditionsRequest{TriggerID: triggerID, EventData: data}).Get(ctx, &conditions)
	if err == nil && !conditions.ConditionsMet {
		return map[string]any{
			"trigger_id": triggerID, "status": "skipped", "reason": "conditions_not_met",
			"execution_time_ms": elapsed(), "workflow_timeout_minutes": timeoutMinutes,
		}, nil
	}
	var res ExecuteTriggerResult
	if err == nil {
		err = workflow.ExecuteActivity(specCtx(ctx, api.ActivityExecuteTrigger, executeNonRetryable()...),
			api.ActivityExecuteTrigger, ExecuteTriggerRequest{TriggerID: triggerID, ExecutionData: data}).Get(ctx, &res)
	}
	if err != nil {
		workflow.GetLogger(ctx).Error("trigger execution failed", "trigger_id", triggerID, "error", err)
		return nil, recordFailedFiring(ctx, triggerID, err, elapsed(), timeoutMinutes)
	}
	out := map[string]any{
		"trigger_id": res.TriggerID, "status": res.Status, "task_id": nullable(res.TaskID),
		"execution_id": nullable(res.ExecutionID), "execution_time_ms": res.Duration.Milliseconds(),
		"reason": nullable(res.Reason), "error": nullable(res.Error), "trigger_data": res.TriggerData,
		"workflow_timeout_minutes": timeoutMinutes, "total_workflow_time_ms": elapsed(),
	}
	if out["trigger_data"] == nil {
		out["trigger_data"] = map[string]any{}
	}
	return out, nil
}

// recordFailedFiring records a firing that failed after its last attempt and
// returns the workflow's error. An activity's ApplicationError is recorded
// with its own message; anything else (a timeout, a cancel) as unexpected.
func recordFailedFiring(ctx workflow.Context, triggerID string, err error, elapsedMS int64, timeoutMinutes float64) error {
	data := map[string]any{
		"status": "failed", "execution_time_ms": elapsedMS, "executed_at": pyISOTime(workflow.Now(ctx)),
		"workflow_timeout_minutes": timeoutMinutes,
	}
	var appErr *temporal.ApplicationError
	var out error
	if errors.As(err, &appErr) {
		data["error_message"], data["error_type"] = appErr.Message(), "ApplicationError"
		out = err
	} else {
		msg := err.Error()
		var actErr *temporal.ActivityError
		if errors.As(err, &actErr) && actErr.Unwrap() != nil {
			msg = actErr.Unwrap().Error()
		}
		data["error_message"], data["error_type"], data["is_unexpected_error"] = "Unexpected error: "+msg, "ActivityError", true
		out = temporal.NewApplicationErrorWithCause("Unexpected trigger execution error: "+msg, "ApplicationError", err)
	}
	rec := RecordTriggerExecutionRequest{TriggerID: triggerID, ExecutionData: data}
	if rerr := workflow.ExecuteActivity(specCtx(ctx, api.ActivityRecordTriggerExecution, recordNonRetryable()...),
		api.ActivityRecordTriggerExecution, rec).Get(ctx, nil); rerr != nil {
		return rerr
	}
	return out
}

func numberOf(v any) (float64, bool) {
	switch n := v.(type) {
	case float64:
		return n, true
	case int:
		return float64(n), true
	case int64:
		return float64(n), true
	}
	return 0, false
}

// pyISOTime is datetime.isoformat() of an aware UTC time.
func pyISOTime(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/1000 == 0 {
		return t.Format("2006-01-02T15:04:05+00:00")
	}
	return t.Format("2006-01-02T15:04:05.000000+00:00")
}

// SignalAddEvent hands an admitted event to a trigger's open batch.
const SignalAddEvent = "add_event"

// BatchCancelledReason is why a cancelled batch's events were skipped.
const BatchCancelledReason = "the batch was cancelled before it fired"

// TriggerBatchWorkflow holds one open batch of a windowed stream trigger: one
// timer, one firing. Each event id joins once; events that arrive while it
// fires open the next batch in a new run. Cancelled, the batch closes and its
// events are recorded as skipped (trigger_batch_workflow.py).
func TriggerBatchWorkflow(ctx workflow.Context, s BatchSpec) (int, error) {
	var pending []string
	seen := map[string]bool{}
	add := func(id string) {
		if seen[id] {
			return
		}
		seen[id] = true
		pending = append(pending, id)
	}
	for _, id := range s.Pending {
		add(id)
	}
	events := workflow.GetSignalChannel(ctx, SignalAddEvent)
	workflow.Go(ctx, func(ctx workflow.Context) {
		for {
			var id string
			if !events.Receive(ctx, &id) {
				return
			}
			add(id)
		}
	})
	info := workflow.GetInfo(ctx)
	wid := info.WorkflowExecution.ID
	maxEvents := max(s.MaxEvents, 1)

	waitErr := workflow.Await(ctx, func() bool { return len(pending) > 0 })
	if waitErr == nil {
		if s.Window > 0 {
			_, waitErr = workflow.AwaitWithTimeout(ctx, s.Window, func() bool { return len(pending) >= maxEvents })
		} else {
			waitErr = workflow.Await(ctx, func() bool { return len(pending) >= maxEvents })
		}
	}
	var batch []string
	if waitErr == nil {
		batch = append([]string(nil), pending[:min(len(pending), maxEvents)]...)
		waitErr = workflow.ExecuteActivity(specCtx(ctx, api.ActivityFireTriggerBatch), api.ActivityFireTriggerBatch,
			OpenBatch{Spec: s, WorkflowID: wid, EventIDs: batch}).Get(ctx, nil)
	}
	if waitErr != nil {
		if !temporal.IsCanceledError(waitErr) && ctx.Err() == nil {
			return 0, waitErr
		}
		dctx, _ := workflow.NewDisconnectedContext(ctx)
		closing := OpenBatch{Spec: s, WorkflowID: wid, EventIDs: append([]string(nil), pending...), Reason: BatchCancelledReason}
		if err := workflow.ExecuteActivity(specCtx(dctx, api.ActivityCloseTriggerBatch), api.ActivityCloseTriggerBatch, closing).Get(dctx, nil); err != nil {
			return 0, err
		}
		return 0, nil
	}
	for {
		var id string
		if !events.ReceiveAsync(&id) {
			break
		}
		add(id)
	}
	if rest := pending[len(batch):]; len(rest) > 0 {
		next := s
		next.Pending = append([]string(nil), rest...)
		return 0, workflow.NewContinueAsNewError(ctx, api.WorkflowTriggerBatch, next)
	}
	return len(batch), nil
}
