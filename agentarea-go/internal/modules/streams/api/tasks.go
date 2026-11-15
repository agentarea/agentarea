package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// TaskCost is a task's spend as the trigger history shows it (result own_cost, else total_cost).
type TaskCost struct {
	CostUSD *float64
}

// TaskReads is the task reads the events feed and the trigger history show.
type TaskReads interface {
	// Statuses maps each id of a workspace task to its status.
	Statuses(ctx context.Context, ws scope.Workspace, ids []string) (map[string]string, error)
	// Costs maps each id of a workspace task to its cost.
	Costs(ctx context.Context, ws scope.Workspace, ids []string) (map[string]TaskCost, error)
}

// StoredTask is a task as an idempotent retry reads it back.
type StoredTask struct {
	Status      string
	ExecutionID string
}

// TaskDefinition is a saved task a trigger runs: its text and parameters.
type TaskDefinition struct {
	Description string
	Parameters  map[string]any
}

// FiringTasks is what TriggerService.fire reads of tasks beside starting one.
type FiringTasks interface {
	// Task reads a stored task; false when there is none.
	Task(ctx context.Context, ws scope.Workspace, id string) (StoredTask, bool, error)
	// RestartUndispatched starts a stored task whose start failed, its message replaced
	// (TaskService.restart_undispatched_task).
	RestartUndispatched(ctx context.Context, ws scope.Workspace, id, message string) error
	// OpenRunFrom is the origin's task whose workflow is still open, "" when none
	// (unfinished_runs_from plus workflow_is_open).
	OpenRunFrom(ctx context.Context, ws scope.Workspace, originType, originID string) (string, error)
	// Definition reads a saved task definition of the workspace; false when it is gone.
	Definition(ctx context.Context, ws scope.Workspace, id string) (TaskDefinition, bool, error)
	// Origin is a workspace task's provenance as the loop guard walks it; false when it is gone.
	Origin(ctx context.Context, ws scope.Workspace, taskID string) (TaskOrigin, bool, error)
}

// TaskOrigin is what started a task (ChainTask): its origin and the event that caused it.
type TaskOrigin struct {
	OriginType  string
	OriginID    string
	CausationID string
}

// TriggerFire is one firing of a trigger by its schedule (runs' service.TriggerFire).
type TriggerFire struct {
	TriggerID     string
	Data          map[string]any
	TaskID        string
	OriginType    string
	OriginID      string
	CorrelationID string
}

// TriggerFiring is what a firing did (runs' service.TriggerFiring).
type TriggerFiring struct {
	Outcome     string
	Reason      string
	TaskID      string
	ExecutionID string
	BlockedBy   string
	Verdict     bool
}

// TriggerBatch is one open batch of a windowed stream trigger (runs' service.TriggerBatch).
type TriggerBatch struct {
	TriggerID      string
	SubscriptionID string
	WorkspaceID    string
	ConfiguredBy   string
	Caller         string
	WorkflowID     string
	EventIDs       []string
	Reason         string
}
