package api

import (
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
)

// Temporal Schedules the runs workflows are started by.
const (
	// ScheduleUndispatchedTasks starts the reconciler every ReconcileEvery
	// (undispatched_task_reconciler_workflow.py SCHEDULE_ID).
	ScheduleUndispatchedTasks = "undispatched-task-reconciler"
	// ScheduleCronSync starts the cron schedule sync every CronSyncEvery
	// (cron_schedule_sync_workflow.py SCHEDULE_ID).
	ScheduleCronSync = "cron-schedule-sync"
	// CronTriggerSchedulePrefix names a cron trigger's schedule (SCHEDULE_ID_PREFIX).
	CronTriggerSchedulePrefix = "cron-trigger-"
	// CronCatchupWindow is how late a slot missed while Temporal was down still fires.
	CronCatchupWindow = time.Hour
	ReconcileEvery    = time.Minute
	CronSyncEvery     = 5 * time.Minute
)

// UndispatchedTasksSchedule starts UndispatchedTaskReconcilerWorkflow on the agent queue.
func UndispatchedTasksSchedule(agentQueue string) durable.Schedule {
	return durable.Schedule{
		ID: ScheduleUndispatchedTasks, Workflow: WorkflowUndispatchedTasks, WorkflowID: ScheduleUndispatchedTasks,
		TaskQueue: agentQueue, Every: []time.Duration{ReconcileEvery}, Overlap: durable.OverlapSkip,
	}
}

// CronSyncSchedule starts CronScheduleSyncWorkflow on the trigger queue.
func CronSyncSchedule(triggerQueue string) durable.Schedule {
	return durable.Schedule{
		ID: ScheduleCronSync, Workflow: WorkflowCronScheduleSync, WorkflowID: ScheduleCronSync,
		TaskQueue: triggerQueue, Every: []time.Duration{CronSyncEvery}, Overlap: durable.OverlapSkip,
	}
}

// CronTriggerScheduleID is the schedule of a cron trigger.
func CronTriggerScheduleID(triggerID string) string { return CronTriggerSchedulePrefix + triggerID }

// CronFiringData is what a cron trigger's schedule hands TriggerExecutionWorkflow
// besides the trigger id; the slot a firing is for is Temporal's
// TemporalScheduledStartTime, read by the workflow.
func CronFiringData(cronExpression, timezone string) map[string]any {
	return map[string]any{"source": "cron", "cron_expression": cronExpression, "timezone": timezone}
}

// CronTriggerSchedule is a cron trigger's schedule as the triggers table says
// it should be (TemporalScheduleManager._schedule).
func CronTriggerSchedule(triggerID, cronExpression, timezone, triggerQueue string, paused bool) durable.Schedule {
	return durable.Schedule{
		ID:            CronTriggerScheduleID(triggerID),
		Workflow:      WorkflowTriggerExecution,
		WorkflowID:    "trigger-execution-" + triggerID + "-{{.ScheduledTime}}",
		TaskQueue:     triggerQueue,
		Args:          []any{triggerID, CronFiringData(cronExpression, timezone)},
		Cron:          []string{cronExpression},
		TimeZone:      timezone,
		CatchupWindow: CronCatchupWindow,
		Paused:        paused,
		Note:          "Cron trigger schedule for trigger " + triggerID,
	}
}
