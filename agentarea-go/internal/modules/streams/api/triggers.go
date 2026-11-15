package api

import (
	"context"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// TriggerSummary is one trigger as other modules read it (insights topology, task definition counts).
type TriggerSummary struct {
	ID               string
	Name             string
	AgentID          string
	TriggerType      string
	IsActive         bool
	StreamID         *string
	TaskDefinitionID *string
	CronExpression   *string
}

// Triggers is what other modules call on streams' triggers.
type Triggers interface {
	// CountByTaskDefinition counts the triggers that run a saved task (agents' TaskDefTriggers).
	CountByTaskDefinition(ctx context.Context, ws scope.Workspace, definitionID string) (int64, error)
	// ListTriggers lists the workspace's triggers, filtered to one agent when agentID is set (insights topology).
	ListTriggers(ctx context.Context, ws scope.Workspace, agentID *string) ([]TriggerSummary, error)
}

// CronRow is a cron trigger's schedule as its row says it should be (runs' schedule sync).
type CronRow struct {
	ID             string
	WorkspaceID    string
	CronExpression string
	TimeZone       string
	Active         bool
}

// TriggerState is a trigger found by id across workspaces (runs' trigger activities).
type TriggerState struct {
	ID          string
	Name        string
	WorkspaceID string
	Active      bool
}

// ExecutionRecord is one firing's outcome to write to trigger_executions.
type ExecutionRecord struct {
	Status        string
	ExecutionTime time.Duration
	TaskID        string
	ErrorMessage  string
	TriggerData   map[string]any
}

// RecordedExecution is the row a firing wrote.
type RecordedExecution struct {
	ID         string
	ExecutedAt time.Time
}

// CronTriggerCatchupWindow is how far back a missed cron tick is still fired.
const CronTriggerCatchupWindow = time.Hour

// CronTriggerSchedule is the schedule of cron trigger triggerID: it starts TriggerExecutionWorkflow
// with the trigger's id and the cron firing data, once per tick, on queue. Runs and streams build
// the same schedule through this function.
func CronTriggerSchedule(triggerID, cronExpression, timezone, queue string, paused bool) durable.Schedule {
	return durable.Schedule{
		ID:            "cron-trigger-" + triggerID,
		Workflow:      "TriggerExecutionWorkflow",
		WorkflowID:    "trigger-execution-" + triggerID + "-{{.ScheduledTime}}",
		TaskQueue:     queue,
		Args:          []any{triggerID, CronFiringData(cronExpression, timezone)},
		Cron:          []string{cronExpression},
		TimeZone:      timezone,
		CatchupWindow: CronTriggerCatchupWindow,
		Paused:        paused,
	}
}

// CronFiringData is the second argument of a cron schedule's workflow.
func CronFiringData(cronExpression, timezone string) map[string]any {
	return map[string]any{"source": "cron", "cron_expression": cronExpression, "timezone": timezone}
}
