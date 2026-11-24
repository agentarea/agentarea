package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// OutcomeTask is what the consumers of a task's events read of it: where it replies, whose it
// is, what started it and its place in a causation chain.
type OutcomeTask struct {
	ID            string
	AgentID       string
	Owner         string
	OriginType    string
	OriginID      string
	CorrelationID string
	Depth         int
	Parameters    map[string]any
	Metadata      map[string]any
}

// TaskOutcomes reads the task a task event names.
type TaskOutcomes interface {
	// OutcomeTask reads a workspace task; false when it is gone.
	OutcomeTask(ctx context.Context, ws scope.Workspace, id string) (OutcomeTask, bool, error)
}
