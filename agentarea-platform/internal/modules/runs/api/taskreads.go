package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// TaskReads is what other modules show of a workspace's tasks: a feed's task
// statuses, a trigger history's spend. An id that is not a UUID names nothing.
type TaskReads interface {
	// Statuses maps each id of a workspace task to its status (TaskRepository.statuses).
	Statuses(ctx context.Context, ws scope.Workspace, ids []string) (map[string]string, error)
	// Costs maps each id of a workspace task to its spend: the result's own_cost,
	// else its total_cost, else 0 (triggers.py _costs_by_task).
	Costs(ctx context.Context, ws scope.Workspace, ids []string) (map[string]float64, error)
}

// StoredTask is a task's status and workflow as a retried firing reads it back.
type StoredTask struct {
	Status      string
	ExecutionID string
}

// TaskOrigin is what started a task: its origin and the event that caused it.
type TaskOrigin struct {
	OriginType  string
	OriginID    string
	CausationID string
}

// FiringTasks is what a trigger firing reads and restarts of the tasks it started.
type FiringTasks interface {
	// Task reads a stored task; false when the workspace has none.
	Task(ctx context.Context, ws scope.Workspace, id string) (StoredTask, bool, error)
	// RestartUndispatched starts a stored task whose workflow never started,
	// under its stored policy, with message as its ask
	// (TaskService.restart_undispatched_task); a failed start leaves it failed.
	RestartUndispatched(ctx context.Context, ws scope.Workspace, id, message string) error
	// OpenRunFrom is the origin's oldest unended task whose workflow is still
	// open, "" when none (unfinished_runs_from plus workflow_is_open).
	OpenRunFrom(ctx context.Context, ws scope.Workspace, originType, originID string) (string, error)
	// Origin is a workspace task's provenance; false when it is gone.
	Origin(ctx context.Context, ws scope.Workspace, taskID string) (TaskOrigin, bool, error)
}
